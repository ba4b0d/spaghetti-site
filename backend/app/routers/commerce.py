"""Commerce router — website cart requests and staff-reviewed invoices.

Public:
    POST /api/v1/commerce/requests          submit a cart request (pending review)
    GET  /api/v1/commerce/invoices/{token}  minimal read of an approved invoice

Staff:
    GET  /api/v1/commerce/staff/requests    review queue with item snapshots
    POST /api/v1/commerce/staff/invoices    create a draft invoice (request/manual)
    GET  /api/v1/commerce/staff/invoices    invoice queue
    PUT  /api/v1/commerce/staff/invoices/{id}          revise (drops to draft, kills link)
    POST /api/v1/commerce/staff/invoices/{id}/approve  freeze + issue private link
    POST /api/v1/commerce/staff/invoices/{id}/revoke   invalidate the private link
    POST /api/v1/commerce/staff/invoices/{id}/notify   re-emit admin alert (retry)
    POST /api/v1/commerce/staff/requests/{id}/notify   re-emit request alert (retry)

Payment initiation/callback arrive in Task 3. Handlers stay thin; validation
and persistence live in ``app.services.commerce``.
"""
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy.orm import Session

from app.audit import log_user
from app.database import get_db
from app.routers.auth import limiter, require_staff_role
from app.services import commerce as commerce_service
from app.services import commerce_notifications
from app.services import digipay
from app.services.commerce import (
    MAX_DISTINCT_PRODUCTS,
    MAX_INVOICE_ITEMS,
    MAX_INVOICE_ITEM_QTY,
    MAX_INVOICE_TOTAL_TOMAN,
    MAX_QTY,
    MIN_QTY,
    CommerceValidationError,
)

router = APIRouter(prefix="/api/v1/commerce", tags=["commerce"])

VALID_MESSENGERS = ("telegram", "bale")

# The public invoice read carries a private bearer token in its URL and body:
# never let a browser, intermediary proxy or Referer header cache or leak it.
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _normalize_mobile(value: str) -> str:
    """Validate an Iranian mobile number; ASCII digits only.

    ``str.isdigit()`` is true for Arabic-Indic / Persian digits and
    ``startswith("09")`` only checks two ASCII chars, so a mixed value like
    ``"09١٢٣٤٥٦٧٨٩"`` would otherwise be stored undialable.
    """
    value = (value or "").strip()
    if (
        len(value) != 11
        or not value.startswith("09")
        or not all("0" <= c <= "9" for c in value)
    ):
        raise ValueError("شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود")
    return value


def _validation_error(exc: Exception) -> HTTPException:
    """Map a domain exception onto the matching HTTP status."""
    if isinstance(exc, commerce_service.CommerceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, commerce_service.CommerceGoneError):
        return HTTPException(status_code=410, detail=str(exc))
    if isinstance(exc, commerce_service.CommerceStateError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, commerce_service.CommerceGatewayUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, commerce_service.CommercePaymentError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, commerce_service.CommerceConfigError):
        return HTTPException(status_code=500, detail="پیکربندی آدرس عمومی سایت نامعتبر است")
    return HTTPException(status_code=400, detail=str(exc))


class CommerceRequestItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(..., ge=1)
    qty: int = Field(..., ge=MIN_QTY, le=MAX_QTY)


class CommerceRequestCreate(BaseModel):
    # Surplus fields — including any client-supplied price — are rejected with
    # a 422 rather than silently ignored (Task 1 brief: "disallow surplus
    # fields on the public payload to avoid silent price acceptance"). The
    # server snapshots catalogue data and never trusts a client amount.
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(..., min_length=1, max_length=120)
    mobile: str
    messenger: str
    messenger_handle: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)
    items: list[CommerceRequestItemIn] = Field(..., min_length=1, max_length=MAX_DISTINCT_PRODUCTS)

    @field_validator("customer_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("نام مشتری الزامی است")
        return value

    @field_validator("mobile")
    @classmethod
    def _valid_iranian_mobile(cls, value: str) -> str:
        return _normalize_mobile(value)

    @field_validator("messenger")
    @classmethod
    def _valid_messenger(cls, value: str) -> str:
        if value not in VALID_MESSENGERS:
            raise ValueError("پیامرسان نامعتبر است")
        return value

    @model_validator(mode="after")
    def _distinct_products(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("محصول تکراری در سبد خرید مجاز نیست")
        return self


@router.post("/requests")
@limiter.limit("5/minute")
def create_request(
    request: Request,
    background_tasks: BackgroundTasks,
    body: CommerceRequestCreate,
    db: Session = Depends(get_db),
):
    """Public — record a pending-review website cart request.

    Returns an opaque receipt identifier only; no invoice or payment link is
    produced before staff review. The admin alert is dispatched as a *background*
    task after the response, so a slow Telegram/SMS/SMTP transport cannot delay
    the customer's acknowledgement.
    """
    try:
        created = commerce_service.create_website_request(
            db,
            customer_name=body.customer_name,
            mobile=body.mobile,
            messenger=body.messenger,
            messenger_handle=body.messenger_handle,
            address=body.address,
            note=body.note,
            items=[{"product_id": i.product_id, "qty": i.qty} for i in body.items],
            background_tasks=background_tasks,
        )
    except CommerceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return commerce_service.serialize_public_receipt(created)


@router.get("/staff/requests")
def list_staff_requests(
    state: str | None = Query(default=None, max_length=20),
    limit: int = Query(
        default=commerce_service.DEFAULT_LIST_LIMIT,
        ge=1,
        le=commerce_service.MAX_LIST_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — newest-first request queue with product snapshots.

    Bounded (``limit``/``offset``) and optionally filtered by ``state`` so the
    queue cannot return the whole table; the response stays a plain array so
    existing clients keep working.
    """
    rows = commerce_service.list_staff_requests(db, limit=limit, offset=offset, state=state)
    return [commerce_service.serialize_staff_request(r) for r in rows]


# ── Task 2: staff invoices ───────────────────────────────────────────

class InvoiceItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional catalogue link; custom/manual lines carry no product.
    product_id: StrictInt | None = Field(default=None, ge=1)
    description: str = Field(..., min_length=1, max_length=255)
    qty: StrictInt = Field(..., ge=1, le=MAX_INVOICE_ITEM_QTY)
    unit_toman: StrictInt = Field(..., ge=1, le=MAX_INVOICE_TOTAL_TOMAN)

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("شرح آیتم الزامی است")
        return value


class InvoiceWrite(BaseModel):
    """Full invoice payload, used for both staff create and revise (PUT)."""

    model_config = ConfigDict(extra="forbid")

    # Links a website request; omitted for manual/chat invoices. Ignored on
    # PUT so a revision cannot silently re-point the invoice at another request.
    request_id: StrictInt | None = Field(default=None, ge=1)
    customer_name: str = Field(..., min_length=1, max_length=120)
    mobile: str
    messenger: str = "telegram"
    messenger_handle: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=500)
    # Customer-visible finalized specification.
    specification: str = Field(default="", max_length=2000)
    # Staff-only note; never returned by any public endpoint.
    internal_note: str = Field(default="", max_length=2000)
    shipping_toman: StrictInt = Field(default=0, ge=0, le=MAX_INVOICE_TOTAL_TOMAN)
    items: list[InvoiceItemIn] = Field(..., min_length=1, max_length=MAX_INVOICE_ITEMS)

    @field_validator("customer_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("نام مشتری الزامی است")
        return value

    @field_validator("mobile")
    @classmethod
    def _valid_iranian_mobile(cls, value: str) -> str:
        return _normalize_mobile(value)

    @field_validator("messenger")
    @classmethod
    def _valid_messenger(cls, value: str) -> str:
        if value not in VALID_MESSENGERS:
            raise ValueError("پیامرسان نامعتبر است")
        return value


def _item_dicts(body: InvoiceWrite) -> list[dict]:
    return [
        {
            "product_id": i.product_id,
            "description": i.description,
            "qty": i.qty,
            "unit_toman": i.unit_toman,
        }
        for i in body.items
    ]


@router.post("/staff/invoices", status_code=201)
def create_staff_invoice(
    body: InvoiceWrite,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — draft an invoice from a website request or a manual order."""
    try:
        invoice = commerce_service.create_staff_invoice(
            db,
            request_id=body.request_id,
            customer_name=body.customer_name,
            mobile=body.mobile,
            messenger=body.messenger,
            messenger_handle=body.messenger_handle,
            address=body.address,
            specification=body.specification,
            internal_note=body.internal_note,
            shipping_toman=body.shipping_toman,
            items=_item_dicts(body),
        )
    except (
        CommerceValidationError,
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceStateError,
        commerce_service.CommerceConfigError,
    ) as exc:
        raise _validation_error(exc)
    payload = commerce_service.serialize_staff_invoice(invoice)
    log_user(
        user, db, "create", "commerce_invoice", invoice.id,
        f"ایجاد پیش‌نویس فاکتور #{invoice.id}",
    )
    return payload


@router.get("/staff/invoices")
def list_staff_invoices(
    state: str | None = Query(default=None, max_length=20),
    limit: int = Query(
        default=commerce_service.DEFAULT_LIST_LIMIT,
        ge=1,
        le=commerce_service.MAX_LIST_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — newest-first invoice queue."""
    try:
        rows = commerce_service.list_staff_invoices(
            db, limit=limit, offset=offset, state=state
        )
    except CommerceValidationError as exc:
        raise _validation_error(exc)
    return [commerce_service.serialize_staff_invoice(r) for r in rows]


@router.put("/staff/invoices/{invoice_id}")
def update_staff_invoice(
    invoice_id: int,
    body: InvoiceWrite,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — revise a non-settled invoice (bumps revision, drops to draft).

    The previous private link is invalidated; the invoice must be approved
    again to obtain a fresh one.
    """
    try:
        invoice = commerce_service.update_staff_invoice(
            db,
            invoice_id,
            customer_name=body.customer_name,
            mobile=body.mobile,
            messenger=body.messenger,
            messenger_handle=body.messenger_handle,
            address=body.address,
            specification=body.specification,
            internal_note=body.internal_note,
            shipping_toman=body.shipping_toman,
            items=_item_dicts(body),
        )
    except (
        CommerceValidationError,
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceStateError,
        commerce_service.CommerceConfigError,
    ) as exc:
        raise _validation_error(exc)
    payload = commerce_service.serialize_staff_invoice(invoice)
    log_user(
        user, db, "update", "commerce_invoice", invoice.id,
        f"ویرایش فاکتور #{invoice.id}",
    )
    return payload


@router.post("/staff/invoices/{invoice_id}/approve")
def approve_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — freeze the invoice and return the one-time private share link.

    The approval alert is dispatched as a *background* task after the response,
    so a slow transport cannot delay the staff UI.
    """
    try:
        invoice, raw_token = commerce_service.approve_invoice(
            db, invoice_id, background_tasks=background_tasks
        )
        share_url = commerce_service.build_share_url(raw_token)
    except (
        CommerceValidationError,
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceStateError,
        commerce_service.CommerceConfigError,
    ) as exc:
        raise _validation_error(exc)
    # Audit the approval without ever writing the raw token or share URL: only
    # the invoice identity and state transition belong in the log.
    log_user(
        user, db, "approve", "commerce_invoice", invoice.id,
        f"تأیید و صدور لینک فاکتور #{invoice.id}",
    )
    return {
        "id": invoice.id,
        "state": invoice.state,
        "revision": invoice.revision,
        "share_url": share_url,
        "expires_at": (
            invoice.token_expires_at.isoformat() if invoice.token_expires_at else None
        ),
    }


@router.post("/staff/invoices/{invoice_id}/revoke")
def revoke_invoice(
    invoice_id: int,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — invalidate the private link."""
    try:
        invoice = commerce_service.revoke_invoice(db, invoice_id)
    except (
        CommerceValidationError,
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceStateError,
        commerce_service.CommerceConfigError,
    ) as exc:
        raise _validation_error(exc)
    payload = commerce_service.serialize_staff_invoice(invoice)
    log_user(
        user, db, "revoke", "commerce_invoice", invoice.id,
        f"لغو فاکتور #{invoice.id}",
    )
    return payload


@router.post("/staff/requests/{request_id}/notify")
@limiter.limit("10/minute")
def resend_request_notification(
    request: Request,
    request_id: int,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — re-emit the ``request_created`` admin alert for a website request.

    There is no durable outbox, so a channel that was down (or unconfigured) when
    the request first arrived can be retried explicitly here. The request is never
    mutated; the response reports the per-channel result so staff can see whether
    the retry landed. Rate-limited because each call fans out to live transports.
    """
    try:
        row = commerce_service.get_staff_request(db, request_id)
    except commerce_service.CommerceNotFoundError as exc:
        raise _validation_error(exc)

    channels = commerce_notifications.notify_admin(
        commerce_notifications.EVENT_REQUEST_CREATED, row
    )
    log_user(
        user, db, "notify", "commerce_request", row.id,
        f"ارسال مجدد اطلاع درخواست #{row.id}",
    )
    return {
        "request_id": row.id,
        "event": commerce_notifications.EVENT_REQUEST_CREATED,
        "channels": channels,
    }


@router.post("/staff/invoices/{invoice_id}/notify")
@limiter.limit("10/minute")
def resend_invoice_notification(
    request: Request,
    invoice_id: int,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — re-emit the admin notification for an invoice's current state.

    There is no durable outbox, so a channel that was down (or unconfigured)
    when ``invoice_approved`` / ``payment_verified`` originally fired can be
    retried explicitly here. The invoice is never mutated; the response reports
    the per-channel result (``sent`` / ``skipped`` / ``failed``) so staff can
    see whether the retry actually landed. Rate-limited because each call fans
    out to live transports.
    """
    try:
        invoice = commerce_service.get_staff_invoice(db, invoice_id)
    except commerce_service.CommerceNotFoundError as exc:
        raise _validation_error(exc)

    if invoice.state == "paid":
        event = commerce_notifications.EVENT_PAYMENT_VERIFIED
    elif invoice.state == "approved":
        event = commerce_notifications.EVENT_INVOICE_APPROVED
    else:
        raise HTTPException(
            status_code=400, detail="فاکتور در وضعیتی نیست که اطلاعرسانی داشته باشد"
        )

    channels = commerce_notifications.notify_admin(event, invoice)
    log_user(
        user, db, "notify", "commerce_invoice", invoice.id,
        f"ارسال مجدد اطلاع فاکتور #{invoice.id}",
    )
    return {"invoice_id": invoice.id, "event": event, "channels": channels}


@router.get("/invoices/{token}")
@limiter.limit("30/minute")
def read_public_invoice(
    request: Request,
    response: Response,
    token: str = Path(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
):
    """Public — minimal read of an approved invoice behind its private token.

    Returns no customer contact details and no staff-only notes. Expired
    links answer 410; unknown or revoked tokens answer 404. Every response —
    success or error — carries ``Cache-Control: no-store`` and
    ``Referrer-Policy: no-referrer`` so the private bearer URL is never cached
    or leaked through a referrer.
    """
    response.headers.update(NO_STORE_HEADERS)
    try:
        invoice = commerce_service.resolve_public_invoice(db, token)
    except (
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceGoneError,
    ) as exc:
        http_exc = _validation_error(exc)
        http_exc.headers = {**(http_exc.headers or {}), **NO_STORE_HEADERS}
        raise http_exc
    return commerce_service.serialize_public_invoice(invoice)


# ── Task 3: public payment initiation ────────────────────────────────

@router.post("/invoices/{token}/pay")
@limiter.limit("10/minute")
def pay_invoice(
    request: Request,
    response: Response,
    token: str = Path(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
    client=Depends(digipay.client_dependency),
):
    """Public — start (or resume) a DigiPay UPG payment for an approved invoice.

    Creates a durable ``CommercePaymentAttempt``, requests a business ticket and
    returns the provider's HTTPS ``redirect_url``. Valid only for an approved,
    unexpired, unpaid invoice; repeated clicks while an attempt is in flight are
    idempotent. The private bearer token is never forwarded to the gateway.
    """
    response.headers.update(NO_STORE_HEADERS)

    if client is None:
        try:
            client = digipay.get_client()
        except digipay.DigiPayConfigError:
            http_exc = HTTPException(status_code=503, detail="درگاه پرداخت پیکربندی نشده است")
            http_exc.headers = {**NO_STORE_HEADERS}
            raise http_exc

    try:
        callback_url = digipay.build_callback_url()
    except digipay.DigiPayConfigError as exc:
        http_exc = HTTPException(status_code=500, detail="پیکربندی درگاه پرداخت نامعتبر است")
        http_exc.headers = {**NO_STORE_HEADERS}
        raise http_exc from exc

    try:
        invoice = commerce_service.resolve_public_invoice(db, token)
        attempt = commerce_service.start_payment(db, invoice, client, callback_url=callback_url)
    except (
        CommerceValidationError,
        commerce_service.CommerceNotFoundError,
        commerce_service.CommerceGoneError,
        commerce_service.CommerceStateError,
        commerce_service.CommerceConfigError,
        commerce_service.CommercePaymentError,
        commerce_service.CommerceGatewayUnavailableError,
    ) as exc:
        http_exc = _validation_error(exc)
        http_exc.headers = {**(http_exc.headers or {}), **NO_STORE_HEADERS}
        raise http_exc

    return {
        "state": attempt.state,
        "amount_rial": attempt.amount_rial,
        "redirect_url": attempt.redirect_url,
    }


# ── Task 3: staff payment reconciliation ─────────────────────────────

class PaymentReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "verify" re-queries the provider (only when the callback pinned a method);
    # "abandon" is an explicit staff decision to release a stuck attempt.
    action: str = Field(default="verify", pattern="^(verify|abandon)$")
    reason: str = Field(default="", max_length=200)


@router.get("/staff/payments")
def list_staff_payments(
    state: str | None = Query(default=None, max_length=20),
    min_age_seconds: int | None = Query(default=None, ge=0),
    limit: int = Query(
        default=commerce_service.DEFAULT_LIST_LIMIT,
        ge=1,
        le=commerce_service.MAX_LIST_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — in-flight/stuck payment attempts needing attention (bounded).

    Read-only: listing never resolves an attempt, it only surfaces the ones
    that are no longer progressing so a human can reconcile them. Aging
    (``min_age_seconds``) only filters/re-orders; it never changes state.
    """
    try:
        rows = commerce_service.list_stuck_payment_attempts(
            db,
            state=state,
            min_age_seconds=min_age_seconds,
            limit=limit,
            offset=offset,
        )
    except CommerceValidationError as exc:
        raise _validation_error(exc)
    return [commerce_service.serialize_staff_payment_attempt(r) for r in rows]


@router.post("/staff/payments/{attempt_id}/reconcile")
def reconcile_staff_payment(
    attempt_id: int,
    body: PaymentReconcileRequest,
    background_tasks: BackgroundTasks,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
    client=Depends(digipay.client_dependency),
):
    """Staff — resolve a stuck attempt (re-query the provider, or abandon it).

    A payment is never failed on age alone: ``verify`` fails only on a
    provider-confirmed non-success, and ``abandon`` is an explicit, audited
    staff decision (requiring a reason) that releases the invoice lock.
    """
    from app.models import CommercePaymentAttempt

    attempt = (
        db.query(CommercePaymentAttempt)
        .filter(CommercePaymentAttempt.id == attempt_id)
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="تراکنش یافت نشد")

    if body.action == "abandon" and not body.reason.strip():
        # Guard against a silent abandon: releasing a lock on a possibly-paid
        # attempt without a recorded reason could lead to a second payment.
        raise HTTPException(
            status_code=422,
            detail="برای رهاسازی تراکنش، ثبت دلیل الزامی است",
        )

    if client is None and body.action == "verify":
        try:
            client = digipay.get_client()
        except digipay.DigiPayConfigError:
            # Unconfigured gateway: reconcile() keeps the attempt open rather
            # than guessing an outcome.
            client = None

    try:
        resolved = commerce_service.reconcile_payment_attempt(
            db, attempt, client, abandon=(body.action == "abandon"), reason=body.reason,
            background_tasks=background_tasks,
        )
    except commerce_service.CommerceValidationError as exc:
        raise _validation_error(exc)
    except commerce_service.CommerceGatewayUnavailableError as exc:
        raise _validation_error(exc)

    log_user(
        user, db, "reconcile", "commerce_payment_attempt", resolved.id,
        f"تسویه دستی تراکنش #{resolved.id} → {resolved.state}",
    )
    return commerce_service.serialize_staff_payment_attempt(resolved)
