"""Public «سفارش‌های من» history boundary — verified, read-only, no-store.

Four thin public routes under ``/api/v1/commerce/history``:

* ``POST /otp``      — send a history one-time code to the customer's mobile
* ``POST /verify``   — exchange the code for a short-lived bearer session
* ``GET  /``         — exact-mobile, redacted, bounded history (Bearer only)
* ``POST /sign-out`` — revoke the bearer session

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
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import limiter
from app.services import commerce_history, commerce_history_auth, commerce_notifications, commerce_otp

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
