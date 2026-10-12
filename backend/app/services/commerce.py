"""Commerce domain service — website cart requests (Task 1 slice).

Keeps request intake validation, catalogue snapshots and serialization out of
the HTTP layer. Invoice creation, approval and payment live in later tasks and
extend this module.

Design rules enforced here (see plan Global Constraints):
- The storefront is never an authoritative price source; client prices are
  ignored and indicative prices come from the server-side catalogue snapshot.
- Only *active* catalogue products may be requested.
- Money kept as integer Toman; no floating point math on amounts.
"""
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    COMMERCE_INVOICE_STATES,
    INVOICE_LINK_TTL_DAYS,
    MAX_INVOICE_TOTAL_TOMAN,
    AuditLog,
    CommerceInvoice,
    CommerceInvoiceItem,
    CommercePaymentAttempt,
    CommerceRequest,
    CommerceRequestItem,
    Order,
    OrderItem,
    Product,
)
from app.services import commerce_notifications

_logger = logging.getLogger(__name__)

# Public payload envelope (mirrors the Pydantic constraints in the router).
MAX_DISTINCT_PRODUCTS = 30
MIN_QTY = 1
MAX_QTY = 99

# Staff review-queue bounds (query parameters, enforced again in the router).
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 200

# Public receipt prefix — opaque, not a primary key.
RECEIPT_PREFIX = "REQ"


class CommerceValidationError(Exception):
    """Domain-level rejection of a public commerce payload (maps to HTTP 400)."""


def _emit_admin_notification(event: str, subject, background_tasks=None) -> None:
    """Snapshot an *after-commit* admin notification; never affects the transaction.

    Called only once a state change is committed. The payload is built while the
    session is still open and handed to ``BackgroundTasks`` (``background_tasks``)
    so the HTTP response is not gated by a slow Telegram/SMS/SMTP round-trip; with
    no task runner it is delivered inline. Any unexpected error is logged and
    swallowed so it can never roll back or fail a committed order/invoice.
    """
    try:
        commerce_notifications.schedule_admin_delivery(background_tasks, event, subject)
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        _logger.warning("admin notification failed event=%s: %s", event, exc)


def generate_receipt_id() -> str:
    """Opaque, non-sequential public receipt identifier."""
    return f"{RECEIPT_PREFIX}-{secrets.token_hex(6).upper()}"


def _indicative_price_toman(product: Product) -> int | None:
    """Integer-Toman catalogue estimate, or None when the catalogue has no price."""
    price = product.final_price
    if price is None:
        return None
    price_int = int(price)
    return price_int if price_int > 0 else None


def prepare_website_request(
    db: Session,
    *,
    customer_name: str,
    mobile: str,
    messenger: str,
    messenger_handle: str = "",
    address: str = "",
    note: str = "",
    items: list[dict],
) -> CommerceRequest:
    """Validate + build a pending-review website request and flush it.

    Same validation as ``create_website_request`` but deliberately does **not**
    commit: the caller owns the transaction boundary so the request can be
    committed atomically alongside another change (e.g. consuming the cart
    OTP), making a rejected creation roll both back together. Returns the
    request with ``id``/``items`` populated via ``flush()``.

    ``items`` is a list of ``{"product_id": int, "qty": int}``. Any other keys
    (including client-supplied prices) are deliberately ignored.
    """
    if not items:
        raise CommerceValidationError("سبد خرید خالی است")

    if not address or len(address.strip()) < 5:
        raise CommerceValidationError("نشانی تحویل الزامی است")

    # Normalise + collapse to distinct product IDs.
    normalized: list[tuple[int, int]] = []
    seen_ids: set[int] = set()
    for raw in items:
        try:
            product_id = int(raw["product_id"])
            qty = int(raw["qty"])
        except (KeyError, TypeError, ValueError):
            raise CommerceValidationError("آیتم سبد خرید نامعتبر است")
        if product_id in seen_ids:
            raise CommerceValidationError("محصول تکراری در سبد خرید")
        if qty < MIN_QTY or qty > MAX_QTY:
            raise CommerceValidationError("تعداد نامعتبر است")
        seen_ids.add(product_id)
        normalized.append((product_id, qty))

    if len(normalized) > MAX_DISTINCT_PRODUCTS:
        raise CommerceValidationError("تعداد محصولات سبد خرید بیش از حد مجاز است")

    # Only active catalogue products can be requested.
    active_products = {
        p.id: p
        for p in db.query(Product).filter(
            Product.id.in_(seen_ids), Product.is_active == True  # noqa: E712
        ).all()
    }
    missing = [pid for pid, _ in normalized if pid not in active_products]
    if missing:
        raise CommerceValidationError("برخی محصولات موجود یا فعال نیستند")

    request = CommerceRequest(
        receipt_id=generate_receipt_id(),
        customer_name=customer_name.strip(),
        mobile=mobile.strip(),
        messenger=messenger,
        messenger_handle=(messenger_handle or "").strip(),
        address=(address or "").strip(),
        note=(note or "").strip(),
        state="pending_review",
    )
    for product_id, qty in normalized:
        product = active_products[product_id]
        request.items.append(
            CommerceRequestItem(
                product_id=product.id,
                display_name=product.name,
                qty=qty,
                indicative_unit_price_toman=_indicative_price_toman(product),
            )
        )

    db.add(request)
    db.flush()  # assign request.id / item rows without ending the transaction
    return request


def notify_request_created(request: CommerceRequest, *, background_tasks=None) -> None:
    """After-commit admin alert that a website request arrived. Never raises.

    Public wrapper around ``_emit_admin_notification`` so a caller that commits
    the request itself (rather than via ``create_website_request``) can still
    fire the alert once the transaction is durable.
    """
    _emit_admin_notification(
        commerce_notifications.EVENT_REQUEST_CREATED, request,
        background_tasks=background_tasks,
    )


def create_website_request(
    db: Session,
    *,
    customer_name: str,
    mobile: str,
    messenger: str,
    messenger_handle: str = "",
    address: str = "",
    note: str = "",
    items: list[dict],
    background_tasks=None,
) -> CommerceRequest:
    """Persist a pending-review website request with server-side item snapshots.

    Commits the request then, after commit, alerts staff (delivery deferred to
    ``background_tasks`` when provided). ``items`` is a list of
    ``{"product_id": int, "qty": int}``; any other keys (including
    client-supplied prices) are deliberately ignored.
    """
    request = prepare_website_request(
        db,
        customer_name=customer_name,
        mobile=mobile,
        messenger=messenger,
        messenger_handle=messenger_handle,
        address=address,
        note=note,
        items=items,
    )
    db.commit()
    db.refresh(request)
    notify_request_created(request, background_tasks=background_tasks)
    return request


def serialize_request_item(item: CommerceRequestItem) -> dict:
    return {
        "product_id": item.product_id,
        "display_name": item.display_name,
        "qty": item.qty,
        "indicative_unit_price_toman": item.indicative_unit_price_toman,
    }


def serialize_public_receipt(request: CommerceRequest) -> dict:
    """Minimal public acknowledgement — never contains a payable link."""
    return {
        "receipt_id": request.receipt_id,
        "state": request.state,
        "items_count": len(request.items),
        "created_at": request.created_at.isoformat() if request.created_at else None,
    }


def serialize_staff_request(request: CommerceRequest) -> dict:
    """Staff listing row with full snapshots for review (Task 2 input)."""
    return {
        "id": request.id,
        "receipt_id": request.receipt_id,
        "customer_name": request.customer_name,
        "mobile": request.mobile,
        "messenger": request.messenger,
        "messenger_handle": request.messenger_handle,
        "address": request.address,
        "note": request.note,
        "state": request.state,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "items": [serialize_request_item(i) for i in request.items],
    }


def list_staff_requests(
    db: Session,
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    state: str | None = None,
) -> list[CommerceRequest]:
    """Newest-first staff review queue (includes all states unless filtered).

    ``selectinload`` eager-loads the line items so serialization does not issue
    one extra query per request (previously 1 + N). Results are bounded by
    ``limit``/``offset`` and can be narrowed with ``state``.
    """
    query = (
        db.query(CommerceRequest)
        .options(selectinload(CommerceRequest.items))
        .order_by(CommerceRequest.created_at.desc(), CommerceRequest.id.desc())
    )
    if state:
        query = query.filter(CommerceRequest.state == state)
    return query.offset(offset).limit(limit).all()


def get_staff_request(db: Session, request_id: int) -> CommerceRequest:
    """Lookup for a staff action on a website request (404 when absent)."""
    request = (
        db.query(CommerceRequest).filter(CommerceRequest.id == request_id).first()
    )
    if request is None:
        raise CommerceNotFoundError("درخواست یافت نشد")
    return request


# ══════════════════════════════════════════════════════════════════════
# Task 2 — reviewed invoices + private expiring links
# ══════════════════════════════════════════════════════════════════════

# Invoice payload bounds (mirrored by the Pydantic layer in the router).
MAX_INVOICE_ITEMS = 100
MAX_INVOICE_ITEM_QTY = 999
MAX_INVOICE_DESCRIPTION = 255

# A private link stays valid for 7 days from approval.
INVOICE_LINK_TTL = timedelta(days=INVOICE_LINK_TTL_DAYS)

# Default public site origin for the shared pay link (overridable per deploy).
DEFAULT_PUBLIC_SITE_ORIGIN = "https://spaghettiprints.ir"
INVOICE_PAY_PATH = "/pay"
TOKEN_BYTES = 32

# Anything but a settled payment may be edited (which returns it to draft).
EDITABLE_INVOICE_STATES = ("draft", "approved", "revoked")


class CommerceNotFoundError(Exception):
    """Requested commerce entity does not exist (maps to HTTP 404)."""


class CommerceGoneError(Exception):
    """Token existed but is no longer usable (expired/revoked) (maps to HTTP 410)."""


class CommerceStateError(Exception):
    """The entity exists but is not in a state that allows this action (HTTP 409)."""


class CommerceConfigError(Exception):
    """The deployment origin is misconfigured (maps to HTTP 500)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes read back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── Private token handling ───────────────────────────────────────────

def hash_invoice_token(raw_token: str) -> str:
    """Deterministic SHA-256 hex digest of a raw bearer token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_invoice_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)`` — only the hash is persisted."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_invoice_token(raw)


# Plain HTTP is tolerated only for an explicit local development host. Real
# deployments must serve the private bearer link over HTTPS — enforced here
# unconditionally rather than behind an optional APP_ENV flag that a production
# deploy is likely to leave unset (which would silently accept a plaintext link).
LOCAL_DEV_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_local_dev_origin(parsed) -> bool:
    return (parsed.hostname or "").lower() in LOCAL_DEV_HOSTS


def public_site_origin() -> str:
    """Validated public origin used to build customer-facing share links.

    Defaults to the production site. HTTPS is required for every origin except
    an explicit local development host (``localhost`` / ``127.0.0.1`` /
    ``::1``), so a private bearer link is never emitted over plain HTTP on a
    real deployment regardless of whether ``APP_ENV`` happens to be set.
    """
    raw = (os.getenv("PUBLIC_SITE_ORIGIN") or DEFAULT_PUBLIC_SITE_ORIGIN).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CommerceConfigError("PUBLIC_SITE_ORIGIN must be a valid absolute URL")
    # Only a bare origin is accepted — no path, query string, fragment or
    # userinfo. Anything else (e.g. ``https://evil.example/path?leak=1``) could
    # route the private bearer link to an attacker-controlled location or leak
    # the token through a redirect/query string.
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise CommerceConfigError(
            "PUBLIC_SITE_ORIGIN must be a bare origin (no path, query, fragment or userinfo)"
        )
    if parsed.scheme != "https" and not _is_local_dev_origin(parsed):
        raise CommerceConfigError(
            "PUBLIC_SITE_ORIGIN must use HTTPS unless it is an explicit localhost dev host"
        )
    return raw


def build_share_url(raw_token: str) -> str:
    """Full private pay URL for a freshly issued token."""
    return f"{public_site_origin()}{INVOICE_PAY_PATH}/{raw_token}"


def is_link_expired(invoice: CommerceInvoice) -> bool:
    expires = _as_utc(invoice.token_expires_at)
    return expires is not None and expires <= _now()


# ── Money / item validation ──────────────────────────────────────────

def _require_int(value, *, field: str, minimum: int, maximum: int) -> int:
    """Strict integer-Toman bound check (no floats, no bools, no coercion)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommerceValidationError(f"{field} باید عدد صحیح باشد")
    if value < minimum or value > maximum:
        raise CommerceValidationError(f"{field} خارج از محدوده مجاز است")
    return value


def _normalize_invoice_items(db: Session, items: list[dict]) -> list[dict]:
    """Validate and normalize invoice lines; snapshots stay authoritative."""
    if not items:
        raise CommerceValidationError("فاکتور باید حداقل یک آیتم داشته باشد")
    if len(items) > MAX_INVOICE_ITEMS:
        raise CommerceValidationError("تعداد آیتمهای فاکتور بیش از حد مجاز است")

    normalized: list[dict] = []
    for raw in items:
        try:
            description = str(raw.get("description") or "").strip()
        except AttributeError:
            raise CommerceValidationError("آیتم فاکتور نامعتبر است")
        if not description:
            raise CommerceValidationError("شرح آیتم الزامی است")
        if len(description) > MAX_INVOICE_DESCRIPTION:
            raise CommerceValidationError("شرح آیتم بسیار طولانی است")

        raw_product_id = raw.get("product_id")
        if raw_product_id is None or raw_product_id == "":
            product_id = None
        else:
            product_id = _require_int(
                raw_product_id, field="شناسه محصول", minimum=1, maximum=2_147_483_647
            )

        qty = _require_int(raw.get("qty"), field="تعداد", minimum=1, maximum=MAX_INVOICE_ITEM_QTY)
        unit = _require_int(
            raw.get("unit_toman"), field="قیمت واحد", minimum=1, maximum=MAX_INVOICE_TOTAL_TOMAN
        )
        normalized.append(
            {
                "product_id": product_id,
                "description": description,
                "qty": qty,
                "unit_toman": unit,
                "line_total_toman": qty * unit,
            }
        )

    product_ids = {i["product_id"] for i in normalized if i["product_id"] is not None}
    if product_ids:
        found = {
            p.id
            for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
        }
        if product_ids - found:
            raise CommerceValidationError("برخی محصولات انتخابشده یافت نشدند")
    return normalized


def compute_invoice_totals(normalized_items: list[dict], shipping_toman: int) -> tuple[int, int, int]:
    """Return ``(items_subtotal, shipping, total)`` in integer Toman.

    The total ceiling is enforced here so every mutation path (create, edit and
    the Task 3 payment transition, which reuses this helper) shares one bound.
    """
    subtotal = sum(item["line_total_toman"] for item in normalized_items)
    total = subtotal + shipping_toman
    if total > MAX_INVOICE_TOTAL_TOMAN:
        raise CommerceValidationError("مبلغ کل فاکتور بیش از حد مجاز است")
    if total <= 0:
        raise CommerceValidationError("مبلغ کل فاکتور باید مثبت باشد")
    return subtotal, shipping_toman, total


def assert_payable_total(invoice: CommerceInvoice) -> None:
    """Defensive re-check before issuing/using a payable link (Task 3 reuse)."""
    if not isinstance(invoice.total_toman, int) or invoice.total_toman <= 0:
        raise CommerceStateError("مبلغ فاکتور نامعتبر است")
    if invoice.total_toman > MAX_INVOICE_TOTAL_TOMAN:
        raise CommerceStateError("مبلغ فاکتور بیش از حد مجاز است")


# ── Payment-attempt coordination (Task 3 hook) ───────────────────────

def _payment_attempt_model():
    """The Task 3 ``CommercePaymentAttempt`` model, if it has landed yet."""
    from app import models

    return getattr(models, "CommercePaymentAttempt", None)


def has_inflight_payment_attempt(db: Session, invoice: CommerceInvoice) -> bool:
    """True while an unsettled payment attempt exists for this invoice."""
    model = _payment_attempt_model()
    if model is None:
        return False
    return (
        db.query(model)
        .filter(
            model.invoice_id == invoice.id,
            model.state.in_(("initiating", "pending", "unknown")),
        )
        .count()
        > 0
    )


def _invalidate_pending_payment_attempts(db: Session, invoice: CommerceInvoice) -> int:
    """Fail any in-flight attempts so a revised invoice cannot be paid twice.

    A no-op until Task 3 defines ``CommercePaymentAttempt``; kept here so
    revision semantics are already correct when payments land.
    """
    model = _payment_attempt_model()
    if model is None:
        return 0
    rows = (
        db.query(model)
        .filter(
            model.invoice_id == invoice.id,
            model.state.in_(("initiating", "pending", "unknown")),
        )
        .all()
    )
    for row in rows:
        row.state = "failed"
    return len(rows)


# ── Staff mutations ──────────────────────────────────────────────────

def _get_invoice(db: Session, invoice_id: int) -> CommerceInvoice:
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).first()
    if invoice is None:
        raise CommerceNotFoundError("فاکتور یافت نشد")
    return invoice


def get_staff_invoice(db: Session, invoice_id: int) -> CommerceInvoice:
    """Public lookup for a staff action (raises ``CommerceNotFoundError``)."""
    return _get_invoice(db, invoice_id)


def _apply_items(invoice: CommerceInvoice, normalized_items: list[dict]) -> None:
    invoice.items.clear()
    for item in normalized_items:
        invoice.items.append(CommerceInvoiceItem(**item))


def create_staff_invoice(
    db: Session,
    *,
    customer_name: str,
    mobile: str,
    items: list[dict],
    request_id: int | None = None,
    messenger: str = "telegram",
    messenger_handle: str = "",
    address: str = "",
    specification: str = "",
    internal_note: str = "",
    shipping_toman: int = 0,
) -> CommerceInvoice:
    """Create a draft invoice — from a website request or a manual/chat order."""
    shipping = _require_int(
        shipping_toman, field="هزینه ارسال", minimum=0, maximum=MAX_INVOICE_TOTAL_TOMAN
    )
    normalized = _normalize_invoice_items(db, items)
    _, _, total = compute_invoice_totals(normalized, shipping)

    linked_request: CommerceRequest | None = None
    if request_id is not None:
        request_id = _require_int(request_id, field="شناسه درخواست", minimum=1, maximum=2_147_483_647)
        linked_request = (
            db.query(CommerceRequest).filter(CommerceRequest.id == request_id).first()
        )
        if linked_request is None:
            raise CommerceNotFoundError("درخواست یافت نشد")
        if linked_request.state != "pending_review":
            raise CommerceStateError("این درخواست قبلاً بررسی شده است")

    invoice = CommerceInvoice(
        request_id=linked_request.id if linked_request else None,
        customer_name=customer_name.strip(),
        mobile=mobile.strip(),
        messenger=messenger,
        messenger_handle=(messenger_handle or "").strip(),
        address=(address or "").strip(),
        specification=(specification or "").strip(),
        internal_note=(internal_note or "").strip(),
        shipping_toman=shipping,
        total_toman=total,
        state="draft",
        revision=1,
    )
    _apply_items(invoice, normalized)
    db.add(invoice)
    if linked_request is not None:
        linked_request.state = "converted"
    db.commit()
    db.refresh(invoice)
    return invoice


def update_staff_invoice(
    db: Session,
    invoice_id: int,
    *,
    customer_name: str,
    mobile: str,
    items: list[dict],
    messenger: str = "telegram",
    messenger_handle: str = "",
    address: str = "",
    specification: str = "",
    internal_note: str = "",
    shipping_toman: int = 0,
) -> CommerceInvoice:
    """Revise a non-settled invoice: bump revision, drop to draft, kill the link.

    The link is invalidated because the payable amount/specification changed;
    any in-flight payment attempt is failed for the same reason.
    """
    invoice = _get_invoice(db, invoice_id)
    if invoice.state == "paid":
        raise CommerceStateError("فاکتور پرداختشده قابل ویرایش نیست")
    if has_inflight_payment_attempt(db, invoice):
        raise CommerceStateError("پرداخت در حال انجام است؛ پس از تعیین نتیجه قابل ویرایش است")

    shipping = _require_int(
        shipping_toman, field="هزینه ارسال", minimum=0, maximum=MAX_INVOICE_TOTAL_TOMAN
    )
    normalized = _normalize_invoice_items(db, items)
    _, _, total = compute_invoice_totals(normalized, shipping)

    _invalidate_pending_payment_attempts(db, invoice)

    invoice.customer_name = customer_name.strip()
    invoice.mobile = mobile.strip()
    invoice.messenger = messenger
    invoice.messenger_handle = (messenger_handle or "").strip()
    invoice.address = (address or "").strip()
    invoice.specification = (specification or "").strip()
    invoice.internal_note = (internal_note or "").strip()
    invoice.shipping_toman = shipping
    invoice.total_toman = total
    invoice.revision = (invoice.revision or 1) + 1
    invoice.state = "draft"
    invoice.token_hash = None
    invoice.token_expires_at = None
    invoice.approved_at = None
    invoice.revoked_at = None
    _apply_items(invoice, normalized)

    db.commit()
    db.refresh(invoice)
    return invoice


def approve_invoice(
    db: Session, invoice_id: int, *, background_tasks=None
) -> tuple[CommerceInvoice, str]:
    """Freeze the invoice and issue a fresh private link.

    Returns ``(invoice, raw_token)`` — the raw token is returned exactly once
    and never persisted or logged. Re-approving (e.g. after expiry or a
    revoke) simply mints a new token and invalidates the previous one.
    """
    invoice = _get_invoice(db, invoice_id)
    if invoice.state == "paid":
        raise CommerceStateError("فاکتور پرداختشده قابل تأیید مجدد نیست")
    # Validate the deploy origin BEFORE any mutation/commit: a misconfigured
    # deployment must never leave an invoice frozen as 'approved' while its
    # share link is broken or attacker-controlled.
    public_site_origin()
    if has_inflight_payment_attempt(db, invoice):
        raise CommerceStateError(
            "پرداخت در حال انجام است؛ پس از تعیین نتیجه قابل تأیید مجدد است"
        )
    assert_payable_total(invoice)

    raw_token, token_hash = generate_invoice_token()
    invoice.token_hash = token_hash
    invoice.token_expires_at = _now() + INVOICE_LINK_TTL
    invoice.state = "approved"
    invoice.approved_at = _now()
    invoice.revoked_at = None

    db.commit()
    db.refresh(invoice)
    # After-commit: the private link/token is NOT broadcast — only the fact of
    # approval and a minimized summary. Deferred to a background task so the
    # staff response is not gated by the transport. Never raises.
    _emit_admin_notification(
        commerce_notifications.EVENT_INVOICE_APPROVED, invoice,
        background_tasks=background_tasks,
    )
    return invoice, raw_token


def revoke_invoice(db: Session, invoice_id: int) -> CommerceInvoice:
    """Invalidate the private link; idempotent for an already-revoked invoice."""
    invoice = _get_invoice(db, invoice_id)
    if invoice.state == "paid":
        raise CommerceStateError("فاکتور پرداختشده قابل لغو نیست")
    if has_inflight_payment_attempt(db, invoice):
        raise CommerceStateError("پرداخت در حال انجام است؛ پس از تعیین نتیجه قابل لغو است")

    _invalidate_pending_payment_attempts(db, invoice)
    invoice.state = "revoked"
    invoice.revoked_at = _now()
    invoice.token_hash = None
    invoice.token_expires_at = None

    db.commit()
    db.refresh(invoice)
    return invoice


def list_staff_invoices(
    db: Session,
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    state: str | None = None,
) -> list[CommerceInvoice]:
    """Newest-first invoice queue, optionally filtered by state."""
    if state is not None and state not in COMMERCE_INVOICE_STATES:
        raise CommerceValidationError("وضعیت فاکتور نامعتبر است")
    query = (
        db.query(CommerceInvoice)
        .options(selectinload(CommerceInvoice.items))
        .order_by(CommerceInvoice.created_at.desc(), CommerceInvoice.id.desc())
    )
    if state:
        query = query.filter(CommerceInvoice.state == state)
    return query.offset(offset).limit(limit).all()


# ── Public token read ────────────────────────────────────────────────

def resolve_public_invoice(db: Session, raw_token: str) -> CommerceInvoice:
    """Look up a live invoice by its raw bearer token.

    Unknown/revoked/never-approved tokens are 404; a token past its expiry is
    410 so the pay page can show a distinct "expired" state.
    """
    if not raw_token or len(raw_token) > 200:
        raise CommerceNotFoundError("لینک نامعتبر است")
    invoice = (
        db.query(CommerceInvoice)
        .options(selectinload(CommerceInvoice.items))
        .filter(CommerceInvoice.token_hash == hash_invoice_token(raw_token))
        .first()
    )
    if invoice is None or invoice.state not in ("approved", "paid"):
        raise CommerceNotFoundError("لینک فاکتور یافت نشد")
    if invoice.state == "approved" and is_link_expired(invoice):
        raise CommerceGoneError("لینک فاکتور منقضی شده است")
    return invoice


# ── Serialization ────────────────────────────────────────────────────

def serialize_invoice_item(item: CommerceInvoiceItem) -> dict:
    return {
        "product_id": item.product_id,
        "description": item.description,
        "qty": item.qty,
        "unit_toman": item.unit_toman,
        "line_total_toman": item.line_total_toman,
    }


def serialize_staff_invoice(invoice: CommerceInvoice) -> dict:
    """Staff view — full detail, but never the raw or hashed token."""
    return {
        "id": invoice.id,
        "request_id": invoice.request_id,
        "customer_name": invoice.customer_name,
        "mobile": invoice.mobile,
        "messenger": invoice.messenger,
        "messenger_handle": invoice.messenger_handle,
        "address": invoice.address,
        "specification": invoice.specification,
        "internal_note": invoice.internal_note,
        "shipping_toman": invoice.shipping_toman,
        "total_toman": invoice.total_toman,
        "state": invoice.state,
        "revision": invoice.revision,
        "order_id": invoice.order_id,
        "has_active_link": invoice.state == "approved" and not is_link_expired(invoice),
        "token_expires_at": (
            invoice.token_expires_at.isoformat() if invoice.token_expires_at else None
        ),
        "approved_at": invoice.approved_at.isoformat() if invoice.approved_at else None,
        "revoked_at": invoice.revoked_at.isoformat() if invoice.revoked_at else None,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
        "items": [serialize_invoice_item(i) for i in invoice.items],
    }


def serialize_public_invoice(invoice: CommerceInvoice) -> dict:
    """Minimal pay-page payload.

    Deliberately excludes every contact/PII field (name, mobile, messenger,
    address) and staff-only notes. The token itself is never echoed back.
    """
    return {
        "id": invoice.id,
        "state": invoice.state,
        "revision": invoice.revision,
        "shipping_toman": invoice.shipping_toman,
        "total_toman": invoice.total_toman,
        "specification": invoice.specification,
        "items": [
            {
                "description": i.description,
                "qty": i.qty,
                "unit_toman": i.unit_toman,
                "line_total_toman": i.line_total_toman,
            }
            for i in invoice.items
        ],
        "expires_at": (
            invoice.token_expires_at.isoformat() if invoice.token_expires_at else None
        ),
        "approved_at": invoice.approved_at.isoformat() if invoice.approved_at else None,
    }


# ══════════════════════════════════════════════════════════════════════
# Task 3 — durable payment attempts + DigiPay UPG settlement
# ══════════════════════════════════════════════════════════════════════

TOMAN_TO_RIAL = 10
PAYMENT_PROVIDER_DIGIPAY = "digipay"
# Task 2 — the BitPay gateway is a second provider on the same attempt table;
# shared settlement code must read ``attempt.provider`` rather than assume
# DigiPay. Kept local to mirror the existing constant's placement.
PAYMENT_PROVIDER_BITPAY = "bitpay"
# UPG ticket type requested at initiation (docs: 11 = all UPG features).
DIGIPAY_TICKET_TYPE = 11
# Payment methods reported by the DigiPay callback ``type`` and echoed to
# ``/purchases/verify?type=`` (docs table): IPG=0, Wallet=11, Credit=5,
# BNPL=13, CreditCard=24. v1 enables only IPG/Wallet — credit/BNPL additionally
# need a ``basketDetailsDto`` (+ ``/purchases/deliver`` after fulfillment), so
# they are *rejected safely* and never verified here.
PAYMENT_METHOD_IPG = 0
PAYMENT_METHOD_WALLET = 11
PAYMENT_METHOD_CREDIT = 5
PAYMENT_METHOD_BNPL = 13
PAYMENT_METHOD_CREDIT_CARD = 24
ALLOWED_PAYMENT_METHODS = (PAYMENT_METHOD_IPG, PAYMENT_METHOD_WALLET)
REJECTED_PAYMENT_METHODS = (
    PAYMENT_METHOD_CREDIT,
    PAYMENT_METHOD_BNPL,
    PAYMENT_METHOD_CREDIT_CARD,
)
# Documented verify ``result.status`` values.
DIGIPAY_STATUS_SUCCESS = 0
DIGIPAY_STATUS_PENDING = 9011  # accepted but not settled yet — keep unknown
ACTIVE_ATTEMPT_STATES = ("initiating", "pending", "unknown")
PROVIDER_ID_PREFIX = "INV"
# Public, non-secret confirmation page. The raw bearer token is never persisted,
# so a gateway callback cannot rebuild the `/pay/{token}` URL — and must not,
# since that would leak the token into the redirect/logs.
PAYMENT_RESULT_PATH = "/pay/result"


class CommercePaymentError(Exception):
    """Provider/network failure while initiating or verifying (HTTP 502)."""


class CommerceGatewayUnavailableError(Exception):
    """Payment provider is not configured on this deployment (HTTP 503)."""


class CommerceReconciliationRequiredError(CommerceStateError):
    """A genuine server-verified payment could not be settled (needs staff).

    Raised by ``settle_verified_payment`` when the provider really confirmed a
    payment but it cannot be applied to the current invoice — the attempt's
    ``invoice_revision``/``amount_rial`` no longer match, or the invoice was
    revoked/revised while the gateway session was live. The attempt keeps its
    verified evidence and is queued for staff reconciliation/refund; callers
    must never treat this as a settlement failure that unlocks the attempt,
    marks the invoice paid, or 500s the gateway callback.
    """


def _short(value, limit: int = 300) -> str:
    return str(value)[:limit]


def toman_to_rial(total_toman: int) -> int:
    """Exact integer Toman → Rial conversion, applied once at the boundary."""
    if isinstance(total_toman, bool) or not isinstance(total_toman, int) or total_toman <= 0:
        raise CommerceStateError("مبلغ فاکتور نامعتبر است")
    return total_toman * TOMAN_TO_RIAL


def generate_payment_provider_id(invoice: CommerceInvoice) -> str:
    """Unique, non-secret merchant reference echoed back by the gateway."""
    return f"{PROVIDER_ID_PREFIX}{invoice.id}-R{invoice.revision}-{secrets.token_hex(8)}"


def find_active_payment_attempt(db: Session, invoice: CommerceInvoice) -> CommercePaymentAttempt | None:
    return (
        db.query(CommercePaymentAttempt)
        .filter(
            CommercePaymentAttempt.invoice_id == invoice.id,
            CommercePaymentAttempt.state.in_(ACTIVE_ATTEMPT_STATES),
        )
        .order_by(CommercePaymentAttempt.id.desc())
        .first()
    )


def find_payment_attempt_by_provider_id(db: Session, provider_id: str | None) -> CommercePaymentAttempt | None:
    if not provider_id:
        return None
    return (
        db.query(CommercePaymentAttempt)
        # DigiPay-only: its alnum merchant reference is the callback identity.
        # A BitPay attempt now stores a short *numeric* ``provider_id`` (the
        # factorId), so without this filter a forged DigiPay callback carrying
        # that number could resolve a BitPay row.
        .filter(
            CommercePaymentAttempt.provider == PAYMENT_PROVIDER_DIGIPAY,
            CommercePaymentAttempt.provider_id == provider_id,
        )
        .first()
    )


def assert_payment_allowed(invoice: CommerceInvoice) -> None:
    """Only an approved, unexpired, unpaid invoice may start a payment."""
    if invoice.state == "paid" or invoice.order_id is not None:
        raise CommerceStateError("این فاکتور قبلاً پرداخت شده است")
    if invoice.state != "approved":
        raise CommerceStateError("این فاکتور برای پرداخت آماده نیست")
    if is_link_expired(invoice):
        raise CommerceGoneError("لینک فاکتور منقضی شده است")
    assert_payable_total(invoice)


def start_payment(
    db: Session,
    invoice: CommerceInvoice,
    client,
    *,
    callback_url: str,
) -> CommercePaymentAttempt:
    """Create (or resume) the durable attempt and request a UPG ticket.

    Idempotent while an attempt is in flight: a repeated click returns the
    existing ticket's redirect instead of minting a second session. The
    attempt row is committed *before* the network call so a crash or timeout
    still leaves a reconcilable ``unknown``/``initiating`` row.
    """
    assert_payment_allowed(invoice)
    amount_rial = toman_to_rial(invoice.total_toman)

    attempt = find_active_payment_attempt(db, invoice)
    if attempt is not None and attempt.provider != PAYMENT_PROVIDER_DIGIPAY:
        # Another provider (BitPay) already holds this invoice's shared lock;
        # a cross-provider click is a conflict, never a resume that reflects the
        # other gateway's portal through the DigiPay endpoint.
        raise CommerceStateError("پرداخت از درگاه دیگری برای این فاکتور در حال انجام است")
    if attempt is not None and attempt.redirect_url:
        return attempt

    if attempt is None:
        attempt = CommercePaymentAttempt(
            invoice_id=invoice.id,
            provider=PAYMENT_PROVIDER_DIGIPAY,
            state="initiating",
            provider_id=generate_payment_provider_id(invoice),
            amount_rial=amount_rial,
            invoice_revision=invoice.revision,
            type=DIGIPAY_TICKET_TYPE,
        )
        db.add(attempt)
    else:
        attempt.amount_rial = amount_rial
        attempt.invoice_revision = invoice.revision
        attempt.type = DIGIPAY_TICKET_TYPE
        attempt.state = "initiating"

    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent initiation (partial unique index).
        db.rollback()
        existing = find_active_payment_attempt(db, invoice)
        if (
            existing is not None
            and existing.provider == PAYMENT_PROVIDER_DIGIPAY
            and existing.redirect_url
        ):
            return existing
        raise CommerceStateError("پرداخت دیگری برای این فاکتور در حال انجام است")

    db.refresh(attempt)
    try:
        ticket = client.create_ticket(
            amount_rial=amount_rial,
            mobile=invoice.mobile,
            provider_id=attempt.provider_id,
            callback_url=callback_url,
        )
    except Exception as exc:  # noqa: BLE001 - gateway boundary → recoverable
        attempt.state = "unknown"
        attempt.last_error = _short(exc)
        db.commit()
        raise CommercePaymentError("ارتباط با درگاه پرداخت ناموفق بود") from exc

    attempt.redirect_url = ticket["redirect_url"]
    attempt.state = "pending"
    attempt.last_error = None
    db.commit()
    db.refresh(attempt)
    return attempt


def _provider_label(provider: str | None) -> str:
    """Human (Persian) provider name for the order note, defaulting to DigiPay.

    The legacy order note used to hardcode "دیجیپی"; keeping the DigiPay label as
    the default preserves every existing note byte-for-byte while letting a
    BitPay-settled invoice record its own provider identity.
    """
    if provider == PAYMENT_PROVIDER_BITPAY:
        return "بیت‌پی"
    return "دیجی‌پی"


def _create_legacy_order(
    db: Session, invoice: CommerceInvoice, *, provider: str | None = PAYMENT_PROVIDER_DIGIPAY
) -> Order:
    """One legacy Order (+items) mirroring the paid invoice, paid in full.

    A synthetic shipping line keeps ``sum(items) == paid_amount == total_toman``
    so the existing order board's accounting stays consistent. Status stays
    ``new``: fulfillment remains a staff decision, never auto-set to printing.
    ``provider`` selects the gateway named in the order note so a BitPay payment
    is never mislabelled as DigiPay.
    """
    items = list(invoice.items)
    qty = sum(i.qty for i in items) or 1
    order = Order(
        customer_name=invoice.customer_name,
        contact=invoice.mobile,
        product_label=(items[0].description if items else "سفارش آنلاین"),
        qty=qty,
        quoted_price=float(invoice.total_toman) / qty,
        paid_amount=float(invoice.total_toman),
        status="new",
        notes=f"پرداخت آنلاین فاکتور #{invoice.id} از طریق {_provider_label(provider)}",
        is_active=True,
    )
    db.add(order)
    db.flush()
    for item in items:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                product_label=item.description,
                qty=item.qty,
                unit_price=float(item.unit_toman),
            )
        )
    if invoice.shipping_toman:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=None,
                product_label="هزینه ارسال",
                qty=1,
                unit_price=float(invoice.shipping_toman),
            )
        )
    db.flush()
    return order


def _expected_amount_rial(invoice: CommerceInvoice) -> int | None:
    """The invoice's current payable amount in Rial, or None if unpayable."""
    try:
        return toman_to_rial(invoice.total_toman)
    except CommerceStateError:
        return None


def _attempt_binds_invoice(attempt: CommercePaymentAttempt, invoice: CommerceInvoice) -> bool:
    """True only when the attempt was issued for the invoice's *current* state.

    An attempt is bound to the invoice only if it was created against the same
    ``revision`` AND for the invoice's current total. This is the guard that
    stops a late callback for an abandoned old attempt from settling a
    re-approved, re-priced invoice.
    """
    expected = _expected_amount_rial(invoice)
    if expected is None:
        return False
    return (
        attempt.invoice_revision == invoice.revision
        and attempt.amount_rial == expected
    )


def _mark_verified_needs_reconciliation(
    db: Session,
    attempt: CommercePaymentAttempt,
    tracking_code: str | None,
    reason: str,
) -> None:
    """Preserve a genuine verified payment for staff, without settling it.

    The attempt keeps terminal ``verified`` state (so the partial-unique index
    releases and re-payment is not blocked) plus its tracking/verified evidence,
    and is flagged ``reconciliation_required`` so it stays visible in the staff
    payment queue even though it is no longer active.
    """
    attempt.state = "verified"
    attempt.tracking_code = attempt.tracking_code or (tracking_code or None)
    attempt.verified_at = attempt.verified_at or _now()
    attempt.reconciliation_required = True
    attempt.last_error = _short(reason)
    db.commit()
    db.refresh(attempt)


def settle_verified_payment(
    db: Session, attempt: CommercePaymentAttempt, *, tracking_code: str,
    background_tasks=None, on_success=None,
) -> CommercePaymentAttempt:
    """Atomically mark the attempt verified, the invoice paid and link ONE order.

    Safe under replay/concurrency: the ``approved → paid`` transition is claimed
    with a single conditional UPDATE, so only the first writer creates the
    legacy order. Later callers see ``state == 'paid'`` and no-op.

    Before settling, the attempt is bound to the invoice's *current* revision
    and amount. A genuine but stale/foreign success (an abandoned attempt from
    an earlier revision, or a session against an invoice that was since
    revoked/revised) never settles: it is flagged for staff reconciliation and
    ``CommerceReconciliationRequiredError`` is raised.

    ``on_success`` is an optional ``callback(db, invoice, attempt)`` invoked
    immediately before the single successful commit, so any rows it adds (e.g.
    an audit entry) are committed *atomically with the settlement* — and are
    never written on the reconciliation / already-paid no-op branches, where no
    settlement actually happened. A caller that passes it must add only, never
    commit or roll back.
    """
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
    if invoice is None:
        raise CommerceNotFoundError("فاکتور یافت نشد")

    # Bind BEFORE any settlement: never apply a payment to a differently-priced
    # or differently-revised invoice. Preserve the verified evidence and hand it
    # to staff reconciliation instead of marking the invoice paid.
    if not _attempt_binds_invoice(attempt, invoice):
        _mark_verified_needs_reconciliation(
            db, attempt, tracking_code,
            "settle blocked: attempt does not match the current invoice "
            f"(attempt revision={attempt.invoice_revision} amount_rial={attempt.amount_rial}, "
            f"invoice revision={invoice.revision} total_rial={_expected_amount_rial(invoice)})",
        )
        raise CommerceReconciliationRequiredError(
            "پرداخت تأییدشده با نسخه فعلی فاکتور مطابقت ندارد؛ نیازمند بررسی دستی"
        )

    if invoice.state == "paid":
        # Already settled (replay, or a second attempt racing the first).
        attempt.state = "verified"
        attempt.tracking_code = attempt.tracking_code or tracking_code
        attempt.verified_at = attempt.verified_at or _now()
        db.commit()
        return attempt

    claimed = (
        db.query(CommerceInvoice)
        .filter(CommerceInvoice.id == invoice.id, CommerceInvoice.state == "approved")
        .update(
            {CommerceInvoice.state: "paid", CommerceInvoice.updated_at: _now()},
            synchronize_session=False,
        )
    )
    if claimed == 0:
        db.rollback()
        invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
        if invoice is None:
            raise CommerceNotFoundError("فاکتور یافت نشد")
        if invoice.state == "paid":
            attempt.state = "verified"
            attempt.tracking_code = attempt.tracking_code or tracking_code
            attempt.verified_at = attempt.verified_at or _now()
            db.commit()
            return attempt
        # Provider-confirmed success, but the invoice is no longer payable
        # (revoked, or revised back to draft). Never mark it paid and never let
        # the callback 500: keep the verified evidence, surface it to staff.
        _mark_verified_needs_reconciliation(
            db, attempt, tracking_code,
            f"provider verified but invoice not payable (state={invoice.state}); "
            "manual refund/reconciliation required",
        )
        raise CommerceReconciliationRequiredError(
            "پرداخت تأییدشده روی فاکتور غیرقابل‌پرداخت؛ نیازمند بررسی دستی"
        )

    db.expire_all()
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
    if invoice.order_id is None:
        order = _create_legacy_order(db, invoice, provider=attempt.provider)
        invoice.order_id = order.id

    attempt.state = "verified"
    attempt.tracking_code = tracking_code
    attempt.verified_at = _now()
    attempt.last_error = None
    # Commit any caller-supplied rows (e.g. an audit entry) atomically with the
    # settlement: they exist only when this branch — the one real settlement —
    # is taken.
    if on_success is not None:
        on_success(db, invoice, attempt)
    db.commit()
    db.refresh(attempt)
    # After-commit: this is the single claimed `approved -> paid` transition, so
    # the paid alert fires exactly once even if the callback is replayed (later
    # callbacks return via the `state == 'paid'` branch above and never reach
    # here). Deferred to a background task so the customer redirect is not gated
    # by the transport. Never raises.
    _emit_admin_notification(
        commerce_notifications.EVENT_PAYMENT_VERIFIED, invoice,
        background_tasks=background_tasks,
    )
    return attempt


def _int_or_none(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _callback_result_is_failure(result_value) -> bool:
    """DigiPay may post ``result`` as a JSON document or a bare status token."""
    if result_value is None:
        return False
    text = str(result_value).strip()
    if not text:
        return False
    if text[:1] in ("{", "["):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            status = _int_or_none(parsed.get("status"))
            if status is not None:
                return status != 0
            return str(parsed.get("result", "")).strip().upper() in (
                "FAILURE", "FAILED", "ERROR",
            )
    return text.upper() in ("FAILURE", "FAILED", "ERROR", "NOK")


def _verify_confirms(
    verified: dict,
    attempt: CommercePaymentAttempt,
    *,
    tracking_code: str | None = None,
) -> bool:
    """Strict server-side confirmation against the documented verify payload.

    Documented shape (docs "UPG" → verify)::

        {"result": {"status": 0, ...}, "trackingCode": ..., "providerId": ...,
         "amount": ..., "paymentGateway": ...}

    The success flag is ``result.status``; the identity/amount fields are
    **top-level**. Reading ``status``/``amount`` off the top level (or the
    identity fields out of ``result``) is the earlier bug that made every real
    verification fail.

    When ``tracking_code`` is supplied, the reply must echo it too: a
    confirmation counts only when it matches the issued amount, the unique
    ``providerId`` **and** the tracking code we actually verified.
    """
    if not isinstance(verified, dict):
        return False
    result = verified.get("result")
    if not isinstance(result, dict):
        return False
    if _int_or_none(result.get("status")) != DIGIPAY_STATUS_SUCCESS:
        return False
    if _int_or_none(verified.get("amount")) != attempt.amount_rial:
        return False
    provider_id = verified.get("providerId") or verified.get("provider_id")
    if provider_id != attempt.provider_id:
        return False
    if tracking_code is not None:
        echoed = verified.get("trackingCode")
        if echoed is None:
            echoed = verified.get("tracking_code")
        if str(echoed or "").strip() != str(tracking_code).strip():
            return False
    return True


def _verify_reports_authoritative_non_success(
    verified,
    attempt: CommercePaymentAttempt,
    *,
    tracking_code: str,
) -> bool:
    """True only for a terminal non-success tied to the ticket WE issued.

    A provider non-success whose only link to our attempt is a
    **callback-supplied** ``trackingCode`` is *not* authoritative. ``providerId``
    and ``amount`` are both visible in the gateway redirect, so a reply that
    merely echoes those two proves nothing about the invoice we issued: the
    gateway may recognise our ``providerId`` (and so echo the amount it holds)
    yet be answering about a tracking code we *supplied* — which may be a
    forgery. Such a "not found"/error therefore says nothing about whether OUR
    payment failed, and must not release the invoice lock.

    The reply is authoritative only when it explicitly reports a terminal
    non-success **and** is tied to the exact transaction we asked about: it must
    echo our unique ``providerId``, the issued ``amount_rial`` **and** the
    ``tracking_code`` we verified with. A missing or mismatched tracking echo is
    an ambiguous/absent tie and keeps the attempt open, so only a proven
    transaction-terminal response — or an explicit, audited staff ``abandon`` —
    may release the lock.
    """
    if not isinstance(verified, dict):
        return False
    result = verified.get("result")
    if not isinstance(result, dict):
        return False
    status = _int_or_none(result.get("status"))
    if status is None:
        return False
    if status in (DIGIPAY_STATUS_SUCCESS, DIGIPAY_STATUS_PENDING):
        return False
    provider_id = verified.get("providerId") or verified.get("provider_id")
    if provider_id != attempt.provider_id:
        return False
    if _int_or_none(verified.get("amount")) != attempt.amount_rial:
        return False
    # The decisive tie: the gateway must echo the very tracking code we verified
    # with. A callback-supplied code it does not echo (missing) or echoes
    # differently (ambiguous) cannot conclude a failure for our ticket.
    echoed = verified.get("trackingCode")
    if echoed is None:
        echoed = verified.get("tracking_code")
    if str(echoed or "").strip() != str(tracking_code).strip():
        return False
    return True


def handle_digipay_callback(
    db: Session,
    client,
    *,
    provider_id: str | None,
    amount,
    tracking_code: str | None,
    type_value,
    result_value,
    background_tasks=None,
) -> str:
    """Process an untrusted provider callback.

    Returns ``success`` | ``failed`` | ``pending``. The callback is treated as a
    hint only: the invoice is settled solely when a server-to-server verify
    confirms ``result.status == 0`` with a matching top-level providerId/amount.
    The callback ``type`` is the method actually used (IPG=0 / Wallet=11) and is
    the value echoed to ``/purchases/verify``; a credit/BNPL callback is refused
    before any verify call.
    """
    attempt = find_payment_attempt_by_provider_id(db, provider_id)
    if attempt is None:
        return "failed"
    if attempt.state == "verified":
        # A genuine verify whose attempt could NOT be settled is flagged for
        # staff reconciliation (wrong/stale customer invoice, revoked link). A
        # replay must NOT report success: the invoice is still unsettled and no
        # order exists, so a "success" here would contradict the first (pending)
        # response and mislead the customer. Keep it pending until staff settle
        # it via reconciliation.
        if attempt.reconciliation_required:
            return "pending"
        return "success"  # idempotent replay of a settled payment

    def _hold(reason) -> None:
        # Never claim a definite failure on an untrusted callback signal: keep
        # the attempt open — still locking the invoice and still visible to
        # staff — for reconciliation instead. ``failed`` would release the
        # active-attempt lock and could let a genuine payment be taken twice.
        if attempt.state in ACTIVE_ATTEMPT_STATES:
            attempt.state = "unknown"
            attempt.last_error = _short(reason)
            db.commit()

    # The callback is an untrusted hint (no signature, no invoice token). Its
    # identity (method/tracking) is PROVISIONAL: it is never authoritative, and
    # is used only as a staff-visible diagnostic and as a verify *candidate*.
    #
    # ``providerId`` is visible in the redirect, so anyone can POST a forged,
    # self-consistent callback (matching amount, supported type, any tracking)
    # before the customer's genuine one. Therefore:
    #
    #   * validate fully BEFORE persisting anything;
    #   * persist only the FIRST validated hint (diagnostics), and never treat
    #     it as authoritative;
    #   * verify with THIS callback's own candidate, so a genuine callback can
    #     still settle after an earlier forged one;
    #   * never terminally fail/unlock here — a non-confirming verify that rests
    #     only on callback-supplied data must not release the invoice lock.
    cb_amount = _int_or_none(amount)
    cb_type = _int_or_none(type_value)  # method actually used, NOT ticket type (11)
    tracking = (tracking_code or "").strip()

    if cb_amount != attempt.amount_rial:
        _hold("callback amount mismatch (unverified)")
        return "failed"

    if cb_type is None:
        _hold("callback missing/invalid type")
        return "failed"
    if cb_type not in ALLOWED_PAYMENT_METHODS:
        # Credit/BNPL/Card are disabled in v1: never verify them automatically,
        # and never persist the untrusted method; hold the attempt open (lock
        # held) so this callback cannot hide or re-route a real payment.
        _hold(f"unsupported payment method (type={cb_type}); needs manual review")
        return "failed"

    if not tracking:
        _hold("callback missing trackingCode")
        return "failed"

    if attempt.payment_method is None and not attempt.tracking_code:
        # First validated callback wins as the staff-visible diagnostic hint. It
        # is NOT authoritative: only a server-to-server verify that confirms
        # amount+providerId+tracking settles the attempt.
        attempt.payment_method = cb_type
        attempt.tracking_code = tracking
        db.commit()

    if _callback_result_is_failure(result_value):
        # Unverified hint of failure — keep the attempt open for reconciliation.
        _hold("callback reported failure (unverified)")
        return "failed"

    # Verify using THIS callback's validated candidate. Never gate the verify on
    # a previously stored hint: a genuine callback must be able to settle after a
    # forged one pinned a bogus identity first.
    try:
        verified = client.verify(
            tracking_code=tracking,
            provider_id=attempt.provider_id,
            type=cb_type,
        )
    except Exception as exc:  # noqa: BLE001 - transient → recoverable unknown
        _hold(exc)
        return "pending"

    result = verified.get("result") if isinstance(verified, dict) else None
    status = _int_or_none(result.get("status")) if isinstance(result, dict) else None
    if status == DIGIPAY_STATUS_PENDING:
        _hold("provider verify still pending (9011)")
        return "pending"
    if _verify_confirms(verified, attempt, tracking_code=tracking):
        # Confirmed authoritative success: pin the confirmed identity and settle.
        attempt.payment_method = cb_type
        try:
            settle_verified_payment(
                db, attempt, tracking_code=tracking, background_tasks=background_tasks
            )
        except CommerceReconciliationRequiredError:
            # The provider genuinely confirmed payment, but it can no longer be
            # settled against the current invoice (its revision/amount changed,
            # or the invoice was revoked/revised). The attempt kept its verified
            # evidence and is queued for staff; never 500 and never claim paid.
            return "pending"
        return "success"
    # Any non-confirming outcome — including a provider non-success for a merely
    # callback-supplied tracking code, which may be forged — must never terminally
    # fail or unlock the attempt. Keep it open (lock held) for staff reconcile.
    _hold(f"provider verify did not confirm (status={status})")
    return "failed"


# ══════════════════════════════════════════════════════════════════════
# Reconciliation — staff resolution of stuck/in-flight attempts
# ══════════════════════════════════════════════════════════════════════
#
# A payment that is left in ``initiating``/``pending``/``unknown`` can outlive
# its natural lifetime (customer never finished, callback lost, verify timeout).
# The rules below intentionally never *auto-fail* such an attempt on age alone:
# a definite failure requires either a provider-confirmed non-success or an
# explicit staff ``abandon``. Until then the attempt stays open and visible in
# the staff queue, so an invoice is never permanently locked without a human
# able to release it.

def serialize_staff_payment_attempt(attempt: CommercePaymentAttempt) -> dict:
    """Staff view of one attempt. Exposes no credential, token or redirect URL."""
    return {
        "id": attempt.id,
        "invoice_id": attempt.invoice_id,
        "provider": attempt.provider,
        "state": attempt.state,
        "provider_id": attempt.provider_id,
        "amount_rial": attempt.amount_rial,
        "type": attempt.type,
        "payment_method": attempt.payment_method,
        "tracking_code": attempt.tracking_code,
        # BitPay's ``id_get`` lives in ``tracking_code``; the callback-supplied
        # ``trans_id`` is exposed here so staff can see what a reconcile queries.
        "provider_trans_id": attempt.provider_trans_id,
        "has_redirect": bool(attempt.redirect_url),
        "last_error": attempt.last_error,
        # A genuine provider-verified payment that could not be settled against
        # its invoice is preserved with this flag set and shown in the queue.
        "reconciliation_required": bool(attempt.reconciliation_required),
        "verified_at": attempt.verified_at.isoformat() if attempt.verified_at else None,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
        "updated_at": attempt.updated_at.isoformat() if attempt.updated_at else None,
    }


def list_stuck_payment_attempts(
    db: Session,
    *,
    state: str | None = None,
    min_age_seconds: int | None = None,
    needs_reconciliation: bool | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[CommercePaymentAttempt]:
    """Bounded list of attempts needing staff attention.

    The default queue contains everything still requiring a human decision:
    in-flight attempts (``ACTIVE_ATTEMPT_STATES``) **and** provider-verified
    payments that could not be settled (``reconciliation_required``). The
    latter would otherwise disappear once their state became terminal. There is
    deliberately **no** time-based auto-fail: aging an attempt only moves it up
    this queue, it never changes its state.
    """
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    offset = max(0, int(offset))
    query = db.query(CommercePaymentAttempt)
    if state:
        if state not in ACTIVE_ATTEMPT_STATES:
            raise CommerceValidationError("وضعیت تراکنش نامعتبر است")
        query = query.filter(CommercePaymentAttempt.state == state)
    elif needs_reconciliation:
        query = query.filter(CommercePaymentAttempt.reconciliation_required.is_(True))
    else:
        query = query.filter(
            or_(
                CommercePaymentAttempt.state.in_(ACTIVE_ATTEMPT_STATES),
                CommercePaymentAttempt.reconciliation_required.is_(True),
            )
        )
    if min_age_seconds is not None:
        cutoff = _now() - timedelta(seconds=max(0, int(min_age_seconds)))
        query = query.filter(CommercePaymentAttempt.updated_at < cutoff)
    return (
        query.order_by(CommercePaymentAttempt.updated_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def reconcile_payment_attempt(
    db: Session,
    attempt: CommercePaymentAttempt | None,
    client,
    *,
    abandon: bool = False,
    reason: str | None = None,
    background_tasks=None,
) -> CommercePaymentAttempt:
    """Staff-driven resolution of a stuck attempt; returns the reloaded row.

    Safety rules:

    * A terminal attempt is never touched (idempotent).
    * ``abandon`` is the only way to close an attempt without a provider query —
      an explicit, audited staff decision that **requires a reason**, so a
      stuck/unknown attempt is never silently released (which could double-pay).
    * Otherwise the provider is queried **only when the method is known** (a
      callback confirmed IPG/Wallet) and a tracking code exists. The method is
      never guessed from the ticket type: verifying an IPG payment with
      ``type=11`` would wrongly report failure.
    * A pending/unknown provider status keeps the attempt open; only a
      provider-confirmed non-success **tied to the exact transaction we asked
      about** (the reply echoes our unique ``providerId``, the issued amount
      **and** the tracking code we verified with) closes it as ``failed``. A
      non-success that rests only on a callback-supplied tracking code — echoed
      ``providerId``/``amount`` alone, with the tracking missing or mismatched —
      cannot: that code may be forged, so the reply says nothing about our
      ticket. The lock is released only on such a proven terminal response or an
      explicit, audited staff ``abandon``.
    """
    if attempt is None:
        raise CommerceNotFoundError("تراکنش یافت نشد")
    if attempt.state not in ACTIVE_ATTEMPT_STATES:
        return attempt

    if abandon:
        reason = (reason or "").strip()
        if not reason:
            # A silent abandon could release the lock on an attempt that was in
            # fact paid (→ a second payment). Require an explicit, audited reason.
            raise CommerceValidationError("برای رهاسازی تراکنش، ثبت دلیل الزامی است")
        attempt.state = "failed"
        attempt.last_error = _short(reason)
        db.commit()
        db.refresh(attempt)
        return attempt

    if attempt.provider == PAYMENT_PROVIDER_BITPAY:
        return _reconcile_bitpay_attempt(
            db, attempt, client, background_tasks=background_tasks
        )

    method = attempt.payment_method
    tracking = (attempt.tracking_code or "").strip()
    if method not in ALLOWED_PAYMENT_METHODS or not tracking:
        # No provider-verifiable identity yet (e.g. the customer never reached
        # the gateway). Keep it open for an explicit staff decision.
        return attempt

    if client is None:
        raise CommerceGatewayUnavailableError("درگاه پرداخت پیکربندی نشده است")

    try:
        verified = client.verify(
            tracking_code=tracking,
            provider_id=attempt.provider_id,
            type=method,
        )
    except Exception as exc:  # noqa: BLE001 - transient; keep unknown
        attempt.last_error = _short(exc)
        db.commit()
        db.refresh(attempt)
        return attempt

    result = verified.get("result") if isinstance(verified, dict) else None
    status = _int_or_none(result.get("status")) if isinstance(result, dict) else None
    if status == DIGIPAY_STATUS_PENDING:
        attempt.last_error = _short("provider verify still pending (9011)")
        db.commit()
        db.refresh(attempt)
        return attempt
    if _verify_confirms(verified, attempt, tracking_code=tracking):
        try:
            settle_verified_payment(
                db, attempt, tracking_code=tracking, background_tasks=background_tasks
            )
        except CommerceReconciliationRequiredError:
            # Already flagged for staff (verified evidence preserved); the queue
            # surfaces it, so just return the refreshed attempt.
            db.refresh(attempt)
        return attempt

    if _verify_reports_authoritative_non_success(verified, attempt, tracking_code=tracking):
        # The provider explicitly reported a terminal non-success tied to the
        # exact transaction we asked about (it echoed our unique ``providerId``,
        # the issued amount AND the tracking code we verified with): only now may
        # staff reconciliation close the attempt and release the lock. An echo
        # of providerId/amount alone is NOT enough — both are visible in the
        # redirect, and the tracking may be a forged callback hint.
        attempt.state = "failed"
        attempt.last_error = _short(f"reconcile: provider status={status}")
        db.commit()
        db.refresh(attempt)
        return attempt

    # A non-success whose only link to the attempt is a callback-supplied
    # tracking code (no providerId/amount linkage), an unrecognized/malformed
    # reply, or a provider-success whose identity/amount does not match: none can
    # conclude a failure. Keep the attempt open so its lock is never silently
    # released — a forged callback must not be able to unlock a payment.
    attempt.last_error = _short(f"reconcile: provider did not confirm (status={status})")
    db.commit()
    db.refresh(attempt)
    return attempt


# ══════════════════════════════════════════════════════════════════════
# Task 2 — BitPay gateway v2.2 attempts + GET callback
# ══════════════════════════════════════════════════════════════════════
#
# BitPay's documented flow (gateway-help v2.2) differs from DigiPay in two ways
# this section encodes:
#
#   * The GET callback carries only ``trans_id`` and ``id_get`` (documented
#     sample ``.../payment/gateway-1200-get`` → ``?trans_id=123&id_get=321``),
#     NOT the ``factorId`` we sent. So the durable link from an untrusted
#     callback back to its attempt is the ``id_get`` returned by
#     ``gateway-send`` at initiation, persisted in ``tracking_code`` and matched
#     exactly.
#   * ``gateway-result-second`` verification needs BOTH ``trans_id`` (from the
#     callback) and ``id_get`` (persisted at initiation), and its success body
#     echoes the paid ``amount`` and the ``factorId`` — both are matched against
#     the stored attempt before any settlement.
#
# Everything above (DigiPay) is untouched. Settlement is reused: the generic
# ``settle_verified_payment`` binds on ``invoice_revision`` + amount, so a
# late/foreign success is preserved for staff rather than applied.

# BitPay has no UPG "ticket type"; the NOT NULL ``type`` column stores this
# sentinel so staff tooling can distinguish a BitPay attempt from a DigiPay one.
BITPAY_TICKET_TYPE = 0

# The documented gateway ``factorId`` is a Latin integer only. For a BitPay
# attempt we send the attempt's own integer id and persist it (as a string) in
# ``provider_id`` — the one existing, unique merchant-reference column — so the
# verify echo can be matched exactly. ``[0-9]`` (not ``\d``) on purpose: a
# non-Latin decimal (e.g. Arabic-Indic digits) is likewise coerced to ``0`` by
# the gateway, so it must be treated as unreferenceable too.
_LATIN_DECIMAL_RE = re.compile(r"[0-9]+")


def _pending_bitpay_provider_id() -> str:
    """A temporary unique ``provider_id`` so a new row can be flushed for its id.

    The column is NOT NULL + UNIQUE, so the row cannot be inserted blank; this
    placeholder lives only across the flush and is overwritten with the attempt's
    Latin-decimal id before commit.
    """
    return f"pending-{secrets.token_hex(12)}"


def bitpay_factor_reference(attempt: CommercePaymentAttempt) -> str | None:
    """The exact numeric ``factorId`` a BitPay attempt was issued with, if any.

    A *new* attempt persists the Latin-decimal ``attempt.id`` in ``provider_id``
    and sends it as ``factorId``. A row created before the numeric-factor fix
    holds the historical alnum ``INV<id>-R<rev>-<hex>`` reference, whose factorId
    the gateway silently coerced to ``0`` on verify: it has no provable numeric
    reference and MUST NOT be settled by an ordinary callback or a regular staff
    reconcile. Returns ``None`` for such a legacy row (fail closed).
    """
    raw = getattr(attempt, "provider_id", None)
    if raw is None:
        return None
    text = str(raw).strip()
    if not _LATIN_DECIMAL_RE.fullmatch(text):
        return None
    return text


def find_bitpay_attempt_by_id_get(db: Session, id_get) -> CommercePaymentAttempt | None:
    """Resolve the attempt whose persisted ``id_get`` matches a callback hint.

    Matching is strictly by ``provider == bitpay`` and the ``id_get`` we
    received from ``gateway-send`` (stored as ``tracking_code``) — never by any
    other, callback-supplied value.
    """
    parsed = _int_or_none(id_get)
    if parsed is None or parsed <= 0:
        return None
    return (
        db.query(CommercePaymentAttempt)
        .filter(
            CommercePaymentAttempt.provider == PAYMENT_PROVIDER_BITPAY,
            CommercePaymentAttempt.tracking_code == str(parsed),
        )
        .order_by(CommercePaymentAttempt.id.desc())
        .first()
    )


def start_bitpay_payment(
    db: Session, invoice: CommerceInvoice, client, *, callback_url: str
) -> CommercePaymentAttempt:
    """Create (or resume) the durable attempt and start a BitPay transaction.

    Mirrors ``start_payment`` (DigiPay): the row is committed *before* the
    network call so a crash/timeout still leaves a reconcilable attempt, and a
    repeated click while an attempt is in flight returns the existing redirect
    instead of minting a second session.
    """
    assert_payment_allowed(invoice)
    amount_rial = toman_to_rial(invoice.total_toman)

    attempt = find_active_payment_attempt(db, invoice)
    if attempt is not None and attempt.provider != PAYMENT_PROVIDER_BITPAY:
        # A DigiPay attempt already holds this invoice's shared lock; a
        # cross-provider click is a conflict, never a resume that reflects the
        # other gateway's portal through the BitPay endpoint.
        raise CommerceStateError("پرداخت از درگاه دیگری برای این فاکتور در حال انجام است")
    if attempt is not None and attempt.redirect_url:
        return attempt

    if attempt is None:
        attempt = CommercePaymentAttempt(
            invoice_id=invoice.id,
            provider=PAYMENT_PROVIDER_BITPAY,
            state="initiating",
            # A NOT NULL + UNIQUE column: a placeholder is required so the row
            # can be flushed to obtain its id, which becomes the factorId.
            provider_id=_pending_bitpay_provider_id(),
            amount_rial=amount_rial,
            invoice_revision=invoice.revision,
            type=BITPAY_TICKET_TYPE,
        )
        db.add(attempt)
    else:
        attempt.provider = PAYMENT_PROVIDER_BITPAY
        attempt.amount_rial = amount_rial
        attempt.invoice_revision = invoice.revision
        attempt.type = BITPAY_TICKET_TYPE
        attempt.state = "initiating"

    try:
        # Flush first so the row has its id; the documented gateway ``factorId``
        # must be a Latin integer, so we send the attempt's own id and persist it
        # as the expected reference (``provider_id``). A reused in-flight row is
        # migrated the same way, so it too is issued/expected numerically.
        db.flush()
        attempt.provider_id = str(attempt.id)
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent initiation (partial unique index).
        db.rollback()
        existing = find_active_payment_attempt(db, invoice)
        if (
            existing is not None
            and existing.provider == PAYMENT_PROVIDER_BITPAY
            and existing.redirect_url
        ):
            return existing
        raise CommerceStateError("پرداخت دیگری برای این فاکتور در حال انجام است")

    db.refresh(attempt)
    try:
        session = client.create_payment(
            amount_rial=amount_rial,
            redirect_url=callback_url,
            factor_id=attempt.provider_id,
            name=(invoice.customer_name or None),
            mobile=(invoice.mobile or None),
            description=f"فاکتور #{invoice.id}",
        )
    except Exception as exc:  # noqa: BLE001 - gateway boundary → recoverable
        attempt.state = "unknown"
        attempt.last_error = _short(exc)
        db.commit()
        raise CommercePaymentError("ارتباط با درگاه پرداخت ناموفق بود") from exc

    # The id_get is the only durable key that can link the (factorId-less) GET
    # callback back to this attempt; persist it the moment the gateway returns.
    attempt.tracking_code = str(session.id_get)
    attempt.redirect_url = session.redirect_url
    attempt.state = "pending"
    attempt.last_error = None
    db.commit()
    db.refresh(attempt)
    return attempt


def _bitpay_verification_confirms(verified, attempt: CommercePaymentAttempt) -> bool:
    """True only when a BitPay verify proves the *exact* amount and factorId.

    The provider reply must report success AND carry an ``amount`` equal to the
    issued ``amount_rial`` AND a ``factorId`` equal to the Latin-decimal
    reference we sent (persisted in ``provider_id``). A success missing either
    identity field is not a confirmation — matching both is what stops a
    self-consistent forgery (or a genuine payment for a different invoice) from
    settling this attempt.

    Both sides must be Latin integers. A legacy alnum reference has no numeric
    value to compare (the gateway coerced it to ``0``) and a non-integer echo is
    likewise coerced, so neither can ever confirm — that is what keeps a pre-fix
    paid attempt from auto-settling.
    """
    if not getattr(verified, "is_success", False):
        return False
    if _int_or_none(getattr(verified, "amount_rial", None)) != attempt.amount_rial:
        return False
    expected = bitpay_factor_reference(attempt)
    if expected is None:
        return False
    echoed = getattr(verified, "factor_id", None)
    if echoed is None:
        return False
    echoed_text = str(echoed).strip()
    if not _LATIN_DECIMAL_RE.fullmatch(echoed_text):
        return False
    if echoed_text != expected:
        return False
    return True


def _hold_bitpay_attempt(db: Session, attempt: CommercePaymentAttempt, reason) -> None:
    """Keep an attempt open (still locking the invoice) on an unproven signal.

    Never terminally fails: a BitPay non-success rests on a callback-supplied
    ``trans_id`` (untrusted) and cannot prove OUR transaction failed, so it must
    not release the invoice lock. ``unknown`` is an active state, so the lock is
    retained and the row stays visible in the staff reconciliation queue.
    """
    if attempt.state in ACTIVE_ATTEMPT_STATES:
        attempt.state = "unknown"
        attempt.last_error = _short(reason)
        db.commit()


def handle_bitpay_callback(
    db: Session,
    client,
    *,
    trans_id,
    id_get,
    factor_id=None,
    background_tasks=None,
) -> str:
    """Process an untrusted BitPay GET callback; returns success|failed|pending.

    The query is a hint only: the invoice is settled solely after a
    server-to-server ``gateway-result-second`` verify confirms success with a
    matching amount + factorId, and after ``settle_verified_payment`` re-binds
    the attempt to the invoice's *current* revision + amount. ``factor_id`` is
    accepted as an optional callback hint but never trusted or required (BitPay
    does not echo it on the GET callback).
    """
    attempt = find_bitpay_attempt_by_id_get(db, id_get)
    if attempt is None:
        return "failed"
    if attempt.state == "verified":
        # Replay of an already-verified attempt: report the SAME outcome the
        # first callback produced — a flagged (unsettled) attempt must never
        # replay as a contradictory "success".
        if attempt.reconciliation_required:
            return "pending"
        return "success"

    # A legacy attempt carries the historical alnum ``provider_id``, whose
    # factorId the gateway coerced to ``0`` — the verify reply can never be
    # matched to it. Refuse to auto-settle here: keep the lock (the row stays
    # active and in the staff queue) for an explicit, audited manual settlement.
    if bitpay_factor_reference(attempt) is None:
        _hold_bitpay_attempt(
            db,
            attempt,
            "legacy alnum factorId reference; cannot auto-settle — "
            "needs audited manual settlement",
        )
        return "failed"

    parsed_trans = _int_or_none(trans_id)
    if parsed_trans is None or parsed_trans <= 0:
        _hold_bitpay_attempt(db, attempt, "callback trans_id invalid (unverified)")
        return "failed"

    # Provisional, staff-visible trans_id for a later reconcile; it is NOT
    # authoritative and is overwritten by the confirmed value only on success.
    if attempt.provider_trans_id is None:
        attempt.provider_trans_id = parsed_trans
        db.commit()

    try:
        verified = client.verify(trans_id=parsed_trans, id_get=_int_or_none(id_get))
    except Exception as exc:  # noqa: BLE001 - transient → recoverable unknown
        _hold_bitpay_attempt(db, attempt, exc)
        return "pending"

    if not _bitpay_verification_confirms(verified, attempt):
        # Non-success, or a success whose amount/factorId does not match the
        # attempt we issued: never settle, never release the lock.
        _hold_bitpay_attempt(
            db,
            attempt,
            f"provider verify did not confirm (status={getattr(verified, 'status', None)})",
        )
        return "failed"

    # Confirmed. Pin the confirmed trans_id, then settle — which re-checks the
    # attempt's revision + amount against the CURRENT invoice, so a success for
    # a stale/revoked invoice is preserved for staff instead of applied.
    attempt.provider_trans_id = parsed_trans
    db.commit()
    try:
        settle_verified_payment(
            db,
            attempt,
            tracking_code=str(_int_or_none(id_get)),
            background_tasks=background_tasks,
        )
    except CommerceReconciliationRequiredError:
        return "pending"
    return "success"


def _reconcile_bitpay_attempt(
    db: Session, attempt: CommercePaymentAttempt, client, *, background_tasks=None
) -> CommercePaymentAttempt:
    """Staff reconcile of a BitPay attempt: re-verify, else keep it open.

    Requires both the persisted ``id_get`` (``tracking_code``) and the
    ``trans_id`` captured from the callback; without either there is nothing to
    query, so the attempt is left open for an explicit, audited staff abandon.
    A reply that does not prove the exact amount + factorId keeps the lock held.
    """
    id_get = _int_or_none(attempt.tracking_code)
    trans_id = attempt.provider_trans_id
    if id_get is None or id_get <= 0 or not trans_id:
        return attempt
    if bitpay_factor_reference(attempt) is None:
        # Legacy alnum reference (factorId coerced to ``0``): never auto-settle
        # through a routine staff reconcile. Keep the lock and leave the row in
        # the queue for an explicit, audited manual settlement (or a staff
        # abandon).
        attempt.last_error = _short(
            "legacy alnum factorId reference; cannot auto-settle — "
            "needs audited manual settlement"
        )
        db.commit()
        db.refresh(attempt)
        return attempt
    if client is None:
        raise CommerceGatewayUnavailableError("درگاه پرداخت پیکربندی نشده است")

    try:
        verified = client.verify(trans_id=trans_id, id_get=id_get)
    except Exception as exc:  # noqa: BLE001 - transient; keep unknown
        attempt.last_error = _short(exc)
        db.commit()
        db.refresh(attempt)
        return attempt

    if _bitpay_verification_confirms(verified, attempt):
        try:
            settle_verified_payment(
                db, attempt, tracking_code=str(id_get), background_tasks=background_tasks
            )
        except CommerceReconciliationRequiredError:
            db.refresh(attempt)
        return attempt

    attempt.last_error = _short(
        f"reconcile: provider did not confirm (status={getattr(verified, 'status', None)})"
    )
    db.commit()
    db.refresh(attempt)
    return attempt


# ══════════════════════════════════════════════════════════════════════
# Audited, admin-only recovery of an already-paid *legacy* BitPay attempt
# ══════════════════════════════════════════════════════════════════════
#
# A pre-fix BitPay attempt persisted the historical alnum merchant reference
# ``INV<id>-R<rev>-<hex>`` as ``provider_id`` and sent it as ``factorId``. The
# documented gateway coerces any non-Integer factor to ``0`` on the verify
# reply, so such a row can NEVER be matched by the ordinary callback or a
# routine staff ``verify`` reconcile — both correctly fail closed and hold the
# lock (see ``handle_bitpay_callback`` / ``_reconcile_bitpay_attempt``).
#
# When the customer really did pay, an admin needs one explicit, audited way to
# close that gap. This is it — and it is deliberately the *narrowest* possible
# path. It re-verifies server-to-server and accepts ONLY the documented
# ``factorId == 0`` coercion artifact, together with an exact amount match and
# the attempt's OWN persisted ``id_get`` + ``trans_id`` (never a request value).
#
# It refuses, without exception:
#   * any non-BitPay attempt;
#   * any modern, numeric-factor attempt (``provider_id`` is a Latin decimal) —
#     that must settle through the ordinary callback/reconcile, so a genuine
#     numeric match can never be smuggled through a weaker zero-factor check;
#   * any attempt whose state is not the strict ``unknown`` one (an already
#     ``verified`` replay is returned as-is; anything else is a conflict);
#   * a missing/unpersisted ``id_get`` or ``trans_id`` (nothing to bind to);
#   * an invoice that is not the attempt's current revision+amount, or is not
#     payable (paid / revoked / revised);
#   * a verify that is not documented success ``1``/``11`` with the exact amount
#     AND the ``factorId`` coercion artifact ``0``.
#
# Nothing here is ever automatic: it runs only behind the admin-only route and
# requires an explicit attempt id + affirmation + reason.

# Documented ``gateway-result-second`` success statuses: ``1`` = fresh success,
# ``11`` = already verified. Both are genuine success.
BITPAY_VERIFY_SUCCESS_CODES = (1, 11)
# The exact ``factorId`` the gateway echoes after coercing a non-Integer factor
# reference (the historical alnum ``INV<id>-R<rev>-<hex>``) to an integer. It is
# the documented artifact that lets a legacy payment be recognised at all.
BITPAY_LEGACY_FACTOR_ECHO = "0"
# Audit action label; also the stable key the tests assert on.
LEGACY_RECOVERY_ACTION = "recover_legacy_bitpay"


def _bitpay_legacy_recovery_confirms(verified, attempt: CommercePaymentAttempt) -> bool:
    """True only for the documented legacy success: amount exact + factorId ``0``.

    Distinct from :func:`_bitpay_verification_confirms`, which *requires a
    numeric match* and therefore can never confirm a legacy row. Here the echo
    must be the coercion artifact ``0`` and the attempt must genuinely be a
    legacy (non-numeric) reference — a numeric attempt is refused so this weaker
    check can never be used to settle a modern payment.
    """
    if not getattr(verified, "is_success", False):
        return False
    if getattr(verified, "status", None) not in BITPAY_VERIFY_SUCCESS_CODES:
        return False
    if _int_or_none(getattr(verified, "amount_rial", None)) != attempt.amount_rial:
        return False
    # Only a legacy (non-numeric) reference may use this path.
    if bitpay_factor_reference(attempt) is not None:
        return False
    echoed = getattr(verified, "factor_id", None)
    if echoed is None:
        return False
    echoed_text = str(echoed).strip()
    if not _LATIN_DECIMAL_RE.fullmatch(echoed_text):
        return False
    return echoed_text == BITPAY_LEGACY_FACTOR_ECHO


def _legacy_bitpay_recovery_target(
    db: Session, attempt: CommercePaymentAttempt | None
) -> tuple[CommerceInvoice, int, int]:
    """Validate eligibility and return ``(invoice, id_get, trans_id)``.

    Every rejection raises (never silently proceeds) so the caller can only ever
    settle the exact, payable invoice an eligible legacy attempt binds to.
    """
    if attempt is None:
        raise CommerceNotFoundError("تراکنش یافت نشد")
    if attempt.provider != PAYMENT_PROVIDER_BITPAY:
        raise CommerceStateError("این تراکنش مربوط به درگاه بیت‌پی نیست")
    if bitpay_factor_reference(attempt) is not None:
        raise CommerceStateError(
            "این مسیر فقط برای تراکنش‌های قدیمی (ارجاع غیرعددی) است"
        )
    if attempt.state != "unknown":
        raise CommerceStateError("وضعیت این تراکنش برای بازیابی دستی مناسب نیست")

    # Bind to the evidence we durably hold — never to anything the caller sends.
    id_get = _int_or_none(attempt.tracking_code)
    if id_get is None or id_get <= 0:
        raise CommerceStateError("شناسه id_get این تراکنش ثبت نشده است")
    trans_id = _int_or_none(attempt.provider_trans_id)
    if trans_id is None or trans_id <= 0:
        raise CommerceStateError("شناسه trans_id این تراکنش ثبت نشده است")

    invoice = (
        db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
    )
    if invoice is None:
        raise CommerceNotFoundError("فاکتور یافت نشد")
    if invoice.state != "approved" or invoice.order_id is not None:
        raise CommerceStateError("فاکتور در وضعیت قابل تسویه نیست")
    if attempt.invoice_revision != invoice.revision:
        raise CommerceStateError("نسخه فاکتور با این تراکنش مطابقت ندارد")
    expected = _expected_amount_rial(invoice)
    if expected is None or attempt.amount_rial != expected:
        raise CommerceStateError("مبلغ تراکنش با فاکتور مطابقت ندارد")
    return invoice, id_get, trans_id


def _rebind_invoice_after_verify(
    db: Session, attempt: CommercePaymentAttempt
) -> CommerceInvoice | None:
    """Re-read the attempt's invoice from committed state after a provider call.

    The eligibility precheck runs *before* the server-to-server verify, which is
    slow enough for a concurrent revise/revoke to commit behind an
    already-loaded, identity-mapped invoice. Expiring forces the next read to
    hit the database rather than hand back the stale copy.
    """
    db.expire_all()
    return (
        db.query(CommerceInvoice)
        .filter(CommerceInvoice.id == attempt.invoice_id)
        .first()
    )


def _settlement_invoice_is_current(
    attempt: CommercePaymentAttempt, invoice: CommerceInvoice
) -> bool:
    """True only when a freshly-read invoice may still take this settlement.

    Mirrors the caller's eligibility check (payable state, no order yet) plus
    the shared ``_attempt_binds_invoice`` revision/amount bind, so a concurrent
    change detected after the verify can never mark the wrong invoice paid.
    """
    return (
        invoice.state == "approved"
        and invoice.order_id is None
        and _attempt_binds_invoice(attempt, invoice)
    )


def recover_legacy_bitpay_attempt(
    db: Session,
    attempt: CommercePaymentAttempt | None,
    client,
    *,
    reason: str,
    actor: str = "",
    background_tasks=None,
) -> CommercePaymentAttempt:
    """Admin-only, audited settlement of a genuine *legacy* BitPay payment.

    Re-verifies server-to-server (through the injected provider) using the
    attempt's own persisted ``trans_id`` + ``id_get``, requires the documented
    success ``1``/``11`` with the exact amount and the ``factorId == 0``
    coercion artifact, then settles through the shared
    :func:`settle_verified_payment` — which claims the ``approved → paid``
    transition with a single conditional UPDATE, so exactly one order is created
    even under concurrency or replay.

    The audit entry is added to the *same* session as the settlement, so the
    single commit inside ``settle_verified_payment`` persists both together —
    never the best-effort, separately-committed ``audit.log`` helper.

    A refused recovery is never an unsafe abandon: the attempt is left
    ``unknown`` (lock held, visible in the staff queue) and the invoice stays
    ``approved``. Nothing is read from or written to the card/PII fields, and no
    provider secret is logged.
    """
    if attempt is None:
        raise CommerceNotFoundError("تراکنش یافت نشد")

    reason = (reason or "").strip()
    if not reason:
        # An explicit, recorded reason is what makes the settlement an
        # authorized staff decision rather than an accidental one.
        raise CommerceValidationError("ثبت دلیل برای بازیابی پرداخت الزامی است")

    # Idempotent replay: an already-settled legacy recovery returns as-is and
    # must never create a second order. (Anything else — e.g. a flagged
    # reconciliation row — falls through to the strict eligibility check.)
    if attempt.state == "verified" and not attempt.reconciliation_required:
        return attempt

    invoice, id_get, trans_id = _legacy_bitpay_recovery_target(db, attempt)

    if client is None:
        raise CommerceGatewayUnavailableError("درگاه پرداخت پیکربندی نشده است")

    try:
        verified = client.verify(trans_id=trans_id, id_get=id_get)
    except Exception as exc:  # noqa: BLE001 - transient → keep the lock, surface it
        attempt.last_error = _short(f"legacy recovery verify failed: {exc}")
        db.commit()
        db.refresh(attempt)
        raise CommercePaymentError("ارتباط با درگاه پرداخت ناموفق بود") from exc

    if not _bitpay_legacy_recovery_confirms(verified, attempt):
        # Never settle and never release the lock: keep the attempt open for a
        # further staff decision. Record the status only — never the card/PII.
        attempt.last_error = _short(
            "legacy recovery: provider did not confirm legacy success "
            f"(status={getattr(verified, 'status', None)})"
        )
        db.commit()
        db.refresh(attempt)
        raise CommerceStateError("درگاه پرداخت این تراکنش را تأیید نکرد")

    # Confirmed. Re-bind against the invoice as it is *now*: the eligibility
    # precheck ran before the (potentially slow) provider round trip, so a
    # concurrent revision/amount change or revoke could since have made the
    # identity-mapped invoice stale. A stale success must never mark the wrong
    # invoice paid — keep the genuine confirmation for staff and refuse.
    fresh_invoice = _rebind_invoice_after_verify(db, attempt)
    if fresh_invoice is None or not _settlement_invoice_is_current(attempt, fresh_invoice):
        _mark_verified_needs_reconciliation(
            db, attempt, str(id_get),
            "legacy recovery blocked: invoice changed during provider verify "
            f"(state={getattr(fresh_invoice, 'state', None)} "
            f"revision={getattr(fresh_invoice, 'revision', None)} "
            "total_rial="
            f"{_expected_amount_rial(fresh_invoice) if fresh_invoice is not None else None})",
        )
        raise CommerceStateError(
            "فاکتور پس از تأیید درگاه تغییر کرده است؛ نیازمند بررسی دستی"
        )

    # The audit row is committed by ``settle_verified_payment`` in the *same*
    # transaction as the settlement (via ``on_success``): it exists exactly when
    # a settlement happened, and is never written on a reconciliation branch
    # that did not settle.
    audit_summary = (
        f"بازیابی پرداخت قدیمی بیت‌پی تراکنش #{attempt.id} "
        f"(فاکتور #{invoice.id}، مبلغ {attempt.amount_rial} ریال) — {reason}"
    )

    def _record_audit(inner_db, _invoice, settled_attempt):
        inner_db.add(
            AuditLog(
                user=actor or "system",
                action=LEGACY_RECOVERY_ACTION,
                entity="commerce_payment_attempt",
                entity_id=settled_attempt.id,
                summary=audit_summary,
            )
        )

    try:
        settle_verified_payment(
            db, attempt, tracking_code=str(id_get), background_tasks=background_tasks,
            on_success=_record_audit,
        )
    except CommerceReconciliationRequiredError as exc:
        # The fresh re-bind above makes this unreachable in normal operation. If
        # a change ever claims the row between that re-read and the conditional
        # UPDATE, the settlement already preserved the payment for staff; no
        # audit row was written and we never claim success.
        raise CommerceStateError(
            "پرداخت تأییدشده با فاکتور فعلی مطابقت ندارد؛ نیازمند بررسی دستی"
        ) from exc

    db.refresh(attempt)
    return attempt
