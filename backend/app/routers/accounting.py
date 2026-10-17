"""Accounting module HTTP boundary — «دفتر حسابداری» CRUD, P&L and export.

Eleven routes under ``/api/v1/accounting``, all staff-gated (``admin`` or
``employee``; the gate is applied on ``include_router`` in ``app.main``, in line
with the other management routers):

* ``categories``   — the chart of accounts (list / create / rename / archive)
* ``transactions`` — the ledger (list with filters + pagination, create, update,
  delete) with invoice-linked guardrails
* ``summary``      — cash-basis P&L: totals, margin, per-category, per-Shamsi-month
* ``export``       — UTF-8-BOM CSV with Shamsi dates, same filters as the list
* ``upload-attachment`` — receipt/bill upload (jpg/png/webp/pdf, ≤ 5 MB)

Validation, aggregation and CSV shaping all live in
``app.services.accounting`` so the invoice→income auto-sync can reuse them
without an HTTP round-trip; this module only marshals request/response.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import require_staff_role
from app.services import accounting as accounting_service
from app.services.uploads import read_upload_limited

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])

_EXPORT_FILENAME = "accounting_transactions.csv"


# ── Request bodies ───────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    name: str
    type: str


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    # Retyping is only honoured while no transaction is booked under the
    # category — the service enforces it.
    type: Optional[str] = None


class TransactionCreate(BaseModel):
    title: str
    category_id: int
    type: str
    amount_toman: int
    transaction_date: date
    account_type: str = "bank"
    reference_code: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    attachment_url: Optional[str] = Field(default=None, max_length=500)


class TransactionUpdate(BaseModel):
    """Partial update. ``invoice_id``/``order_id`` are absent on purpose: the
    invoice link belongs to the payment flow, never to a ledger edit."""

    title: Optional[str] = Field(default=None, max_length=200)
    category_id: Optional[int] = None
    type: Optional[str] = None
    amount_toman: Optional[int] = None
    transaction_date: Optional[date] = None
    account_type: Optional[str] = None
    reference_code: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    attachment_url: Optional[str] = Field(default=None, max_length=500)


# ── Categories (chart of accounts) ───────────────────────────────────
@router.get("/categories")
def list_categories(
    type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Active «سرفصل»s; system seeds first, filterable by ``income``/``expense``."""
    return accounting_service.list_categories(db, type=type)


@router.post("/categories")
def create_category(body: CategoryCreate, db: Session = Depends(get_db)):
    """Add a custom category (``is_system=False``, active, unique per type)."""
    return accounting_service.create_category(db, name=body.name, type=body.type)


@router.put("/categories/{category_id}")
def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
):
    """Rename a custom «سرفصل». System rows are read-only."""
    return accounting_service.update_category(
        db, category_id, name=body.name, type=body.type
    )


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Archive (soft delete) a custom «سرفصل»; system rows cannot be deleted."""
    return accounting_service.delete_category(db, category_id)


# ── Transactions (ledger) ────────────────────────────────────────────
@router.get("/transactions")
def list_transactions(
    type: Optional[str] = None,
    category_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    account_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """One page of ledger rows plus ``total_count`` / ``has_more``."""
    return accounting_service.list_transactions(
        db,
        type=type,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        account_type=account_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post("/transactions")
def create_transaction(
    body: TransactionCreate,
    db: Session = Depends(get_db),
    user=Depends(require_staff_role),
):
    """Book a manual income/expense row stamped with the acting staff user."""
    return accounting_service.create_transaction(
        db,
        title=body.title,
        category_id=body.category_id,
        type=body.type,
        amount_toman=body.amount_toman,
        transaction_date=body.transaction_date,
        account_type=body.account_type,
        reference_code=body.reference_code,
        description=body.description,
        attachment_url=body.attachment_url,
        created_by_user_id=user.get("id"),
    )


@router.put("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    db: Session = Depends(get_db),
):
    """Update a manual row, or an invoice-linked one's four editable fields.

    ``invoice_id IS NOT NULL`` → only ``description``, ``category_id`` (income),
    ``reference_code`` and ``attachment_url`` may change; an unchanged echo of
    any other field is a no-op, a real edit is a 400.
    """
    return accounting_service.update_transaction(
        db, transaction_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Delete a manual row; invoice-linked rows are refused."""
    return accounting_service.delete_transaction(db, transaction_id)


# ── Receipt / bill upload ────────────────────────────────────────────
@router.post("/upload-attachment")
async def upload_attachment(file: UploadFile = File(...)):
    """Store a receipt (jpg/png/webp) or bill (pdf) of at most 5 MB."""
    content = await read_upload_limited(
        file,
        max_bytes=accounting_service.MAX_ATTACHMENT_BYTES,
        detail="حجم فایل بیشتر از ۵ مگابایت است",
    )
    attachment_url = accounting_service.save_attachment(
        content, file.filename or ""
    )
    return {"attachment_url": attachment_url}


# ── Summary & export ─────────────────────────────────────────────────
@router.get("/summary")
def get_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Cash-basis P&L for the (inclusive) Gregorian date range."""
    return accounting_service.compute_summary(
        db, start_date=start_date, end_date=end_date
    )


@router.get("/export")
def export_transactions(
    type: Optional[str] = None,
    category_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    account_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Downloaded CSV of every filtered row, Shamsi-dated and BOM-prefixed."""
    rows = accounting_service.export_transactions(
        db,
        type=type,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        account_type=account_type,
        search=search,
    )
    return Response(
        content=accounting_service.build_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={_EXPORT_FILENAME}",
        },
    )
