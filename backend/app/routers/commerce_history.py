"""Public «سفارش‌های من» history boundary — verified, read-only, no-store.

Four thin public routes under ``/api/v1/commerce/history``:

* ``POST /otp``      — send a history one-time code to the customer's mobile
* ``POST /verify``   — exchange the code for a short-lived bearer session
* ``GET  /``         — exact-mobile, redacted, bounded history (Bearer only)
* ``POST /sign-out`` — revoke the bearer session

plus the customer-initiated payment route:

* ``POST /invoices/{invoice_id}/pay`` — start (or resume) a payment for an
  approved invoice the verified mobile owns, through the chosen gateway

Boundary rules:

* The **only** credential is an explicit ``Authorization: Bearer <history
  token>`` header. Staff cookies and staff JWTs are deliberately not consulted,
  so a logged-in employee session can never read a customer's history and a
  blocked/expired history token never falls back to another auth scheme.
* The mobile is never a query or path parameter: it is resolved from the session
  server-side. IDs in responses are display identifiers, not credentials.
* Every response — success, 401, 400, 422 validation, 429 throttle, 503 delivery
  failure — carries ``Cache-Control: no-store`` and ``Referrer-Policy:
  no-referrer``. The handlers set them directly and a prefix middleware in
  ``app.main`` backstops the ones FastAPI/slowapi generate before a handler runs.
* Bodies forbid surplus fields (``extra='forbid'``) and validate an ASCII Iranian
  mobile, so a client cannot smuggle extra state or a non-canonical number.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CommerceInvoice
from app.routers.auth import limiter
from app.services import (
    bitpay,
    commerce,
    commerce_history,
    commerce_history_auth,
    commerce_notifications,
    commerce_otp,
    digipay,
)

router = APIRouter(prefix="/api/v1/commerce/history", tags=["commerce-history"])

# The session bearer is a private credential: never cache or leak it.
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

_UNAUTHORIZED = "نشست معتبر نیست؛ لطفاً دوباره شمارهٔ خود را تأیید کنید"


def _canonical_mobile(value: str) -> str:
    """Reuse the service's canonicalizer, surfacing failures as validation 422."""
    try:
        return commerce_history_auth.canonical_mobile(value)
    except commerce_history_auth.HistoryOtpInvalid as exc:
        raise ValueError(str(exc))


class HistoryOtpRequest(BaseModel):
    """Public payload for the history one-time-code endpoint."""

    model_config = ConfigDict(extra="forbid")

    mobile: str

    @field_validator("mobile")
    @classmethod
    def _valid_mobile(cls, value: str) -> str:
        return _canonical_mobile(value)


class HistoryVerifyRequest(BaseModel):
    """Public payload that exchanges a code for a session bearer."""

    model_config = ConfigDict(extra="forbid")

    mobile: str
    challenge_id: int = Field(..., ge=1)
    code: str = Field(..., min_length=1, max_length=16)

    @field_validator("mobile")
    @classmethod
    def _valid_mobile(cls, value: str) -> str:
        return _canonical_mobile(value)


class HistoryPayInvoiceRequest(BaseModel):
    """Public payload selecting the gateway for a customer-initiated payment.

    Only the two live gateways are accepted; ``digipay`` is the default so a
    bare ``{}`` body still starts the primary provider. Surplus fields are
    rejected so a client cannot smuggle an amount or a callback into the call.
    """

    model_config = ConfigDict(extra="forbid")

    gateway: str = Field(default="digipay", pattern="^(digipay|bitpay)$")


# Customer-facing refusals. Deliberately coarse: a foreign invoice and an
# unknown id are the same 404 so the route never discloses which ids exist.
_INVOICE_NOT_FOUND = "فاکتور یافت نشد"
_INVOICE_NOT_PAYABLE = "فاکتور در وضعیت قابل پرداخت نیست"
_INVOICE_EXPIRED = "مهلت پرداخت فاکتور به پایان رسیده است"


def _payment_error(exc: Exception) -> HTTPException:
    """Map a commerce domain error onto the matching public HTTP status.

    Mirrors ``app.routers.commerce._validation_error`` so the same service
    failure is surfaced identically through the customer boundary. Every mapped
    response keeps the no-store/no-referrer boundary.
    """
    if isinstance(exc, commerce.CommerceNotFoundError):
        status = 404
    elif isinstance(exc, commerce.CommerceGoneError):
        status = 410
    elif isinstance(exc, commerce.CommerceStateError):
        status = 409
    elif isinstance(exc, commerce.CommerceGatewayUnavailableError):
        status = 503
    elif isinstance(exc, commerce.CommercePaymentError):
        status = 502
    elif isinstance(exc, commerce.CommerceConfigError):
        return HTTPException(
            status_code=500,
            detail="پیکربندی درگاه پرداخت نامعتبر است",
            headers=dict(NO_STORE_HEADERS),
        )
    else:
        status = 400
    return HTTPException(status_code=status, detail=str(exc), headers=dict(NO_STORE_HEADERS))


def _start_customer_payment(db: Session, invoice: CommerceInvoice, gateway: str):
    """Start (or resume) a payment through the selected gateway.

    Each branch runs the *same* server-side readiness predicate its gateway
    route uses, before the provider is resolved, so a direct POST from the
    customer area can never run a checkout the deployment has not enabled. The
    private history bearer is never forwarded to a gateway.
    """
    if gateway == "bitpay":
        if not bitpay.checkout_allowed():
            raise HTTPException(
                status_code=503,
                detail="درگاه پرداخت بیت‌پی در این محیط غیرفعال است",
                headers=dict(NO_STORE_HEADERS),
            )
        try:
            client = bitpay.get_client()
        except bitpay.BitPayConfigError:
            raise HTTPException(
                status_code=503,
                detail="درگاه پرداخت پیکربندی نشده است",
                headers=dict(NO_STORE_HEADERS),
            )
        try:
            callback_url = bitpay.build_callback_url()
        except (bitpay.BitPayConfigError, commerce.CommerceConfigError) as exc:
            raise HTTPException(
                status_code=500,
                detail="پیکربندی درگاه پرداخت نامعتبر است",
                headers=dict(NO_STORE_HEADERS),
            ) from exc
        try:
            return commerce.start_bitpay_payment(db, invoice, client, callback_url=callback_url)
        except (
            commerce.CommerceValidationError,
            commerce.CommerceNotFoundError,
            commerce.CommerceGoneError,
            commerce.CommerceStateError,
            commerce.CommerceConfigError,
            commerce.CommercePaymentError,
            commerce.CommerceGatewayUnavailableError,
        ) as exc:
            raise _payment_error(exc) from exc

    # Default: DigiPay.
    if not digipay.checkout_enabled():
        raise HTTPException(
            status_code=503,
            detail="درگاه پرداخت دیجی‌پی در این محیط غیرفعال است",
            headers=dict(NO_STORE_HEADERS),
        )
    try:
        client = digipay.get_client()
    except digipay.DigiPayConfigError:
        raise HTTPException(
            status_code=503,
            detail="درگاه پرداخت پیکربندی نشده است",
            headers=dict(NO_STORE_HEADERS),
        )
    try:
        callback_url = digipay.build_callback_url()
    except digipay.DigiPayConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail="پیکربندی درگاه پرداخت نامعتبر است",
            headers=dict(NO_STORE_HEADERS),
        ) from exc
    try:
        return commerce.start_payment(db, invoice, client, callback_url=callback_url)
    except (
        commerce.CommerceValidationError,
        commerce.CommerceNotFoundError,
        commerce.CommerceGoneError,
        commerce.CommerceStateError,
        commerce.CommerceConfigError,
        commerce.CommercePaymentError,
        commerce.CommerceGatewayUnavailableError,
    ) as exc:
        raise _payment_error(exc) from exc


def _bearer_from_header(authorization: str | None) -> str | None:
    """Extract a raw bearer from an ``Authorization`` header, else ``None``.

    Only the exact ``Bearer <token>`` scheme is accepted; anything else — a bare
    token, another scheme, an empty value — is a missing credential. No cookie is
    ever read.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def current_history_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[str, str]:
    """Require a live history bearer; returns ``(raw_bearer, canonical_mobile)``.

    A missing/malformed header, an unknown token and an expired/revoked token are
    all indistinguishable ``401`` — the failure never reveals whether a number
    has orders.
    """
    bearer = _bearer_from_header(authorization)
    mobile = commerce_history_auth.resolve_history_session(db, bearer)
    if mobile is None:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED, headers=NO_STORE_HEADERS)
    return bearer, mobile


@router.post("/otp")
@limiter.limit("3/minute")
def request_history_otp(
    request: Request,
    response: Response,
    body: HistoryOtpRequest,
    db: Session = Depends(get_db),
):
    """Public — send a history one-time code to the customer's own mobile.

    ``request`` MUST be the first parameter: slowapi resolves the client key from
    it. A resend cooldown or hourly cap answers 429; a transport failure answers
    503. The code is never echoed and the response never discloses whether the
    number has any orders.
    """
    response.headers.update(NO_STORE_HEADERS)
    client_ip = request.client.host if request.client else None
    try:
        challenge = commerce_history_auth.issue_history_challenge(
            db, body.mobile, client_ip=client_ip
        )
    except commerce_history_auth.HistoryOtpThrottled as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except commerce_history_auth.HistoryOtpDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "challenge_id": challenge.id,
        "expires_in": commerce_history_auth.HISTORY_OTP_TTL_SECONDS,
        "resend_after": commerce_otp.OTP_RESEND_COOLDOWN_SECONDS,
        "delivery": "sms",
        "masked_mobile": commerce_notifications.mask_mobile(body.mobile),
    }


@router.post("/verify")
@limiter.limit("5/minute")
def verify_history_otp(
    request: Request,
    response: Response,
    body: HistoryVerifyRequest,
    db: Session = Depends(get_db),
):
    """Public — exchange a valid history code for a short-lived bearer session.

    A wrong/expired/unknown code is a generic ``400``. On success the challenge is
    consumed and the session is stored (hash only) atomically; the raw bearer is
    returned exactly once and lives only in the customer's tab.
    """
    response.headers.update(NO_STORE_HEADERS)
    try:
        token, expires_at = commerce_history_auth.verify_history_challenge(
            db, body.challenge_id, body.code, body.mobile
        )
    except commerce_history_auth.HistoryOtpInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.get("")
@limiter.limit("30/minute")
def read_history(
    request: Request,
    response: Response,
    limit: int = Query(
        default=commerce_history.HISTORY_DEFAULT_LIMIT,
        ge=1,
        le=commerce_history.HISTORY_MAX_LIMIT,
    ),
    offset: int = Query(default=0, ge=0, le=commerce_history.HISTORY_MAX_OFFSET),
    session: tuple[str, str] = Depends(current_history_session),
    db: Session = Depends(get_db),
):
    """Public — the verified mobile's own requests and invoices, newest first.

    Bounded and redacted. ``has_more`` is derived from a single ``limit + 1``
    fetch so the client can page without a count query.
    """
    response.headers.update(NO_STORE_HEADERS)
    _, mobile = session
    rows = commerce_history.list_history(db, mobile, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    return {"items": rows[:limit], "has_more": has_more}


@router.get("/profile")
@limiter.limit("30/minute")
def read_customer_profile(
    request: Request,
    response: Response,
    session: tuple[str, str] = Depends(current_history_session),
    db: Session = Depends(get_db),
):
    """Public — the verified mobile's identity, saved addresses and order counts."""
    response.headers.update(NO_STORE_HEADERS)
    _, mobile = session
    return commerce_history.get_customer_profile(db, mobile)


@router.post("/invoices/{invoice_id}/pay")
@limiter.limit("10/minute")
def pay_customer_invoice(
    request: Request,
    response: Response,
    body: HistoryPayInvoiceRequest,
    invoice_id: int = Path(..., ge=1),
    session: tuple[str, str] = Depends(current_history_session),
    db: Session = Depends(get_db),
):
    """Public — start (or resume) a payment for one of the customer's invoices.

    The verified history bearer is the only credential and the invoice must
    belong to *that exact* mobile, so a signed-in customer can never pay — or
    even probe the existence of — another number's invoice. The invoice must be
    ``approved`` and its private link unexpired; a foreign/unknown id and a
    draft/paid/revoked invoice are refused without disclosure.

    Initiation runs through the same service and the *same* per-gateway
    readiness predicate as the token-based pay routes, returning the provider's
    HTTPS ``redirect_url`` for the browser to follow. The private bearer is
    never forwarded to a gateway.
    """
    response.headers.update(NO_STORE_HEADERS)
    _, mobile = session

    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).first()
    # Ownership is asserted *before* any state is revealed: a foreign invoice is
    # indistinguishable from an unknown id.
    if invoice is None or invoice.mobile != mobile:
        raise HTTPException(status_code=404, detail=_INVOICE_NOT_FOUND)
    if invoice.state != "approved":
        raise HTTPException(status_code=400, detail=_INVOICE_NOT_PAYABLE)
    if commerce.is_link_expired(invoice):
        raise HTTPException(status_code=400, detail=_INVOICE_EXPIRED)

    attempt = _start_customer_payment(db, invoice, body.gateway)
    return {"redirect_url": attempt.redirect_url}


@router.post("/sign-out")
def sign_out_history(
    response: Response,
    session: tuple[str, str] = Depends(current_history_session),
    db: Session = Depends(get_db),
):
    """Public — revoke the presented bearer session server-side (idempotent).

    Requires a live bearer (an invalid one is ``401``); revoking is silent and
    idempotent, so a retry cannot fail the customer's sign-out.
    """
    response.headers.update(NO_STORE_HEADERS)
    bearer, _ = session
    commerce_history_auth.revoke_history_session(db, bearer)
    return {"ok": True}
