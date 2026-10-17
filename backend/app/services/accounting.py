"""Accounting service — ledger validation, aggregation and Shamsi CSV export.

Pure business logic for the accounting module (دفتر حسابداری), kept out of the
router so the invoice→income auto-sync (Task 4) can reuse the same validation
without going through HTTP. Three groups of concerns live here:

1. **Chart of accounts.** ``create_category`` / ``update_category`` /
   ``delete_category`` enforce the seed protection rules: a system «سرفصل» can
   never be renamed, retyped or deleted; a custom one may be archived (soft
   deletion) and only retyped while no transaction references it (the FK is
   ``ON DELETE RESTRICT``, so history must stay readable).
2. **Ledger validation.** ``create_transaction`` / ``update_transaction``
   enforce ``amount_toman > 0``, a non-blank title, a closed ``account_type``
   set and — the invariant the whole P&L rests on —
   ``transaction.type == category.type``. Invoice-linked rows are frozen:
   ``amount_toman``, ``type`` and ``transaction_date`` may not change and the row
   may never be deleted, so a gateway callback can never rewrite booked income.
   ``invoice_id`` is deliberately absent from the update input: the link is
   owned by the payment flow alone.
3. **Reporting.** ``compute_summary`` sums with SQL ``SUM()`` over a
   ``BigInteger`` column (Python ints are arbitrary precision, so nothing
   truncates at 2**31) and buckets months in Shamsi via ``jdatetime``;
   ``build_csv`` emits the accountant's UTF-8-BOM CSV with Shamsi dates.

Every guardrail failure raises ``HTTPException`` with a Persian ``detail`` —
the same text the frontend surfaces verbatim.
"""
from __future__ import annotations

import csv
import io
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Iterable, Optional

import jdatetime
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ACCOUNTING_TYPES,
    AccountingCategory,
    AccountingTransaction,
)

# ── Enumerations & labels ────────────────────────────────────────────
INCOME = "income"
EXPENSE = "expense"

# Closed set for «حساب / صندوق» — bank | cash | gateway | other, as designed.
ACCOUNT_TYPES = ("bank", "cash", "gateway", "other")

TYPE_LABELS = {INCOME: "درآمد", EXPENSE: "هزینه"}
ACCOUNT_TYPE_LABELS = {
    "bank": "بانک",
    "cash": "صندوق",
    "gateway": "درگاه",
    "other": "سایر",
}

# ── Uploads ──────────────────────────────────────────────────────────
ALLOWED_ATTACHMENT_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".pdf")
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB

# ``backend/uploads`` — same root the app serves at ``/uploads``.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_ROOT = os.path.join(_BACKEND_DIR, "uploads")
ACCOUNTING_UPLOAD_DIR = os.path.join(UPLOAD_ROOT, "accounting")
ATTACHMENT_URL_PREFIX = "/uploads/accounting"

# ── CSV columns, in the accountant's order (Persian headers) ─────────
CSV_COLUMNS = [
    "شناسه",
    "تاریخ",
    "عنوان",
    "سرفصل",
    "نوع",
    "مبلغ به تومان",
    "حساب / صندوق",
    "شماره پیگیری",
    "شماره فاکتور",
    "توضیحات",
]

# Fields a payment-linked (invoice) row may never have rewritten.
LINKED_FROZEN_FIELDS = ("amount_toman", "type", "transaction_date")

# Fields a manual row may update.
MANUAL_UPDATE_FIELDS = (
    "title",
    "category_id",
    "type",
    "amount_toman",
    "transaction_date",
    "account_type",
    "reference_code",
    "description",
    "attachment_url",
)


# ── Small helpers ────────────────────────────────────────────────────
def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 string for a timestamp (``None`` stays ``None``)."""
    return value.isoformat() if value is not None else None


def to_shamsi_date(value: Optional[date]) -> str:
    """Gregorian date → Shamsi ``YYYY/MM/DD`` (ASCII digits, Excel-friendly)."""
    if value is None:
        return ""
    jd = jdatetime.date.fromgregorian(date=value)
    return f"{jd.year:04d}/{jd.month:02d}/{jd.day:02d}"


def _shamsi_parts(value: date) -> tuple[int, int]:
    jd = jdatetime.date.fromgregorian(date=value)
    return jd.year, jd.month


def _escape_like(term: str) -> str:
    """Neutralise ``%``/``_`` so a search term is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_text(value: Optional[str], max_length: int) -> str:
    return (value or "").strip()[:max_length]


def _require_valid_type(value: str, field: str = "نوع") -> str:
    if value not in ACCOUNTING_TYPES:
        raise HTTPException(status_code=400, detail=f"{field} باید درآمد یا هزینه باشد")
    return value


def _require_valid_account_type(value: str) -> str:
    if value not in ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="نوع حساب انتخابی نامعتبر است")
    return value


# ── Serialization ────────────────────────────────────────────────────
def serialize_category(category: AccountingCategory) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "type": category.type,
        "is_system": bool(category.is_system),
        "is_active": bool(category.is_active),
        "created_at": _iso(category.created_at),
    }


def serialize_transaction(txn: AccountingTransaction) -> dict:
    """API shape of one ledger row, with the category joined in for the UI."""
    category = txn.category
    return {
        "id": txn.id,
        "title": txn.title,
        "category_id": txn.category_id,
        "category_name": category.name if category else None,
        "category_type": category.type if category else None,
        "type": txn.type,
        "type_label": TYPE_LABELS.get(txn.type, txn.type),
        "amount_toman": int(txn.amount_toman or 0),
        "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
        "account_type": txn.account_type,
        "account_type_label": ACCOUNT_TYPE_LABELS.get(txn.account_type, txn.account_type or ""),
        "reference_code": txn.reference_code or "",
        "description": txn.description or "",
        "attachment_url": txn.attachment_url,
        "invoice_id": txn.invoice_id,
        "order_id": txn.order_id,
        "created_by_user_id": txn.created_by_user_id,
        # Convenience flag for the table: invoice rows keep the delete button off.
        "is_invoice_linked": txn.invoice_id is not None,
        "created_at": _iso(txn.created_at),
        "updated_at": _iso(txn.updated_at),
    }


# ── Chart of accounts ────────────────────────────────────────────────
def list_categories(db: Session, type: Optional[str] = None) -> list[dict]:
    """Active categories, system «سرفصل»s first, then newest id order."""
    query = db.query(AccountingCategory).filter(AccountingCategory.is_active.is_(True))
    if type is not None:
        _require_valid_type(type)
        query = query.filter(AccountingCategory.type == type)
    rows = query.order_by(
        AccountingCategory.is_system.desc(), AccountingCategory.id.asc()
    ).all()
    return [serialize_category(row) for row in rows]


def get_category_or_404(db: Session, category_id: int) -> AccountingCategory:
    category = (
        db.query(AccountingCategory)
        .filter(AccountingCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="سرفصل یافت نشد")
    return category


def get_active_category_or_400(db: Session, category_id: int) -> AccountingCategory:
    """The category a transaction is being booked against (must be live)."""
    category = (
        db.query(AccountingCategory)
        .filter(AccountingCategory.id == category_id)
        .first()
    )
    if not category or not category.is_active:
        raise HTTPException(status_code=400, detail="سرفصل انتخابی یافت نشد یا غیرفعال است")
    return category


def _assert_type_matches(category: AccountingCategory, txn_type: str) -> None:
    if category.type != txn_type:
        raise HTTPException(
            status_code=400,
            detail="نوع تراکنش با نوع سرفصل مطابقت ندارد",
        )


def _assert_name_is_unique(
    db: Session,
    name: str,
    type: str,
    exclude_id: Optional[int] = None,
) -> None:
    """No two *active* categories may share ``(name, type)``."""
    query = db.query(AccountingCategory).filter(
        AccountingCategory.name == name,
        AccountingCategory.type == type,
        AccountingCategory.is_active.is_(True),
    )
    if exclude_id is not None:
        query = query.filter(AccountingCategory.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=400, detail="سرفصل با این نام و نوع قبلاً ثبت شده است")


def create_category(db: Session, name: str, type: str) -> dict:
    """Create a *custom* (``is_system=False``) active «سرفصل»."""
    clean_name = _clean_text(name, 100)
    if not clean_name:
        raise HTTPException(status_code=400, detail="نام سرفصل نمی‌تواند خالی باشد")
    _require_valid_type(type)
    _assert_name_is_unique(db, clean_name, type)

    category = AccountingCategory(
        name=clean_name, type=type, is_system=False, is_active=True
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return serialize_category(category)


def _transactions_under_category(db: Session, category_id: int) -> int:
    return (
        db.query(func.count(AccountingTransaction.id))
        .filter(AccountingTransaction.category_id == category_id)
        .scalar()
        or 0
    )


def update_category(
    db: Session,
    category_id: int,
    name: Optional[str] = None,
    type: Optional[str] = None,
) -> dict:
    """Rename a custom «سرفصل»; retype only while nothing is booked under it."""
    category = get_category_or_404(db, category_id)

    if category.is_system:
        raise HTTPException(
            status_code=400,
            detail="سرفصل‌های سیستمی قابل ویرایش نیستند",
        )

    if name is not None:
        clean_name = _clean_text(name, 100)
        if not clean_name:
            raise HTTPException(status_code=400, detail="نام سرفصل نمی‌تواند خالی باشد")
        _assert_name_is_unique(db, clean_name, category.type, exclude_id=category.id)
        category.name = clean_name

    if type is not None and type != category.type:
        _require_valid_type(type)
        booked = _transactions_under_category(db, category.id)
        if booked:
            raise HTTPException(
                status_code=400,
                detail="تا زمانی که تراکنشی به این سرفصل متصل است، نوع آن قابل تغییر نیست",
            )
        _assert_name_is_unique(db, category.name, type, exclude_id=category.id)
        category.type = type

    db.commit()
    db.refresh(category)
    return serialize_category(category)


def delete_category(db: Session, category_id: int) -> dict:
    """Archive (soft delete) a custom «سرفصل»; refuse system rows outright."""
    category = get_category_or_404(db, category_id)
    if category.is_system:
        raise HTTPException(
            status_code=400, detail="سرفصل‌های سیستمی قابل حذف نیستند"
        )
    category.is_active = False
    db.commit()
    return {"message": "سرفصل بایگانی شد", "id": category_id}


# ── Ledger queries ───────────────────────────────────────────────────
def _apply_range(query, start_date: Optional[date], end_date: Optional[date]):
    if start_date is not None:
        query = query.filter(AccountingTransaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(AccountingTransaction.transaction_date <= end_date)
    return query


def filter_transaction_query(
    db: Session,
    *,
    type: Optional[str] = None,
    category_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    account_type: Optional[str] = None,
    search: Optional[str] = None,
):
    """The shared filter chain behind the list *and* the CSV export."""
    query = db.query(AccountingTransaction).options(
        joinedload(AccountingTransaction.category)
    )
    if type is not None:
        _require_valid_type(type)
        query = query.filter(AccountingTransaction.type == type)
    if category_id is not None:
        query = query.filter(AccountingTransaction.category_id == category_id)
    if account_type is not None:
        _require_valid_account_type(account_type)
        query = query.filter(AccountingTransaction.account_type == account_type)
    query = _apply_range(query, start_date, end_date)

    term = (search or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        query = query.filter(
            or_(
                AccountingTransaction.title.ilike(pattern, escape="\\"),
                AccountingTransaction.reference_code.ilike(pattern, escape="\\"),
                AccountingTransaction.description.ilike(pattern, escape="\\"),
            )
        )
    return query


def list_transactions(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    **filters: Any,
) -> dict:
    """One page of ledger rows (newest first) plus the total for pagination."""
    query = filter_transaction_query(db, **filters)
    total_count = query.order_by(None).count()
    items = (
        query.order_by(
            AccountingTransaction.transaction_date.desc(),
            AccountingTransaction.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_transaction(item) for item in items],
        "total_count": int(total_count),
        "has_more": (offset + len(items)) < total_count,
    }


def get_transaction_or_404(db: Session, transaction_id: int) -> AccountingTransaction:
    txn = (
        db.query(AccountingTransaction)
        .options(joinedload(AccountingTransaction.category))
        .filter(AccountingTransaction.id == transaction_id)
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="تراکنش یافت نشد")
    return txn


# ── Ledger writes ────────────────────────────────────────────────────
def create_transaction(
    db: Session,
    *,
    title: str,
    category_id: int,
    type: str,
    amount_toman: int,
    transaction_date: date,
    account_type: str = "bank",
    reference_code: str = "",
    description: str = "",
    attachment_url: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
) -> dict:
    """Book a manual income/expense row (``invoice_id`` stays ``None``)."""
    clean_title = _clean_text(title, 200)
    if not clean_title:
        raise HTTPException(status_code=400, detail="عنوان تراکنش نمی‌تواند خالی باشد")
    _require_valid_type(type)
    if amount_toman is None or int(amount_toman) <= 0:
        raise HTTPException(status_code=400, detail="مبلغ باید بزرگ‌تر از صفر باشد")
    _require_valid_account_type(account_type or "bank")

    category = get_active_category_or_400(db, category_id)
    _assert_type_matches(category, type)

    txn = AccountingTransaction(
        title=clean_title,
        category_id=category.id,
        type=type,
        amount_toman=int(amount_toman),
        transaction_date=transaction_date,
        account_type=account_type or "bank",
        reference_code=_clean_text(reference_code, 100),
        description=_clean_text(description, 1000),
        attachment_url=_clean_text(attachment_url, 500) or None,
        created_by_user_id=created_by_user_id,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return serialize_transaction(txn)


def update_transaction(
    db: Session,
    transaction_id: int,
    payload: dict,
) -> dict:
    """Apply a partial update, honouring the invoice-linked guardrails.

    ``payload`` holds only the fields the client actually sent (the router
    passes ``model_dump(exclude_unset=True)``), which is what lets a frozen
    field be told apart from an untouched one.
    """
    txn = get_transaction_or_404(db, transaction_id)
    payload = {k: v for k, v in payload.items() if k in MANUAL_UPDATE_FIELDS}

    linked = txn.invoice_id is not None
    if linked:
        # Booked invoice income is immutable: the payment flow owns the amount,
        # the direction and the booking date.
        for field in LINKED_FROZEN_FIELDS:
            if field in payload and payload[field] != getattr(txn, field):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "مبلغ، نوع و تاریخ تراکنش‌های متصل به فاکتور قابل تغییر نیست"
                    ),
                )

    # ── Validate against the *effective* post-update state ──
    new_type = payload.get("type", txn.type)
    _require_valid_type(new_type)

    category_changed = "category_id" in payload and payload["category_id"] != txn.category_id
    if "category_id" in payload:
        category = get_active_category_or_400(db, payload["category_id"])
    else:
        category = txn.category
    _assert_type_matches(category, new_type)

    if "amount_toman" in payload and (
        payload["amount_toman"] is None or int(payload["amount_toman"]) <= 0
    ):
        raise HTTPException(status_code=400, detail="مبلغ باید بزرگ‌تر از صفر باشد")

    if "title" in payload:
        clean_title = _clean_text(payload["title"], 200)
        if not clean_title:
            raise HTTPException(
                status_code=400, detail="عنوان تراکنش نمی‌تواند خالی باشد"
            )
        payload["title"] = clean_title

    if "account_type" in payload:
        _require_valid_account_type(payload["account_type"] or "")

    for field, value in payload.items():
        if field in ("reference_code", "description", "attachment_url"):
            if field == "attachment_url":
                setattr(txn, field, _clean_text(value, 500) or None)
            elif field == "reference_code":
                setattr(txn, field, _clean_text(value, 100))
            else:
                setattr(txn, field, _clean_text(value, 1000))
        else:
            setattr(txn, field, value)

    if category_changed:
        txn.category_id = category.id

    db.commit()
    db.refresh(txn)
    return serialize_transaction(txn)


def delete_transaction(db: Session, transaction_id: int) -> dict:
    """Hard-delete a manual row; refuse rows owned by a paid invoice."""
    txn = get_transaction_or_404(db, transaction_id)
    if txn.invoice_id is not None:
        raise HTTPException(
            status_code=400,
            detail="تراکنش‌های متصل به فاکتورهای پرداخت‌شده قابل حذف نیستند",
        )
    db.delete(txn)
    db.commit()
    return {"message": "تراکنش حذف شد", "id": transaction_id}


# ── Summary (P&L) ────────────────────────────────────────────────────
def compute_summary(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Cash-basis P&L: totals, margin, per-category and per-Shamsi-month splits.

    ``SUM()`` runs inside SQLite over a ``BigInteger`` column and is handed back
    as a Python ``int`` (arbitrary precision), so a busy year never overflows.
    """
    range_filters = []
    if start_date is not None:
        range_filters.append(AccountingTransaction.transaction_date >= start_date)
    if end_date is not None:
        range_filters.append(AccountingTransaction.transaction_date <= end_date)

    def _sum(txn_type: str) -> int:
        value = (
            db.query(func.coalesce(func.sum(AccountingTransaction.amount_toman), 0))
            .filter(AccountingTransaction.type == txn_type, *range_filters)
            .scalar()
        )
        return int(value or 0)

    total_income = _sum(INCOME)
    total_expense = _sum(EXPENSE)
    net_profit = total_income - total_expense
    profit_margin_pct = (
        round(net_profit / total_income * 100, 2) if total_income > 0 else 0.0
    )

    transaction_count = (
        db.query(func.count(AccountingTransaction.id)).filter(*range_filters).scalar()
        or 0
    )

    # Per-category breakdown (both directions, largest line first).
    total_expr = func.coalesce(func.sum(AccountingTransaction.amount_toman), 0)
    category_rows = (
        db.query(
            AccountingCategory.id.label("category_id"),
            AccountingCategory.name.label("name"),
            AccountingCategory.type.label("type"),
            total_expr.label("total_toman"),
            func.count(AccountingTransaction.id).label("count"),
        )
        .join(AccountingTransaction, AccountingTransaction.category_id == AccountingCategory.id)
        .filter(*range_filters)
        .group_by(AccountingCategory.id, AccountingCategory.name, AccountingCategory.type)
        .order_by(total_expr.desc(), AccountingCategory.id.asc())
        .all()
    )
    by_category = [
        {
            "category_id": row.category_id,
            "name": row.name,
            "type": row.type,
            "total_toman": int(row.total_toman or 0),
            "count": int(row.count or 0),
        }
        for row in category_rows
    ]

    # Per-month breakdown, bucketed by *Shamsi* month (the UI filters in Shamsi).
    month_rows = (
        db.query(
            AccountingTransaction.transaction_date,
            AccountingTransaction.type,
            AccountingTransaction.amount_toman,
        )
        .filter(*range_filters)
        .all()
    )
    buckets: dict[tuple[int, int], dict[str, int]] = {}
    for txn_date, txn_type, amount in month_rows:
        if txn_date is None:
            continue
        key = _shamsi_parts(txn_date)
        bucket = buckets.setdefault(key, {INCOME: 0, EXPENSE: 0})
        bucket[txn_type] = bucket.get(txn_type, 0) + int(amount or 0)

    by_month = [
        {
            "year": year,
            "month": month,
            "label": f"{year:04d}/{month:02d}",
            "income": buckets[(year, month)].get(INCOME, 0),
            "expense": buckets[(year, month)].get(EXPENSE, 0),
            "net_profit": buckets[(year, month)].get(INCOME, 0)
            - buckets[(year, month)].get(EXPENSE, 0),
        }
        for year, month in sorted(buckets)
    ]

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_income": total_income,
        "total_expense": total_expense,
        "net_profit": net_profit,
        "profit_margin_pct": profit_margin_pct,
        "transaction_count": int(transaction_count),
        "by_category": by_category,
        "by_month": by_month,
    }


# ── CSV export ───────────────────────────────────────────────────────
def transaction_to_csv_row(txn: AccountingTransaction) -> list[str]:
    return [
        str(txn.id),
        to_shamsi_date(txn.transaction_date),
        txn.title or "",
        txn.category.name if txn.category else "",
        TYPE_LABELS.get(txn.type, txn.type or ""),
        str(int(txn.amount_toman or 0)),
        ACCOUNT_TYPE_LABELS.get(txn.account_type, txn.account_type or ""),
        txn.reference_code or "",
        str(txn.invoice_id) if txn.invoice_id is not None else "",
        txn.description or "",
    ]


def build_csv(transactions: Iterable[AccountingTransaction]) -> str:
    """Excel-ready CSV: UTF-8 BOM + Persian headers + Shamsi dates.

    The BOM is what makes Excel open the file as UTF-8 instead of mojibake.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for txn in transactions:
        writer.writerow(transaction_to_csv_row(txn))
    return "\ufeff" + buffer.getvalue()


def export_transactions(db: Session, **filters: Any) -> list[AccountingTransaction]:
    """Every row matching the list filters, oldest first (accountant's order)."""
    return (
        filter_transaction_query(db, **filters)
        .order_by(
            AccountingTransaction.transaction_date.asc(),
            AccountingTransaction.id.asc(),
        )
        .all()
    )


# ── Attachment upload ────────────────────────────────────────────────
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._\u0600-\u06FF-]")


def save_attachment(
    content: bytes,
    filename: str,
    upload_dir: Optional[str] = None,
) -> str:
    """Persist a receipt/bill and return its public ``/uploads/...`` URL.

    The stored name is ``<uuid4>_<sanitised-stem><ext>``: the uuid makes two
    uploads of the same receipt impossible to collide, and only the basename
    survives, so ``../../evil.png`` cannot escape the accounting folder.
    """
    if not content:
        raise HTTPException(status_code=400, detail="فایل ارسالی خالی است")

    base = os.path.basename(str(filename or "").replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in ALLOWED_ATTACHMENT_EXTS:
        raise HTTPException(
            status_code=400,
            detail="فرمت فایل مجاز نیست (تصویر jpg، png، webp یا فایل pdf)",
        )

    safe_stem = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip("._")[:80] or "receipt"
    stored_name = f"{uuid.uuid4().hex}_{safe_stem}{ext}"

    target_dir = upload_dir or ACCOUNTING_UPLOAD_DIR
    os.makedirs(target_dir, exist_ok=True)
    with open(os.path.join(target_dir, stored_name), "wb") as handle:
        handle.write(content)

    return f"{ATTACHMENT_URL_PREFIX}/{stored_name}"
