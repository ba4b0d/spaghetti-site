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
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    COMMERCE_INVOICE_STATES,
    INVOICE_LINK_TTL_DAYS,
    MAX_INVOICE_TOTAL_TOMAN,
    CommerceInvoice,
    CommerceInvoiceItem,
    CommercePaymentAttempt,
    CommerceRequest,
    CommerceRequestItem,
    Order,
    OrderItem,
    Product,
)

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
) -> CommerceRequest:
    """Persist a pending-review website request with server-side item snapshots.

    ``items`` is a list of ``{"product_id": int, "qty": int}``. Any other keys
    (including client-supplied prices) are deliberately ignored.
    """
    if not items:
        raise CommerceValidationError("سبد خرید خالی است")

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
    db.commit()
    db.refresh(request)

    # Task 4 emits the `request_created` admin notification here, *after* this
    # commit, so a notification failure can never roll back a committed order.
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


def approve_invoice(db: Session, invoice_id: int) -> tuple[CommerceInvoice, str]:
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
DIGIPAY_TICKET_TYPE = 11
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
        .filter(CommercePaymentAttempt.provider_id == provider_id)
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
        if existing is not None and existing.redirect_url:
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


def _create_legacy_order(db: Session, invoice: CommerceInvoice) -> Order:
    """One legacy Order (+items) mirroring the paid invoice, paid in full.

    A synthetic shipping line keeps ``sum(items) == paid_amount == total_toman``
    so the existing order board's accounting stays consistent. Status stays
    ``new``: fulfillment remains a staff decision, never auto-set to printing.
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
        notes=f"پرداخت آنلاین فاکتور #{invoice.id} از طریق دیجی‌پی",
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


def settle_verified_payment(
    db: Session, attempt: CommercePaymentAttempt, *, tracking_code: str
) -> CommercePaymentAttempt:
    """Atomically mark the attempt verified, the invoice paid and link ONE order.

    Safe under replay/concurrency: the ``approved → paid`` transition is claimed
    with a single conditional UPDATE, so only the first writer creates the
    legacy order. Later callers see ``state == 'paid'`` and no-op.
    """
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
    if invoice is None:
        raise CommerceNotFoundError("فاکتور یافت نشد")

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
        if invoice is None or invoice.state != "paid":
            raise CommerceStateError("وضعیت فاکتور برای تسویه نامعتبر است")
        attempt.state = "verified"
        attempt.tracking_code = attempt.tracking_code or tracking_code
        attempt.verified_at = attempt.verified_at or _now()
        db.commit()
        return attempt

    db.expire_all()
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == attempt.invoice_id).first()
    if invoice.order_id is None:
        order = _create_legacy_order(db, invoice)
        invoice.order_id = order.id

    attempt.state = "verified"
    attempt.tracking_code = tracking_code
    attempt.verified_at = _now()
    attempt.last_error = None
    db.commit()
    db.refresh(attempt)
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


def _verify_confirms(verified: dict, attempt: CommercePaymentAttempt) -> bool:
    """Strict server-side confirmation: status 0 and identity/amount match."""
    if not isinstance(verified, dict):
        return False
    if _int_or_none(verified.get("status")) != 0:
        return False
    if _int_or_none(verified.get("amount")) != attempt.amount_rial:
        return False
    provider_id = verified.get("providerId") or verified.get("provider_id")
    if provider_id != attempt.provider_id:
        return False
    vtype = _int_or_none(verified.get("type"))
    if vtype is not None and vtype != attempt.type:
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
) -> str:
    """Process an untrusted provider callback.

    Returns ``success`` | ``failed`` | ``pending``. The callback is treated as a
    hint only: the invoice is settled solely when a server-to-server verify
    confirms ``status == 0`` with a matching providerId, amount and type.
    """
    attempt = find_payment_attempt_by_provider_id(db, provider_id)
    if attempt is None:
        return "failed"
    if attempt.state == "verified":
        return "success"  # idempotent replay

    def _fail(reason: str) -> None:
        if attempt.state in ACTIVE_ATTEMPT_STATES:
            attempt.state = "failed"
            attempt.last_error = _short(reason)
            db.commit()

    if _int_or_none(amount) != attempt.amount_rial:
        _fail("callback amount mismatch")
        return "failed"
    if _int_or_none(type_value) != attempt.type:
        _fail("callback type mismatch")
        return "failed"
    if not (tracking_code or "").strip():
        _fail("callback missing trackingCode")
        return "failed"
    if _callback_result_is_failure(result_value):
        _fail("callback reported failure")
        return "failed"

    try:
        verified = client.verify(
            tracking_code=tracking_code.strip(),
            provider_id=attempt.provider_id,
            type=attempt.type,
        )
    except Exception as exc:  # noqa: BLE001 - transient → recoverable unknown
        if attempt.state in ACTIVE_ATTEMPT_STATES:
            attempt.state = "unknown"
            attempt.last_error = _short(exc)
            db.commit()
        return "pending"

    if not _verify_confirms(verified, attempt):
        _fail("provider verify did not confirm")
        return "failed"

    settle_verified_payment(db, attempt, tracking_code=tracking_code.strip())
    return "success"
