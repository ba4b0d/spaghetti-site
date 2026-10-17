"""Task 2 — accounting API: categories, transactions, summary, export, upload.

Covers the HTTP contract the frontend accounting page (Task 6) and the
invoice→income auto-sync (Task 4) depend on:

* category CRUD with the seed protection rules (a system «سرفصل» can never be
  renamed, retyped or deleted — only archived if custom);
* manual transaction CRUD with ``transaction.type == category.type`` and
  ``amount_toman > 0`` enforced server-side, plus pagination/search;
* the invoice-linked guardrails: an auto-synced row can be re-described but its
  amount/type/date are frozen and it can never be deleted;
* summary aggregation that survives ``BigInteger`` magnitudes (a 32-bit
  ``SUM()`` would silently truncate);
* the CSV export: UTF-8 BOM, the ten Persian columns, and Shamsi dates;
* receipt upload: extension allow-list, 5 MB cap, and the served URL shape.

Auth is exercised through the real ``require_staff_role`` dependency, so an
unauthenticated caller is rejected and an employee (staff) is accepted.
"""
import csv
import importlib
import io
import os
import sys
from datetime import date

import pytest

from app.models import (
    AccountingCategory,
    AccountingTransaction,
    CommerceInvoice,
    seed_accounting_categories,
)
from app.services import accounting as accounting_service

# ── Fixtures ─────────────────────────────────────────────────────────
ZWNJ = "\u200c"

# The exact Persian contract strings the brief pins down (ZWNJ included).
SYSTEM_DELETE_DETAIL = f"سرفصل{ZWNJ}های سیستمی قابل حذف نیستند"
INVOICE_DELETE_DETAIL = (
    f"تراکنش{ZWNJ}های متصل به فاکتورهای پرداخت{ZWNJ}شده قابل حذف نیستند"
)

CSV_HEADER = [
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


def _test_session_local():
    """The session factory bound to the engine the API's ``get_db`` override uses.

    Resolved from ``sys.modules`` on purpose: importing ``conftest`` a second
    time would re-run its module body (which deletes and rebuilds ``test.db``)
    while the suite is live.
    """
    try:
        return importlib.import_module("tests.conftest").TestSessionLocal
    except Exception:  # pragma: no cover — depends on pytest import mode
        pass
    for name, module in list(sys.modules.items()):
        if name.endswith("conftest") and hasattr(module, "TestSessionLocal"):
            return module.TestSessionLocal
    raise RuntimeError("test session factory not found")  # pragma: no cover


@pytest.fixture()
def db(setup_test_db):
    """A direct session on the test database (for arranging ledger rows)."""
    session = _test_session_local()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    """The default chart of accounts, seeded as the startup hook would."""
    seed_accounting_categories(db)
    return db


def _expense_category_id(db):
    return (
        db.query(AccountingCategory)
        .filter(AccountingCategory.type == "expense", AccountingCategory.is_active == True)  # noqa: E712
        .order_by(AccountingCategory.id)
        .first()
        .id
    )


def _income_category_id(db):
    return (
        db.query(AccountingCategory)
        .filter(AccountingCategory.type == "income", AccountingCategory.is_active == True)  # noqa: E712
        .order_by(AccountingCategory.id)
        .first()
        .id
    )


def _post_txn(client, headers, **overrides):
    payload = {
        "title": "خرید رول PLA مشکی",
        "category_id": overrides.pop("category_id"),
        "type": "expense",
        "amount_toman": 450_000,
        "transaction_date": "2026-10-17",
        "account_type": "bank",
        "reference_code": "REF-998811",
        "description": "خرید فوری برای سفارش مشتری",
    }
    payload.update(overrides)
    return client.post("/api/v1/accounting/transactions", json=payload, headers=headers)


def _linked_transaction(db, invoice_id=None):
    """An auto-synced (invoice-linked) income row, as Task 4 will create it."""
    if invoice_id is None:
        invoice = CommerceInvoice(
            customer_name="مریم احمدی",
            mobile="09121112233",
            total_toman=800_000,
            state="paid",
        )
        db.add(invoice)
        db.commit()
        invoice_id = invoice.id

    txn = AccountingTransaction(
        title=f"فروش فاکتور #{invoice_id} - مریم احمدی",
        category_id=_income_category_id(db),
        type="income",
        amount_toman=800_000,
        transaction_date=date(2026, 10, 17),
        account_type="gateway",
        reference_code="TRK-123456",
        invoice_id=invoice_id,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


# ── Auth ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/accounting/categories"),
        ("post", "/api/v1/accounting/categories"),
        ("get", "/api/v1/accounting/transactions"),
        ("post", "/api/v1/accounting/transactions"),
        ("get", "/api/v1/accounting/summary"),
        ("get", "/api/v1/accounting/export"),
        ("post", "/api/v1/accounting/upload-attachment"),
        ("put", "/api/v1/accounting/categories/1"),
        ("delete", "/api/v1/accounting/categories/1"),
        ("put", "/api/v1/accounting/transactions/1"),
        ("delete", "/api/v1/accounting/transactions/1"),
    ],
)
def test_accounting_endpoints_require_authentication(client, method, path):
    kwargs = {"json": {}} if method in ("post", "put") else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code in (401, 403), (path, res.status_code, res.text)


def test_employee_staff_can_read_accounting(client, employee_headers, seeded):
    res = client.get("/api/v1/accounting/categories", headers=employee_headers)
    assert res.status_code == 200
    assert any(c["name"] == "فروش محصول و خدمات" for c in res.json())


# ── Categories ───────────────────────────────────────────────────────
def test_list_categories_returns_system_first_and_filters_by_type(client, auth_headers, seeded):
    res = client.get("/api/v1/accounting/categories", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 10
    assert any(c["name"] == "فروش محصول و خدمات" for c in data)
    # Active-only, and system rows sort ahead of custom ones.
    assert all(c["is_active"] is True for c in data)
    assert [c["is_system"] for c in data] == sorted(
        (c["is_system"] for c in data), reverse=True
    )

    res = client.get("/api/v1/accounting/categories?type=expense", headers=auth_headers)
    assert res.status_code == 200
    assert {c["type"] for c in res.json()} == {"expense"}
    assert len(res.json()) == 8

    res = client.get("/api/v1/accounting/categories?type=income", headers=auth_headers)
    assert {c["type"] for c in res.json()} == {"income"}


def test_create_custom_category_is_custom_active_and_unique(client, auth_headers, seeded):
    res = client.post(
        "/api/v1/accounting/categories",
        json={"name": "پذیرایی و قهوه کارگاه", "type": "expense"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "پذیرایی و قهوه کارگاه"
    assert body["type"] == "expense"
    assert body["is_system"] is False
    assert body["is_active"] is True
    assert isinstance(body["id"], int)

    # A second active (name, type) pair is rejected.
    dup = client.post(
        "/api/v1/accounting/categories",
        json={"name": "پذیرایی و قهوه کارگاه", "type": "expense"},
        headers=auth_headers,
    )
    assert dup.status_code == 400

    # The same name under the other type is a different «سرفصل» — allowed.
    other = client.post(
        "/api/v1/accounting/categories",
        json={"name": "پذیرایی و قهوه کارگاه", "type": "income"},
        headers=auth_headers,
    )
    assert other.status_code == 200

    # The new category shows up in the picker list, after the system rows.
    listed = client.get("/api/v1/accounting/categories?type=expense", headers=auth_headers).json()
    assert listed[-1]["name"] == "پذیرایی و قهوه کارگاه"
    assert listed[-1]["is_system"] is False


def test_create_category_rejects_invalid_type_and_blank_name(client, auth_headers, seeded):
    bad_type = client.post(
        "/api/v1/accounting/categories",
        json={"name": "سرفصل نامعتبر", "type": "revenue"},
        headers=auth_headers,
    )
    assert bad_type.status_code == 400

    blank = client.post(
        "/api/v1/accounting/categories",
        json={"name": "   ", "type": "expense"},
        headers=auth_headers,
    )
    assert blank.status_code == 400

    assert (
        client.post(
            "/api/v1/accounting/categories",
            json={"name": "سرفصل نامعتبر", "type": "revenue"},
            headers=auth_headers,
        ).status_code
        != 200
    )


def test_update_category_renames_custom_and_blocks_system(client, auth_headers, seeded):
    created = client.post(
        "/api/v1/accounting/categories",
        json={"name": "هزینه جانبی", "type": "expense"},
        headers=auth_headers,
    ).json()

    renamed = client.put(
        f"/api/v1/accounting/categories/{created['id']}",
        json={"name": "هزینه جانبی کارگاه"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "هزینه جانبی کارگاه"

    system_cat = next(
        c
        for c in client.get("/api/v1/accounting/categories", headers=auth_headers).json()
        if c["is_system"]
    )
    blocked = client.put(
        f"/api/v1/accounting/categories/{system_cat['id']}",
        json={"name": "نام جدید"},
        headers=auth_headers,
    )
    assert blocked.status_code == 400

    missing = client.put(
        "/api/v1/accounting/categories/999999",
        json={"name": "هرچیز"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


def test_update_category_blocks_type_change_once_transactions_exist(client, auth_headers, seeded, db):
    created = client.post(
        "/api/v1/accounting/categories",
        json={"name": "دسته قابل تبدیل", "type": "expense"},
        headers=auth_headers,
    ).json()

    # With no transactions the retype is allowed.
    retyped = client.put(
        f"/api/v1/accounting/categories/{created['id']}",
        json={"type": "income"},
        headers=auth_headers,
    )
    assert retyped.status_code == 200
    assert retyped.json()["type"] == "income"

    client.post(
        "/api/v1/accounting/transactions",
        json={
            "title": "درآمد آزمایشی",
            "category_id": created["id"],
            "type": "income",
            "amount_toman": 100_000,
            "transaction_date": "2026-10-17",
        },
        headers=auth_headers,
    )

    blocked = client.put(
        f"/api/v1/accounting/categories/{created['id']}",
        json={"type": "expense"},
        headers=auth_headers,
    )
    assert blocked.status_code == 400
    # …but the name may still be corrected.
    assert (
        client.put(
            f"/api/v1/accounting/categories/{created['id']}",
            json={"name": "دسته قابل تبدیل ۲"},
            headers=auth_headers,
        ).status_code
        == 200
    )


def test_delete_category_soft_deletes_custom_and_protects_system(client, auth_headers, seeded, db):
    created = client.post(
        "/api/v1/accounting/categories",
        json={"name": "سرفصل بایگانی", "type": "expense"},
        headers=auth_headers,
    ).json()

    res = client.delete(
        f"/api/v1/accounting/categories/{created['id']}", headers=auth_headers
    )
    assert res.status_code == 200

    # Soft delete: the row survives, the picker loses it.
    row = db.query(AccountingCategory).filter(AccountingCategory.id == created["id"]).one()
    assert row.is_active is False
    listed_ids = [
        c["id"]
        for c in client.get("/api/v1/accounting/categories", headers=auth_headers).json()
    ]
    assert created["id"] not in listed_ids

    system_cat = (
        db.query(AccountingCategory)
        .filter(AccountingCategory.is_system == True)  # noqa: E712
        .order_by(AccountingCategory.id)
        .first()
    )
    blocked = client.delete(
        f"/api/v1/accounting/categories/{system_cat.id}", headers=auth_headers
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == SYSTEM_DELETE_DETAIL
    db.refresh(system_cat)
    assert system_cat.is_active is True


# ── Transactions ─────────────────────────────────────────────────────
def test_create_manual_transaction_and_serialization(client, auth_headers, seeded, db):
    cat_id = _expense_category_id(db)
    res = _post_txn(client, auth_headers, category_id=cat_id)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["id"]
    assert body["title"] == "خرید رول PLA مشکی"
    assert body["type"] == "expense"
    assert body["amount_toman"] == 450_000
    assert body["transaction_date"] == "2026-10-17"
    assert body["account_type"] == "bank"
    assert body["reference_code"] == "REF-998811"
    assert body["description"] == "خرید فوری برای سفارش مشتری"
    assert body["category_id"] == cat_id
    assert body["category_name"] == "خرید فیلامنت و متریال"
    assert body["category_type"] == "expense"
    assert body["invoice_id"] is None
    assert body["order_id"] is None
    assert body["is_invoice_linked"] is False
    assert body["attachment_url"] is None
    assert body["created_at"]
    assert body["updated_at"]
    # The creator is stamped from the authenticated session, not the payload.
    assert body["created_by_user_id"] is not None


def test_create_transaction_validation_rules(client, auth_headers, seeded, db):
    expense_id = _expense_category_id(db)
    income_id = _income_category_id(db)

    # type must match the category type
    mismatch = _post_txn(client, auth_headers, category_id=income_id, type="expense")
    assert mismatch.status_code == 400

    # amount must be positive
    for amount in (0, -1):
        res = _post_txn(client, auth_headers, category_id=expense_id, amount_toman=amount)
        assert res.status_code == 400

    # title must not be blank
    blank = _post_txn(client, auth_headers, category_id=expense_id, title="   ")
    assert blank.status_code == 400

    # category must exist and be active
    missing = _post_txn(client, auth_headers, category_id=999999)
    assert missing.status_code == 400

    archived = client.post(
        "/api/v1/accounting/categories",
        json={"name": "سرفصل آرشیوی", "type": "expense"},
        headers=auth_headers,
    ).json()
    client.delete(f"/api/v1/accounting/categories/{archived['id']}", headers=auth_headers)
    inactive = _post_txn(client, auth_headers, category_id=archived["id"])
    assert inactive.status_code == 400

    # account_type is a closed set
    bad_account = _post_txn(client, auth_headers, category_id=expense_id, account_type="crypto")
    assert bad_account.status_code == 400

    # A valid income row is accepted.
    ok = _post_txn(client, auth_headers, category_id=income_id, type="income", account_type="gateway")
    assert ok.status_code == 200, ok.text

    assert db.query(AccountingTransaction).count() == 1


def test_list_transactions_filters_search_and_pagination(client, auth_headers, seeded, db):
    expense_id = _expense_category_id(db)
    income_id = _income_category_id(db)

    rows = [
        ("خرید فیلامنت PLA", expense_id, "expense", 1_000_000, "2026-09-05", "bank"),
        ("خرید نازل برنجی", expense_id, "expense", 2_000_000, "2026-10-17", "cash"),
        ("فروش مجسمه", income_id, "income", 5_000_000, "2026-10-18", "gateway"),
    ]
    for title, cat, ttype, amount, when, account in rows:
        res = _post_txn(
            client,
            auth_headers,
            title=title,
            category_id=cat,
            type=ttype,
            amount_toman=amount,
            transaction_date=when,
            account_type=account,
        )
        assert res.status_code == 200, res.text

    # Unfiltered page
    res = client.get("/api/v1/accounting/transactions", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_count"] == 3
    assert body["has_more"] is False
    assert len(body["items"]) == 3
    assert [i["category_name"] for i in body["items"]]

    # Pagination window + has_more
    first_page = client.get(
        "/api/v1/accounting/transactions?limit=2&offset=0", headers=auth_headers
    ).json()
    assert len(first_page["items"]) == 2
    assert first_page["total_count"] == 3
    assert first_page["has_more"] is True

    second_page = client.get(
        "/api/v1/accounting/transactions?limit=2&offset=2", headers=auth_headers
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["has_more"] is False
    assert {i["id"] for i in first_page["items"]} & {
        i["id"] for i in second_page["items"]
    } == set()

    # type filter
    assert client.get(
        "/api/v1/accounting/transactions?type=income", headers=auth_headers
    ).json()["total_count"] == 1

    # category filter
    assert client.get(
        f"/api/v1/accounting/transactions?category_id={expense_id}", headers=auth_headers
    ).json()["total_count"] == 2

    # account_type filter
    assert client.get(
        "/api/v1/accounting/transactions?account_type=cash", headers=auth_headers
    ).json()["total_count"] == 1

    # inclusive Gregorian date range
    ranged = client.get(
        "/api/v1/accounting/transactions?start_date=2026-10-01&end_date=2026-10-31",
        headers=auth_headers,
    ).json()
    assert ranged["total_count"] == 2

    # search spans title / reference_code / description
    assert client.get(
        "/api/v1/accounting/transactions?search=نازل", headers=auth_headers
    ).json()["total_count"] == 1
    assert client.get(
        "/api/v1/accounting/transactions?search=REF-99", headers=auth_headers
    ).json()["total_count"] == 3
    assert client.get(
        "/api/v1/accounting/transactions?search=فوری", headers=auth_headers
    ).json()["total_count"] == 3
    assert client.get(
        "/api/v1/accounting/transactions?search=ناموجود", headers=auth_headers
    ).json()["total_count"] == 0

    # bound checks
    assert client.get(
        "/api/v1/accounting/transactions?limit=500", headers=auth_headers
    ).status_code == 422
    assert client.get(
        "/api/v1/accounting/transactions?limit=0", headers=auth_headers
    ).status_code == 422
    assert client.get(
        "/api/v1/accounting/transactions?start_date=not-a-date", headers=auth_headers
    ).status_code == 422


def test_update_manual_transaction_and_validation(client, auth_headers, seeded, db):
    expense_id = _expense_category_id(db)
    income_id = _income_category_id(db)
    created = _post_txn(client, auth_headers, category_id=expense_id).json()

    res = client.put(
        f"/api/v1/accounting/transactions/{created['id']}",
        json={
            "title": "خرید رول PLA سفید",
            "amount_toman": 500_000,
            "transaction_date": "2026-10-20",
            "description": "ویرایش شده",
            "account_type": "cash",
            "reference_code": "REF-000001",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "خرید رول PLA سفید"
    assert body["amount_toman"] == 500_000
    assert body["transaction_date"] == "2026-10-20"
    assert body["description"] == "ویرایش شده"
    assert body["account_type"] == "cash"
    assert body["reference_code"] == "REF-000001"
    assert body["type"] == "expense"

    # Type/category mismatch and non-positive amount stay rejected.
    assert (
        client.put(
            f"/api/v1/accounting/transactions/{created['id']}",
            json={"category_id": income_id},
            headers=auth_headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/api/v1/accounting/transactions/{created['id']}",
            json={"amount_toman": 0},
            headers=auth_headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/api/v1/accounting/transactions/{created['id']}",
            json={"type": "revenue"},
            headers=auth_headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/v1/accounting/transactions/999999", json={"title": "x"}, headers=auth_headers
        ).status_code
        == 404
    )

    # A manual row is hard-deleted.
    deleted = client.delete(
        f"/api/v1/accounting/transactions/{created['id']}", headers=auth_headers
    )
    assert deleted.status_code == 200
    assert db.query(AccountingTransaction).filter(
        AccountingTransaction.id == created["id"]
    ).first() is None
    assert client.delete(
        f"/api/v1/accounting/transactions/{created['id']}", headers=auth_headers
    ).status_code == 404


def test_invoice_linked_transaction_guardrails(client, auth_headers, seeded, db):
    txn = _linked_transaction(db)
    income_id = _income_category_id(db)

    # Frozen: amount, type and date may not change.
    for payload in (
        {"amount_toman": 1},
        {"type": "expense"},
        {"transaction_date": "2026-01-01"},
    ):
        res = client.put(
            f"/api/v1/accounting/transactions/{txn.id}", json=payload, headers=auth_headers
        )
        assert res.status_code == 400, (payload, res.text)

    # Identical values are a harmless no-op, not a modification.
    same = client.put(
        f"/api/v1/accounting/transactions/{txn.id}",
        json={"amount_toman": 800_000, "type": "income", "transaction_date": "2026-10-17"},
        headers=auth_headers,
    )
    assert same.status_code == 200, same.text

    # Allowed: description, reference_code, attachment_url.
    allowed = client.put(
        f"/api/v1/accounting/transactions/{txn.id}",
        json={
            "description": "توضیح حسابداری",
            "reference_code": "TRK-NEW-1",
            "attachment_url": "/uploads/accounting/x.png",
        },
        headers=auth_headers,
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["description"] == "توضیح حسابداری"
    assert allowed.json()["reference_code"] == "TRK-NEW-1"
    assert allowed.json()["attachment_url"] == "/uploads/accounting/x.png"

    # category_id must stay an income category.
    expense_id = _expense_category_id(db)
    assert (
        client.put(
            f"/api/v1/accounting/transactions/{txn.id}",
            json={"category_id": expense_id},
            headers=auth_headers,
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/api/v1/accounting/transactions/{txn.id}",
            json={"category_id": income_id},
            headers=auth_headers,
        ).status_code
        == 200
    )

    # invoice_id is not writable through the API: even a payload that echoes it
    # back leaves the link untouched.
    echoed = client.put(
        f"/api/v1/accounting/transactions/{txn.id}",
        json={"invoice_id": 999999},
        headers=auth_headers,
    )
    assert echoed.status_code in (200, 422)
    db.refresh(txn)
    assert txn.invoice_id != 999999

    # Deletion is refused, with the exact Persian detail.
    blocked = client.delete(
        f"/api/v1/accounting/transactions/{txn.id}", headers=auth_headers
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == INVOICE_DELETE_DETAIL
    assert db.query(AccountingTransaction).filter(
        AccountingTransaction.id == txn.id
    ).first() is not None


# ── Summary ──────────────────────────────────────────────────────────
def test_summary_totals_margin_and_bigint(client, auth_headers, seeded, db):
    income_id = _income_category_id(db)
    expense_id = _expense_category_id(db)
    big_income = 12_345_678_901  # > 2**31 - 1
    big_expense = 2_500_000_000

    for title, cat, ttype, amount, when in (
        ("فروش عمده", income_id, "income", big_income, "2026-10-01"),
        ("فروش دوم", income_id, "income", 1_000_000_000, "2026-10-02"),
        ("خرید متریال", expense_id, "expense", big_expense, "2026-10-03"),
    ):
        assert _post_txn(
            client,
            auth_headers,
            title=title,
            category_id=cat,
            type=ttype,
            amount_toman=amount,
            transaction_date=when,
        ).status_code == 200

    res = client.get(
        "/api/v1/accounting/summary?start_date=2026-10-01&end_date=2026-10-31",
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    total_income = big_income + 1_000_000_000
    total_expense = big_expense
    assert body["total_income"] == total_income
    assert body["total_expense"] == total_expense
    assert body["net_profit"] == total_income - total_expense
    expected_margin = round((total_income - total_expense) / total_income * 100, 2)
    assert body["profit_margin_pct"] == expected_margin
    assert body["transaction_count"] == 3

    # Empty range: zeroed, no division by zero.
    empty = client.get(
        "/api/v1/accounting/summary?start_date=2020-01-01&end_date=2020-01-31",
        headers=auth_headers,
    ).json()
    assert empty["total_income"] == 0
    assert empty["total_expense"] == 0
    assert empty["net_profit"] == 0
    assert empty["profit_margin_pct"] == 0.0
    assert empty["by_category"] == []
    assert empty["by_month"] == []


def test_summary_by_category_and_by_month(client, auth_headers, seeded, db):
    income_id = _income_category_id(db)
    expense_id = _expense_category_id(db)

    for title, cat, ttype, amount, when in (
        ("فروش مهر", income_id, "income", 3_000_000, "2026-10-05"),
        ("فروش مهر ۲", income_id, "income", 1_000_000, "2026-10-20"),
        ("خرید مهر", expense_id, "expense", 500_000, "2026-10-06"),
        ("فروش شهریور", income_id, "income", 2_000_000, "2026-09-10"),
        ("خرید شهریور", expense_id, "expense", 700_000, "2026-09-11"),
    ):
        assert _post_txn(
            client,
            auth_headers,
            title=title,
            category_id=cat,
            type=ttype,
            amount_toman=amount,
            transaction_date=when,
        ).status_code == 200

    body = client.get(
        "/api/v1/accounting/summary?start_date=2026-09-01&end_date=2026-10-31",
        headers=auth_headers,
    ).json()

    by_category = {c["category_id"]: c for c in body["by_category"]}
    assert by_category[income_id]["total_toman"] == 6_000_000
    assert by_category[income_id]["count"] == 3
    assert by_category[income_id]["type"] == "income"
    assert by_category[income_id]["name"] == "فروش محصول و خدمات"
    assert by_category[expense_id]["total_toman"] == 1_200_000
    assert by_category[expense_id]["count"] == 2
    # Largest line first — the breakdown drives a chart.
    assert body["by_category"][0]["category_id"] == income_id

    # Monthly buckets are Shamsi (مهر ۱۴۰۵ = Oct 2026, شهریور ۱۴۰۵ = Sep 2026).
    assert [m["label"] for m in body["by_month"]] == ["1405/06", "1405/07"]
    mehr, shahrivar = body["by_month"][1], body["by_month"][0]
    assert (shahrivar["year"], shahrivar["month"]) == (1405, 6)
    assert (mehr["year"], mehr["month"]) == (1405, 7)
    assert mehr["income"] == 4_000_000
    assert mehr["expense"] == 500_000
    assert mehr["net_profit"] == 3_500_000
    assert shahrivar["income"] == 2_000_000
    assert shahrivar["expense"] == 700_000
    assert shahrivar["net_profit"] == 1_300_000

    # The range narrows the summary (October only).
    october = client.get(
        "/api/v1/accounting/summary?start_date=2026-10-01&end_date=2026-10-31",
        headers=auth_headers,
    ).json()
    assert october["total_income"] == 4_000_000
    assert [m["label"] for m in october["by_month"]] == ["1405/07"]
    assert october["transaction_count"] == 3


# ── Export ───────────────────────────────────────────────────────────
def _export_rows(resp):
    text = resp.content.decode("utf-8")
    assert text.startswith("\ufeff")
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


def test_export_csv_has_bom_persian_columns_and_shamsi_dates(client, auth_headers, seeded, db):
    income_id = _income_category_id(db)
    expense_id = _expense_category_id(db)
    # 2026-10-17 → 1405/07/25, 2026-03-21 → 1405/01/01
    assert _post_txn(
        client,
        auth_headers,
        title="خرید رول PLA",
        category_id=expense_id,
        amount_toman=450_000,
        transaction_date="2026-10-17",
        account_type="cash",
        reference_code="REF-1",
        description="توضیح",
    ).status_code == 200
    assert _post_txn(
        client,
        auth_headers,
        title="فروش نوروزی",
        category_id=income_id,
        type="income",
        amount_toman=1_500_000,
        transaction_date="2026-03-21",
        account_type="gateway",
        reference_code="TRK-2",
        description="",
    ).status_code == 200

    res = client.get("/api/v1/accounting/export", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == (
        "attachment; filename=accounting_transactions.csv"
    )

    rows = _export_rows(res)
    assert rows[0] == CSV_HEADER
    assert len(rows) == 3

    by_title = {r[2]: r for r in rows[1:]}
    expense = by_title["خرید رول PLA"]
    assert expense[1] == "1405/07/25"
    assert expense[3] == "خرید فیلامنت و متریال"
    assert expense[4] == "هزینه"
    assert expense[5] == "450000"
    assert expense[6] == "صندوق"
    assert expense[7] == "REF-1"
    assert expense[8] == ""
    assert expense[9] == "توضیح"

    income = by_title["فروش نوروزی"]
    assert income[1] == "1405/01/01"
    assert income[3] == "فروش محصول و خدمات"
    assert income[4] == "درآمد"
    assert income[5] == "1500000"
    assert income[6] == "درگاه"
    assert income[8] == ""


def test_export_respects_filters_and_produces_valid_csv(client, auth_headers, seeded, db):
    income_id = _income_category_id(db)
    expense_id = _expense_category_id(db)
    for title, cat, ttype, amount, when, ref in (
        ("هزینه سپتامبر", expense_id, "expense", 100_000, "2026-09-05", "SEP-1"),
        ("هزینه اکتبر", expense_id, "expense", 200_000, "2026-10-05", "OCT-1"),
        ("فروش اکتبر", income_id, "income", 300_000, "2026-10-06", "OCT-2"),
    ):
        assert _post_txn(
            client,
            auth_headers,
            title=title,
            category_id=cat,
            type=ttype,
            amount_toman=amount,
            transaction_date=when,
            reference_code=ref,
        ).status_code == 200

    ranged = _export_rows(
        client.get(
            "/api/v1/accounting/export?start_date=2026-10-01&end_date=2026-10-31",
            headers=auth_headers,
        )
    )
    assert {r[2] for r in ranged[1:]} == {"هزینه اکتبر", "فروش اکتبر"}

    typed = _export_rows(
        client.get("/api/v1/accounting/export?type=income", headers=auth_headers)
    )
    assert {r[2] for r in typed[1:]} == {"فروش اکتبر"}

    searched = _export_rows(
        client.get("/api/v1/accounting/export?search=OCT-", headers=auth_headers)
    )
    assert {r[2] for r in searched[1:]} == {"هزینه اکتبر", "فروش اکتبر"}

    assert _export_rows(client.get("/api/v1/accounting/export?search=نیست", headers=auth_headers)) == [
        CSV_HEADER
    ]


# ── Attachment upload ────────────────────────────────────────────────
def test_upload_attachment_stores_file_and_returns_served_url(
    client, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(accounting_service, "ACCOUNTING_UPLOAD_DIR", str(tmp_path))

    payload = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    res = client.post(
        "/api/v1/accounting/upload-attachment",
        files={"file": ("رسید خرید.png", payload, "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    url = res.json()["attachment_url"]
    assert url.startswith("/uploads/accounting/")
    assert url.endswith(".png")
    assert len(os.listdir(tmp_path)) == 1
    stored = os.path.join(str(tmp_path), url.rsplit("/", 1)[-1])
    with open(stored, "rb") as fh:
        assert fh.read() == payload


def test_upload_attachment_rejects_extension_and_oversize(
    client, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(accounting_service, "ACCOUNTING_UPLOAD_DIR", str(tmp_path))

    bad_ext = client.post(
        "/api/v1/accounting/upload-attachment",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        headers=auth_headers,
    )
    assert bad_ext.status_code == 400
    assert os.listdir(tmp_path) == []

    oversize = client.post(
        "/api/v1/accounting/upload-attachment",
        files={"file": ("big.pdf", b"0" * (5 * 1024 * 1024 + 1), "application/pdf")},
        headers=auth_headers,
    )
    assert oversize.status_code == 413
    assert os.listdir(tmp_path) == []

    # A path-traversal attempt cannot escape the accounting folder.
    sneaky = client.post(
        "/api/v1/accounting/upload-attachment",
        files={"file": ("../../evil.png", payload_png(), "image/png")},
        headers=auth_headers,
    )
    assert sneaky.status_code == 200
    assert sneaky.json()["attachment_url"].startswith("/uploads/accounting/")
    assert ".." not in sneaky.json()["attachment_url"]
    assert len(os.listdir(tmp_path)) == 1


def payload_png():
    return b"\x89PNG\r\n\x1a\n" + b"0" * 8


def test_uploaded_attachment_is_served_at_the_returned_url(client, auth_headers):
    """The URL handed to the client must resolve through the ``/uploads`` mount.

    The upload route always reports ``/uploads/accounting/<file>``; if that path
    did not match where ``app.main`` mounts ``StaticFiles``, every receipt link
    in the ledger would 404. This writes one real file into the live upload
    directory and removes it again.
    """
    payload = payload_png() + b"served"
    res = client.post(
        "/api/v1/accounting/upload-attachment",
        files={"file": ("receipt.png", payload, "image/png")},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    url = res.json()["attachment_url"]
    assert url.startswith(accounting_service.ATTACHMENT_URL_PREFIX + "/")

    stored = os.path.join(
        accounting_service.UPLOAD_ROOT, url[len("/uploads/"):].replace("/", os.sep)
    )
    try:
        served = client.get(url)
        assert served.status_code == 200, served.text
        assert served.content == payload
    finally:
        if os.path.exists(stored):
            os.remove(stored)
            if not os.listdir(os.path.dirname(stored)):
                os.rmdir(os.path.dirname(stored))
