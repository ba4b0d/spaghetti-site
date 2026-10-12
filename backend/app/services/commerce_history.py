"""Verified-customer order history — exact-mobile, bounded, redacted read.

A customer proves ownership of a mobile once (see
``app.services.commerce_history_auth``) and then reads **only** the requests and
invoices recorded against that exact canonical number. There is no account and
no write path here: this module is a read model plus an allowlisting serializer.

Design rules:

* **Exact mobile only.** Both tables are queried by canonical equality
  (``mobile == <canonical>``); a path/query parameter can never address another
  number, so IDs in the response are display identifiers, never credentials.
* **Bounded.** The whole history is never loaded into Python. A ``UNION ALL`` of
  projected ``(kind, id, created_at)`` rows is ordered and paginated *in SQL*;
  only the resulting page's rows (with their snapshot items, eager-loaded) are
  fetched. The caller passes ``limit``/``offset`` and derives ``has_more`` from a
  ``limit + 1`` fetch.
* **Deterministic order.** ``created_at DESC, kind ASC, id DESC`` — the tie-break
  makes a page boundary stable, so pagination never repeats or skips a row.
* **Allowlisted fields.** Every entry is built field-by-field from a fixed
  schema; a model ``__dict__`` is never spread into a response. Internal notes,
  full address, messenger handle, the private invoice token hash, gateway
  identifiers and the raw payment link are structurally absent.
* **Finalized money only for settled states.** Only ``approved``/``paid``
  invoices expose ``shipping_toman``/``total_toman`` and per-item prices; a
  ``draft``/``revoked`` invoice shows names and quantities but no amounts, and
  unknown states are never treated as payable. ``paid`` is read from the DB
  column — never inferred from a redirect or a request parameter.
"""
from datetime import datetime, timezone

from sqlalchemy import literal, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.models import CommerceInvoice, CommerceRequest

# ── Bounds ───────────────────────────────────────────────────────────
HISTORY_DEFAULT_LIMIT = 20
HISTORY_MAX_LIMIT = 50
HISTORY_MAX_OFFSET = 10_000

# ── Entry kinds ──────────────────────────────────────────────────────
KIND_REQUEST = "request"
KIND_INVOICE = "invoice"

# The only invoice states whose money is presented as final. ``paid`` is the
# persisted, server-verified settlement state — this module never derives it.
FINAL_INVOICE_STATES = ("approved", "paid")


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime read back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    dt = _as_utc(value)
    return dt.isoformat() if dt is not None else None


def _page_index(db: Session, mobile: str, *, limit: int, offset: int):
    """The page's ``(kind, id, created_at)`` rows, ordered and paginated in SQL.

    ``UNION ALL`` projects only the three columns pagination needs, so neither
    table is materialized in Python; ``mobile`` is indexed on both tables, which
    keeps the scan bounded to the one number.
    """
    request_ids = select(
        literal(KIND_REQUEST).label("kind"),
        CommerceRequest.id.label("id"),
        CommerceRequest.created_at.label("created_at"),
    ).where(CommerceRequest.mobile == mobile)
    invoice_ids = select(
        literal(KIND_INVOICE).label("kind"),
        CommerceInvoice.id.label("id"),
        CommerceInvoice.created_at.label("created_at"),
    ).where(CommerceInvoice.mobile == mobile)

    combined = union_all(request_ids, invoice_ids).subquery("history_index")
    stmt = (
        select(combined.c.kind, combined.c.id, combined.c.created_at)
        .order_by(
            combined.c.created_at.desc(),
            combined.c.kind.asc(),
            combined.c.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return db.execute(stmt).all()


# ── Allowlisted serializers ──────────────────────────────────────────
def _serialize_request_item(item) -> dict:
    """Customer-visible name + quantity only — no indicative price."""
    return {"name": item.display_name, "qty": item.qty}


def _serialize_invoice_item(item, *, finalized: bool) -> dict:
    """Name + quantity, plus frozen prices only for a settled invoice."""
    data = {"name": item.description, "qty": item.qty}
    if finalized:
        data["unit_toman"] = item.unit_toman
        data["line_total_toman"] = item.line_total_toman
    return data


def _serialize_request(request: CommerceRequest) -> dict:
    return {
        "kind": KIND_REQUEST,
        "id": request.id,
        # A request entry's ``request_id`` is its own id: the field always names
        # the website request an entry belongs to (null for a manual invoice).
        "request_id": request.id,
        "state": request.state,
        "created_at": _iso(request.created_at),
        "items": [_serialize_request_item(i) for i in request.items],
    }


def _serialize_invoice(invoice: CommerceInvoice) -> dict:
    finalized = invoice.state in FINAL_INVOICE_STATES
    entry = {
        "kind": KIND_INVOICE,
        "id": invoice.id,
        "request_id": invoice.request_id,
        "state": invoice.state,
        "created_at": _iso(invoice.created_at),
        "items": [
            _serialize_invoice_item(i, finalized=finalized) for i in invoice.items
        ],
    }
    if finalized:
        entry["shipping_toman"] = invoice.shipping_toman
        entry["total_toman"] = invoice.total_toman
    return entry


def list_history(
    db: Session, mobile: str, *, limit: int, offset: int
) -> list[dict]:
    """Newest-first redacted entries for ``mobile`` (exact, bounded, ordered).

    ``limit``/``offset`` are passed straight to the SQL page query; the caller
    is expected to request ``limit + 1`` when it needs to derive ``has_more``.
    Only the page's rows are loaded with their snapshot items.
    """
    page = _page_index(db, mobile, limit=limit, offset=offset)
    if not page:
        return []

    request_ids = [row.id for row in page if row.kind == KIND_REQUEST]
    invoice_ids = [row.id for row in page if row.kind == KIND_INVOICE]

    requests: dict[int, CommerceRequest] = {}
    if request_ids:
        requests = {
            r.id: r
            for r in db.query(CommerceRequest)
            .options(selectinload(CommerceRequest.items))
            .filter(CommerceRequest.id.in_(request_ids))
            .all()
        }

    invoices: dict[int, CommerceInvoice] = {}
    if invoice_ids:
        invoices = {
            i.id: i
            for i in db.query(CommerceInvoice)
            .options(selectinload(CommerceInvoice.items))
            .filter(CommerceInvoice.id.in_(invoice_ids))
            .all()
        }

    entries: list[dict] = []
    for row in page:
        if row.kind == KIND_REQUEST:
            obj = requests.get(row.id)
            if obj is not None:
                entries.append(_serialize_request(obj))
        else:
            obj = invoices.get(row.id)
            if obj is not None:
                entries.append(_serialize_invoice(obj))
    return entries
