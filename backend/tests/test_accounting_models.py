"""Task 1 — accounting models, chart-of-accounts seed and startup migration.

Covers the DB-level guarantees the accounting module (and the invoice→income
auto-sync that builds on it) depends on:

* ``accounting_categories`` / ``accounting_transactions`` exist with the exact
  columns, foreign keys (incl. ``ondelete`` semantics) and the UNIQUE index on
  ``invoice_id`` that makes the invoice sync idempotent;
* soft deletion (``is_active=False``) archives a category without losing its
  transactions, and the startup seed never resurrects or duplicates a row;
* the startup migration creates both tables on a database that predates the
  accounting module and seeds the default «سرفصل»s exactly once.

Everything runs against a throwaway SQLite file per test, so the shared
``tests/test.db`` fixture database and the real app database are untouched.
"""
import pytest
from datetime import date
from sqlalchemy import BigInteger, create_engine, func, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import ensure_accounting_schema_and_seed
from app.models import (
    ACCOUNTING_TYPES,
    DEFAULT_EXPENSE_CATEGORY_NAMES,
    DEFAULT_INCOME_CATEGORY_NAMES,
    SYSTEM_SALES_INCOME_CATEGORY_NAME,
    AccountingCategory,
    AccountingTransaction,
    CommerceInvoice,
    Order,
    User,
    seed_accounting_categories,
)

# ── Expected seed names, spelled with an explicit ZWNJ (\u200c) so the two
# نیمفاصله-bearing names can never be "fixed" into a different string.
ZWNJ = "\u200c"

EXPECTED_EXPENSE_NAMES = [
    "خرید فیلامنت و متریال",
    "قطعات یدکی و نگهداری پرینتر",
    f"بسته{ZWNJ}بندی و کارتن",
    "هزینه ارسال و پست",
    "هزینه اشتراک و اینترنت",
    "برق کارگاه",
    "تبلیغات و مارکتینگ",
    f"سایر هزینه{ZWNJ}ها",
]

EXPECTED_INCOME_NAMES = [
    "فروش محصول و خدمات",
    "سایر درآمدها",
]

EXPECTED_TOTAL_SEEDS = len(EXPECTED_EXPENSE_NAMES) + len(EXPECTED_INCOME_NAMES)


# ── Fixtures ─────────────────────────────────────────────────────────
def _make_engine(db_path):
    """A dedicated file-backed SQLite engine (SQLite-safe for cross-conn reads)."""
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    return engine


@pytest.fixture()
def db_session(tmp_path):
    """Fresh accounting-capable database and session, isolated per test."""
    engine = _make_engine(tmp_path / "accounting.db")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _expense_category(db, name="خرید فیلامنت و متریال"):
    cat = AccountingCategory(name=name, type="expense", is_system=True)
    db.add(cat)
    db.commit()
    return cat


def _income_category(db, name=SYSTEM_SALES_INCOME_CATEGORY_NAME):
    cat = AccountingCategory(name=name, type="income", is_system=True)
    db.add(cat)
    db.commit()
    return cat


def _transaction(**overrides):
    """An accounting transaction with all required fields filled in."""
    data = {
        "title": "هزینه نمونه",
        "type": "expense",
        "amount_toman": 1_000_000,
        "transaction_date": date(2026, 10, 17),
    }
    data.update(overrides)
    return AccountingTransaction(**data)


# ── Schema contract ──────────────────────────────────────────────────
def test_accounting_tables_have_the_expected_columns_and_foreign_keys(db_session):
    inspector = inspect(db_session.get_bind())
    tables = set(inspector.get_table_names())
    assert {"accounting_categories", "accounting_transactions"} <= tables

    cat_cols = {c["name"]: c for c in inspector.get_columns("accounting_categories")}
    assert set(cat_cols) == {"id", "name", "type", "is_system", "is_active", "created_at"}
    assert cat_cols["name"]["nullable"] is False
    assert cat_cols["type"]["nullable"] is False
    assert cat_cols["is_system"]["nullable"] is False
    assert cat_cols["is_active"]["nullable"] is False

    txn_cols = {c["name"]: c for c in inspector.get_columns("accounting_transactions")}
    assert set(txn_cols) == {
        "id",
        "title",
        "category_id",
        "type",
        "amount_toman",
        "transaction_date",
        "account_type",
        "reference_code",
        "description",
        "attachment_url",
        "invoice_id",
        "order_id",
        "created_by_user_id",
        "created_at",
        "updated_at",
    }
    # NOT NULL columns
    for required in (
        "title",
        "category_id",
        "type",
        "amount_toman",
        "transaction_date",
        "account_type",
    ):
        assert txn_cols[required]["nullable"] is False, required
    # Optional links / free text
    for optional in (
        "reference_code",
        "description",
        "attachment_url",
        "invoice_id",
        "order_id",
        "created_by_user_id",
        "created_at",
        "updated_at",
    ):
        assert txn_cols[optional]["nullable"] is True, optional

    # amount_toman must be BIGINT so SUM() over the ledger cannot overflow 32-bit.
    assert isinstance(txn_cols["amount_toman"]["type"], BigInteger)

    fks = {
        fk["constrained_columns"][0]: (
            fk["referred_table"],
            (fk["options"] or {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys("accounting_transactions")
    }
    assert fks["category_id"] == ("accounting_categories", "RESTRICT")
    assert fks["invoice_id"] == ("commerce_invoices", "SET NULL")
    assert fks["order_id"] == ("orders", "SET NULL")
    assert fks["created_by_user_id"] == ("users", "SET NULL")

    # invoice_id is UNIQUE at the database level: the invoice→income sync is
    # idempotent even if the application check is bypassed.
    unique_invoice_indexes = [
        idx
        for idx in inspector.get_indexes("accounting_transactions")
        if idx["column_names"] == ["invoice_id"] and idx["unique"]
    ]
    assert unique_invoice_indexes, inspector.get_indexes("accounting_transactions")


# ── AccountingCategory ───────────────────────────────────────────────
def test_accounting_category_creation_and_defaults(db_session):
    cat = AccountingCategory(
        name="خرید فیلامنت و متریال",
        type="expense",
        is_system=True,
        is_active=True,
    )
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    assert cat.id is not None
    assert cat.name == "خرید فیلامنت و متریال"
    assert cat.type == "expense"
    assert cat.is_system is True
    assert cat.is_active is True
    assert cat.created_at is not None


def test_accounting_category_defaults_are_custom_and_active(db_session):
    """A category created without flags is custom and active, per the brief."""
    cat = AccountingCategory(name="هزینه جانبی کارگاه", type="expense")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    assert cat.is_system is False
    assert cat.is_active is True


def test_accounting_category_soft_delete_keeps_row_and_transactions(db_session):
    cat = _expense_category(db_session)
    db_session.add(_transaction(category_id=cat.id, amount_toman=2_500_000))
    db_session.commit()

    # Soft delete == archive, not DELETE.
    cat.is_active = False
    db_session.commit()
    db_session.refresh(cat)

    assert cat.is_active is False
    assert cat.is_system is True
    assert db_session.query(AccountingCategory).count() == 1
    assert db_session.query(AccountingTransaction).count() == 1

    # Archived categories disappear from pickers but keep their history.
    active_names = [
        c.name
        for c in db_session.query(AccountingCategory)
        .filter(AccountingCategory.is_active.is_(True))
        .all()
    ]
    assert active_names == []


# ── AccountingTransaction ────────────────────────────────────────────
def test_accounting_transaction_creation_defaults_and_category_relationship(db_session):
    cat = _expense_category(db_session)

    txn = AccountingTransaction(
        title="خرید ۲ کیلو فیلامنت PLA",
        category_id=cat.id,
        type="expense",
        amount_toman=5_200_000,
        transaction_date=date(2026, 10, 17),
    )
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)

    assert txn.id is not None
    assert txn.transaction_date == date(2026, 10, 17)
    # Defaults from the brief
    assert txn.account_type == "bank"
    assert txn.reference_code == ""
    assert txn.description == ""
    # Nullable links stay empty for a manual expense
    assert txn.attachment_url is None
    assert txn.invoice_id is None
    assert txn.order_id is None
    assert txn.created_by_user_id is None
    assert txn.created_at is not None
    assert txn.updated_at is not None

    # Relationship to the category
    assert txn.category.id == cat.id
    assert txn.category.name == "خرید فیلامنت و متریال"
    assert txn.category.type == "expense"


def test_accounting_transaction_amount_toman_round_trips_and_sums_beyond_int32(db_session):
    cat = _income_category(db_session)
    huge = 12_345_678_901  # > 2**31 - 1 (SQLite/32-bit INTEGER would overflow)
    db_session.add_all(
        [
            _transaction(
                title="فروش عمده",
                category_id=cat.id,
                type="income",
                amount_toman=huge,
                account_type="gateway",
            ),
            _transaction(
                title="فروش دوم",
                category_id=cat.id,
                type="income",
                amount_toman=3_000_000_000,
            ),
        ]
    )
    db_session.commit()

    stored = db_session.query(AccountingTransaction).filter(
        AccountingTransaction.amount_toman == huge
    ).one()
    assert stored.amount_toman == huge
    assert isinstance(stored.amount_toman, int)

    total = db_session.query(func.sum(AccountingTransaction.amount_toman)).scalar()
    assert total == huge + 3_000_000_000


def test_accounting_transaction_links_invoice_order_and_creator(db_session):
    cat = _income_category(db_session)
    user = User(
        username="accountant",
        password_hash="x",
        display_name="حسابدار",
        role="employee",
    )
    order = Order(customer_name="مریم احمدی", product_label="جعبه هدیه", quoted_price=800_000)
    invoice = CommerceInvoice(
        customer_name="مریم احمدی",
        mobile="09121112233",
        total_toman=800_000,
        state="paid",
    )
    db_session.add_all([user, order, invoice])
    db_session.commit()

    txn = AccountingTransaction(
        title=f"فروش فاکتور #{invoice.id} - {invoice.customer_name}",
        category_id=cat.id,
        type="income",
        amount_toman=invoice.total_toman,
        transaction_date=date(2026, 10, 17),
        account_type="gateway",
        reference_code="TRK-123456",
        description="پرداخت آنلاین درگاه دیجی‌پی",
        attachment_url="/uploads/accounting/receipt-1.jpg",
        invoice_id=invoice.id,
        order_id=order.id,
        created_by_user_id=user.id,
    )
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)

    assert txn.invoice.id == invoice.id
    assert txn.invoice.total_toman == 800_000
    assert txn.order.id == order.id
    assert txn.created_by_user_id == user.id
    assert txn.account_type == "gateway"
    assert txn.reference_code == "TRK-123456"
    assert txn.attachment_url == "/uploads/accounting/receipt-1.jpg"


def test_accounting_transaction_invoice_link_is_unique(db_session):
    """Two transactions can never share an ``invoice_id`` (idempotent sync)."""
    cat = _income_category(db_session)
    invoice = CommerceInvoice(customer_name="علی رضایی", mobile="09121112233", total_toman=500_000)
    db_session.add(invoice)
    db_session.commit()

    first = _transaction(
        title="فروش فاکتور ۱",
        category_id=cat.id,
        type="income",
        amount_toman=500_000,
        invoice_id=invoice.id,
    )
    db_session.add(first)
    db_session.commit()
    assert first.id is not None

    duplicate = _transaction(
        title="فروش فاکتور ۱ تکراری",
        category_id=cat.id,
        type="income",
        amount_toman=500_000,
        invoice_id=invoice.id,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    rows = (
        db_session.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "فروش فاکتور ۱"


def test_accounting_transaction_allows_many_rows_without_invoice(db_session):
    """Manual expenses are free of the unique link: only one NULL each."""
    cat = _expense_category(db_session)
    for i in range(3):
        db_session.add(
            _transaction(
                title=f"هزینه دستی {i}",
                category_id=cat.id,
                amount_toman=100_000 + i,
                invoice_id=None,
            )
        )
    db_session.commit()

    assert db_session.query(AccountingTransaction).count() == 3
    assert (
        db_session.query(AccountingTransaction.invoice_id).distinct().all() == [(None,)]
    )


# ── Chart-of-accounts seed ───────────────────────────────────────────
def test_seed_accounting_categories_creates_the_default_chart_of_accounts(db_session):
    # The seeded names are the brief's, verbatim (نیمفاصله included).
    assert DEFAULT_EXPENSE_CATEGORY_NAMES == tuple(EXPECTED_EXPENSE_NAMES)
    assert DEFAULT_INCOME_CATEGORY_NAMES == tuple(EXPECTED_INCOME_NAMES)
    assert SYSTEM_SALES_INCOME_CATEGORY_NAME == EXPECTED_INCOME_NAMES[0]
    assert set(ACCOUNTING_TYPES) == {"income", "expense"}

    assert seed_accounting_categories(db_session) == EXPECTED_TOTAL_SEEDS

    rows = db_session.query(AccountingCategory).order_by(AccountingCategory.id).all()
    assert len(rows) == EXPECTED_TOTAL_SEEDS

    assert [r.name for r in rows if r.type == "expense"] == EXPECTED_EXPENSE_NAMES
    assert [r.name for r in rows if r.type == "income"] == EXPECTED_INCOME_NAMES
    assert {r.type for r in rows} <= set(ACCOUNTING_TYPES)
    assert all(r.is_system is True for r in rows)
    assert all(r.is_active is True for r in rows)
    assert all(r.created_at is not None for r in rows)


def test_seed_accounting_categories_is_idempotent(db_session):
    first = seed_accounting_categories(db_session)
    second = seed_accounting_categories(db_session)
    third = seed_accounting_categories(db_session)

    assert first == EXPECTED_TOTAL_SEEDS
    assert second == 0
    assert third == 0
    assert db_session.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS


def test_seed_accounting_categories_does_not_resurrect_an_archived_category(db_session):
    seed_accounting_categories(db_session)
    archived = (
        db_session.query(AccountingCategory)
        .filter(AccountingCategory.name == EXPECTED_EXPENSE_NAMES[-1])
        .one()
    )
    archived.is_active = False
    db_session.commit()

    assert seed_accounting_categories(db_session) == 0

    db_session.refresh(archived)
    assert archived.is_active is False
    assert (
        db_session.query(AccountingCategory)
        .filter(AccountingCategory.name == EXPECTED_EXPENSE_NAMES[-1])
        .count()
        == 1
    )
    assert db_session.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS


def test_seed_accounting_categories_restores_a_missing_system_category(db_session):
    seed_accounting_categories(db_session)
    missing_name = "برق کارگاه"
    db_session.delete(
        db_session.query(AccountingCategory)
        .filter(AccountingCategory.name == missing_name)
        .one()
    )
    db_session.commit()
    assert db_session.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS - 1

    assert seed_accounting_categories(db_session) == 1

    restored = (
        db_session.query(AccountingCategory)
        .filter(AccountingCategory.name == missing_name)
        .one()
    )
    assert restored.type == "expense"
    assert restored.is_system is True
    assert restored.is_active is True
    assert db_session.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS


def test_seed_does_not_duplicate_an_existing_same_name_and_type(db_session):
    """A pre-existing row satisfies the seed — no second visible «سرفصل»."""
    db_session.add(AccountingCategory(name="برق کارگاه", type="expense", is_system=False))
    db_session.commit()

    assert seed_accounting_categories(db_session) == EXPECTED_TOTAL_SEEDS - 1

    rows = (
        db_session.query(AccountingCategory)
        .filter(AccountingCategory.name == "برق کارگاه")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].is_system is False
    assert db_session.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS


# ── Startup migration ────────────────────────────────────────────────
def test_ensure_accounting_schema_and_seed_on_a_pre_accounting_database(tmp_path):
    """A deployed DB predating this module gets the tables + seeds, once."""
    engine = _make_engine(tmp_path / "legacy.db")
    Base.metadata.create_all(bind=engine)
    # Simulate the deployed database: everything except the accounting tables.
    AccountingTransaction.__table__.drop(bind=engine)
    AccountingCategory.__table__.drop(bind=engine)
    assert "accounting_categories" not in inspect(engine).get_table_names()
    assert "accounting_transactions" not in inspect(engine).get_table_names()

    db = sessionmaker(bind=engine)()
    try:
        added = ensure_accounting_schema_and_seed(db, bind=engine)
        assert added == EXPECTED_TOTAL_SEEDS

        tables = set(inspect(engine).get_table_names())
        assert {"accounting_categories", "accounting_transactions"} <= tables
        assert db.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS

        # A ledger row can be booked straight after the migration ran.
        cat = db.query(AccountingCategory).filter(AccountingCategory.type == "income").first()
        db.add(
            _transaction(
                title="فروش بعد از مهاجرت",
                category_id=cat.id,
                type="income",
                amount_toman=9_000_000,
                transaction_date=date(2026, 10, 17),
            )
        )
        db.commit()
        assert db.query(AccountingTransaction).count() == 1

        # Second startup on the migrated database: no new tables, no new rows.
        assert ensure_accounting_schema_and_seed(db, bind=engine) == 0
        assert db.query(AccountingCategory).count() == EXPECTED_TOTAL_SEEDS
    finally:
        db.close()
        engine.dispose()
