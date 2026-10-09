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
import secrets

from sqlalchemy.orm import Session, selectinload

from app.models import CommerceRequest, CommerceRequestItem, Product

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
