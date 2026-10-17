"""Task 4 — admin manual payment + automatic invoice→accounting sync.

Covers the staff «ثبت پرداخت دستی» endpoint and the ledger booking that must
fire whenever an invoice becomes paid, through *both* doors:

* ``POST /api/v1/commerce/admin/invoices/{id}/manual-pay`` — card-to-card and
  cash payments recorded by staff: the invoice transition, the manual attempt
  row, the fulfillment order handed to the production queue, and the exact
  ledger row (``bank`` vs ``cash``) booked on the staff-supplied ``paid_at``;
* the online gateway settlement (``settle_verified_payment`` — the call the
  DigiPay callback makes once the provider genuinely confirms), whose ledger row
  is booked ``gateway`` on the current *Tehran* day and carries the provider's
  transaction id as its reference;
* idempotency: an invoice can never be double-booked — refused by the service
  guard *and* blocked by the accounting table's UNIQUE ``invoice_id``.

Assertions are on real rows read back from the database, not on response echoes.
"""
import importlib
import secrets
import sys
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    SYSTEM_SALES_INCOME_CATEGORY_NAME,
    AccountingCategory,
    AccountingTransaction,
    CommerceInvoice,
    CommercePaymentAttempt,
    Order,
    seed_accounting_categories,
)
from app.services import commerce as commerce_service

BASE = "/api/v1/commerce"
MANUAL_PAY = BASE + "/admin/invoices/{invoice_id}/manual-pay"
CALLBACK = f"{BASE}/digipay/callback"

# The seeded invoice used throughout: 2 × 150,000 + 12,000 shipping = 312,000
# Toman → 3,120,000 Rial, converted exactly once.
ITEM_TOTAL_TOMAN = 312_000
ITEM_TOTAL_RIAL = 3_120_000


# ── Fixtures / helpers ───────────────────────────────────────────────
def _test_session_local():
    """Session factory bound to the engine the API's ``get_db`` override uses."""
    try:
        return importlib.import_module("tests.conftest").TestSessionLocal
    except Exception:  # pragma: no cover — depends on pytest import mode
        pass
    for name, module in list(sys.modules.items()):
        if name.endswith("conftest") and hasattr(module, "TestSessionLocal"):
            return module.TestSessionLocal
    raise RuntimeError("test session factory not found")  # pragma: no cover


def _session():
    """A short-lived session on the API's test database."""
    return _test_session_local()()


@pytest.fixture()
def db(setup_test_db):
    """A direct session on the test database (for reading back real rows)."""
    session = _session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    """The default chart of accounts, seeded as the startup hook would."""
    seed_accounting_categories(db)
    return db


@pytest.fixture(autouse=True)
def reset_limits(client):
    """Isolate slowapi counters so repeated /pay calls never trip a 429."""
    from app.main import app

    app.state.limiter._limiter.storage.reset()


def _utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; compare them as the UTC they are."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _tehran_today() -> date:
    return datetime.now(commerce_service.TEHRAN_TZ).date()


def _draft(**changes):
    data = {
        "customer_name": "مریم احمدی",
        "mobile": "09121112233",
        "messenger": "telegram",
        "address": "تهران، خیابان آزادی",
        "specification": "رنگ مشکی",
        "shipping_toman": 12_000,
        "items": [{"description": "قطعه سفارشی", "qty": 2, "unit_toman": 150_000}],
    }
    data.update(changes)
    return data


def _approved_invoice(client, headers, **changes) -> int:
    """A real approved invoice, created and frozen through the staff API."""
    invoice_id, _token = _approved_invoice_with_token(client, headers, **changes)
    return invoice_id


def _approved_invoice_with_token(client, headers, **changes):
    """An approved invoice plus the one-time private token from its link."""
    created = client.post(f"{BASE}/staff/invoices", json=_draft(**changes), headers=headers)
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]
    approved = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    token = approved.json()["share_url"].rsplit("/", 1)[-1]
    return invoice_id, token


def _manual_pay(client, headers, invoice_id, **overrides):
    payload = {
        "payment_method": "card_to_card",
        "reference_code": "CART-123456",
        "paid_at": "2026-10-17",
        "note": "واریز به صادرات",
    }
    payload.update(overrides)
    return client.post(MANUAL_PAY.format(invoice_id=invoice_id), json=payload, headers=headers)


def _ledger_rows(invoice_id: int) -> int:
    session = _session()
    try:
        return (
            session.query(AccountingTransaction)
            .filter(AccountingTransaction.invoice_id == invoice_id)
            .count()
        )
    finally:
        session.close()


def _invoice_state(invoice_id: int) -> str:
    session = _session()
    try:
        return (
            session.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one().state
        )
    finally:
        session.close()


def _sales_income_category(db) -> AccountingCategory:
    return (
        db.query(AccountingCategory)
        .filter(AccountingCategory.name == SYSTEM_SALES_INCOME_CATEGORY_NAME)
        .one()
    )


# ── Manual payment: card-to-card ─────────────────────────────────────
def test_manual_card_to_card_payment_marks_paid_and_books_bank_income(
    client, auth_headers, seeded, db
):
    invoice_id = _approved_invoice(client, auth_headers)

    res = _manual_pay(client, auth_headers, invoice_id, reference_code="  CART-123456  ")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "paid"
    assert body["total_toman"] == ITEM_TOTAL_TOMAN
    assert body["order_id"] is not None

    # ── the invoice itself
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one()
    assert invoice.state == "paid"
    assert invoice.order_id == body["order_id"]

    # ── the manual attempt, stamped from ``paid_at`` (UTC midnight of that day)
    attempt = (
        db.query(CommercePaymentAttempt)
        .filter(CommercePaymentAttempt.invoice_id == invoice_id)
        .one()
    )
    assert attempt.provider == "manual"
    assert attempt.state == "verified"
    assert attempt.payment_method == "card_to_card"
    assert attempt.provider_trans_id == "CART-123456"  # trimmed, not "  CART…  "
    assert attempt.amount_rial == ITEM_TOTAL_RIAL
    assert attempt.invoice_revision == invoice.revision
    assert _utc(attempt.created_at) == datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert _utc(attempt.verified_at) == datetime(2026, 10, 17, tzinfo=timezone.utc)
    # A hand-recorded payment is closed business, never queued for reconciling.
    assert attempt.reconciliation_required is False

    # ── the fulfillment order for the production queue, honestly labelled
    order = db.query(Order).filter(Order.id == invoice.order_id).one()
    assert order.customer_name == "مریم احمدی"
    assert order.paid_amount == float(ITEM_TOTAL_TOMAN)
    assert order.status == "new"
    assert order.notes == f"پرداخت دستی (کارت به کارت) فاکتور #{invoice_id}"
    assert "آنلاین" not in order.notes

    # ── the accounting ledger row
    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )
    assert txn.title == f"فروش فاکتور #{invoice_id} - مریم احمدی"
    assert txn.type == "income"
    assert txn.account_type == "bank"  # card-to-card money lands in the bank
    assert txn.amount_toman == ITEM_TOTAL_TOMAN
    assert txn.transaction_date == date(2026, 10, 17)  # the staff-supplied day
    assert txn.reference_code == "CART-123456"
    assert txn.description == "واریز به صادرات"
    assert txn.order_id == invoice.order_id
    assert txn.created_by_user_id is not None  # stamped from the staff session
    assert txn.category_id == _sales_income_category(db).id
    # Booked against «فروش محصول و خدمات», never the generic «سایر درآمدها».
    assert txn.category_id != (
        db.query(AccountingCategory)
        .filter(AccountingCategory.name == "سایر درآمدها")
        .one()
        .id
    )


# ── Manual payment: cash ─────────────────────────────────────────────
def test_manual_cash_payment_books_cash_and_defaults_the_description(
    client, auth_headers, seeded, db
):
    invoice_id = _approved_invoice(client, auth_headers)

    res = _manual_pay(
        client,
        auth_headers,
        invoice_id,
        payment_method="cash",
        reference_code="",
        note="",
        paid_at="2026-10-18",
    )
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "paid"

    attempt = (
        db.query(CommercePaymentAttempt)
        .filter(CommercePaymentAttempt.invoice_id == invoice_id)
        .one()
    )
    assert attempt.provider == "manual"
    assert attempt.payment_method == "cash"

    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )
    assert txn.account_type == "cash"
    assert txn.transaction_date == date(2026, 10, 18)
    assert txn.reference_code == ""
    assert txn.description == "ثبت پرداخت دستی (cash)"

    order = db.query(Order).filter(Order.id == res.json()["order_id"]).one()
    assert order.notes == f"پرداخت دستی (نقدی) فاکتور #{invoice_id}"


# ── Access control + payload validation ──────────────────────────────
def test_manual_pay_requires_staff_and_validates_the_payload(client, auth_headers, seeded, db):
    invoice_id = _approved_invoice(client, auth_headers)

    # Anonymous callers are rejected before any state change.
    anon = client.post(MANUAL_PAY.format(invoice_id=invoice_id), json={})
    assert anon.status_code in (401, 403)

    # An unknown invoice is a 404, not a silent success.
    assert _manual_pay(client, auth_headers, 999_999).status_code == 404

    # ``payment_method`` is a closed set of the two real-world methods.
    assert (
        _manual_pay(client, auth_headers, invoice_id, payment_method="cheque").status_code == 422
    )
    # ``paid_at`` must be a parseable Gregorian date (the UI converts Shamsi).
    assert _manual_pay(client, auth_headers, invoice_id, paid_at="1405/07/25").status_code == 422
    assert _manual_pay(client, auth_headers, invoice_id, paid_at="2026-02-30").status_code == 422
    # Surplus fields are refused rather than silently ignored.
    assert _manual_pay(client, auth_headers, invoice_id, amount_toman=1).status_code == 422
    # An over-long reference cannot be smuggled past the column width.
    assert (
        _manual_pay(client, auth_headers, invoice_id, reference_code="x" * 101).status_code == 422
    )

    # …and nothing above booked, paid or queued anything.
    assert _ledger_rows(invoice_id) == 0
    assert _invoice_state(invoice_id) == "approved"
    assert db.query(Order).count() == 0
    assert db.query(CommercePaymentAttempt).count() == 0


def test_employee_staff_may_record_a_manual_payment(client, employee_headers, seeded):
    """«ثبت پرداخت دستی» is a staff action, not an admin-only one."""
    invoice_id = _approved_invoice(client, employee_headers)
    res = _manual_pay(client, employee_headers, invoice_id)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "paid"


# ── Refusal: an already paid invoice ─────────────────────────────────
def test_cannot_manual_pay_an_already_paid_invoice(client, auth_headers, seeded, db):
    invoice_id = _approved_invoice(client, auth_headers)
    assert _manual_pay(client, auth_headers, invoice_id).status_code == 200

    # Service-level guard, with the exact Persian message.
    with pytest.raises(commerce_service.CommerceStateError) as excinfo:
        commerce_service.record_manual_payment(db, invoice_id, "cash", "", date(2026, 10, 17))
    assert str(excinfo.value) == "فاکتور قبلاً پرداخت شده است"

    # HTTP-level refusal.
    second = _manual_pay(client, auth_headers, invoice_id)
    assert second.status_code == 400, second.text
    assert second.json()["detail"] == "فاکتور قبلاً پرداخت شده است"

    # The refusal is total: one attempt, one order, one ledger row.
    assert (
        db.query(CommercePaymentAttempt)
        .filter(CommercePaymentAttempt.invoice_id == invoice_id)
        .count()
        == 1
    )
    assert db.query(Order).count() == 1
    txn = db.query(AccountingTransaction).one()
    assert txn.invoice_id == invoice_id
    assert txn.amount_toman == ITEM_TOTAL_TOMAN


def test_manual_pay_refuses_a_paid_invoice_even_for_a_different_method(
    client, auth_headers, seeded, db
):
    """A second, *different* payment on a paid invoice is refused just as hard."""
    invoice_id = _approved_invoice(client, auth_headers)
    assert (
        _manual_pay(
            client, auth_headers, invoice_id, payment_method="cash", reference_code="X"
        ).status_code
        == 200
    )
    clash = _manual_pay(
        client, auth_headers, invoice_id, payment_method="card_to_card", reference_code="Y"
    )
    assert clash.status_code == 400
    assert clash.json()["detail"] == "فاکتور قبلاً پرداخت شده است"
    assert db.query(AccountingTransaction).count() == 1
    assert db.query(CommercePaymentAttempt).count() == 1
    assert db.query(Order).count() == 1


# ── Idempotency of the ledger entry ──────────────────────────────────
def test_accounting_booking_is_idempotent_for_an_invoice(client, auth_headers, seeded, db):
    """The ledger can never hold two income rows for one invoice."""
    invoice_id = _approved_invoice(client, auth_headers)
    assert _manual_pay(client, auth_headers, invoice_id).status_code == 200

    # Replay of the same staff confirmation: refused, nothing added.
    assert _manual_pay(client, auth_headers, invoice_id).status_code == 400
    assert _ledger_rows(invoice_id) == 1
    assert db.query(Order).count() == 1

    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )

    # The DB-level backstop: the UNIQUE ``invoice_id`` constraint, which is what
    # makes a replayed gateway callback harmless even if the pre-check raced.
    db.add(
        AccountingTransaction(
            title="فروش تکراری",
            category_id=_sales_income_category(db).id,
            type="income",
            amount_toman=ITEM_TOTAL_TOMAN,
            transaction_date=date(2026, 10, 17),
            account_type="bank",
            invoice_id=invoice_id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.expire_all()
    rows = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .all()
    )
    assert [row.id for row in rows] == [txn.id]
    assert rows[0].title == txn.title


# ── Online (gateway) settlement auto-sync ────────────────────────────
def _pending_attempt(db, invoice_id, *, provider="digipay", provider_trans_id=None):
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one()
    attempt = CommercePaymentAttempt(
        invoice_id=invoice_id,
        provider=provider,
        state="pending",
        provider_id=(
            f"INV{invoice_id}-R{invoice.revision}-sync-{secrets.token_hex(4)}"
        ),
        amount_rial=commerce_service.toman_to_rial(invoice.total_toman),
        invoice_revision=invoice.revision,
        type=11,
        provider_trans_id=provider_trans_id,
        redirect_url="https://uatweb.mydigipay.info/web-pay/tgs/v2:sync",
    )
    db.add(attempt)
    db.commit()
    return attempt


def test_online_settlement_books_gateway_income_on_the_tehran_day(
    client, auth_headers, seeded, db
):
    """The gateway settlement call books the same income row, ``gateway``."""
    invoice_id = _approved_invoice(client, auth_headers)
    attempt = _pending_attempt(db, invoice_id)

    commerce_service.settle_verified_payment(db, attempt, tracking_code="TRK-2001")
    db.expire_all()

    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one()
    assert invoice.state == "paid"
    assert invoice.order_id is not None

    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )
    assert txn.title == f"فروش فاکتور #{invoice_id} - مریم احمدی"
    assert txn.type == "income"
    assert txn.account_type == "gateway"
    assert txn.amount_toman == ITEM_TOTAL_TOMAN
    assert txn.transaction_date == _tehran_today()
    assert txn.order_id == invoice.order_id
    assert txn.created_by_user_id is None  # no staff actor on a gateway callback
    assert txn.category_id == _sales_income_category(db).id
    # DigiPay's attempt carries no provider transaction id of its own.
    assert txn.reference_code == ""

    order = db.query(Order).filter(Order.id == invoice.order_id).one()
    assert order.notes == f"پرداخت آنلاین فاکتور #{invoice_id} از طریق دیجی‌پی"


def test_online_settlement_uses_the_provider_transaction_id_as_reference(
    client, auth_headers, seeded, db
):
    """A BitPay attempt's ``provider_trans_id`` lands in the ledger reference."""
    invoice_id = _approved_invoice(client, auth_headers)
    attempt = _pending_attempt(db, invoice_id, provider="bitpay", provider_trans_id=887766)

    commerce_service.settle_verified_payment(db, attempt, tracking_code="IDGET-9")
    db.expire_all()

    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )
    assert txn.account_type == "gateway"
    assert txn.reference_code == "887766"


def test_replayed_settlement_does_not_double_book(client, auth_headers, seeded, db):
    """A second verified attempt cannot create a second ledger row or order."""
    invoice_id = _approved_invoice(client, auth_headers)
    first = _pending_attempt(db, invoice_id)
    commerce_service.settle_verified_payment(db, first, tracking_code="TRK-3001")

    second = _pending_attempt(db, invoice_id)
    commerce_service.settle_verified_payment(db, second, tracking_code="TRK-3002")
    db.expire_all()

    assert db.query(Order).count() == 1
    assert _ledger_rows(invoice_id) == 1
    assert (
        db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one().state == "paid"
    )


# ── Online path end-to-end (the DigiPay callback itself) ─────────────
class _FakeDigiPay:
    """Minimal documented-shape provider: ticket → callback → verify success."""

    def __init__(self):
        self.tickets = {}

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        self.tickets[provider_id] = amount_rial
        return {
            "redirect_url": "https://uatweb.mydigipay.info/web-pay/tgs/v2:sync",
            "ticket": "v2:sync-ticket",
        }

    def verify(self, *, tracking_code, provider_id, type):
        return {
            "result": {"status": 0, "message": "SUCCESS", "level": "INFO"},
            "providerId": provider_id,
            "amount": self.tickets.get(provider_id),
            "trackingCode": tracking_code,
            "paymentGateway": 3,
        }


@pytest.fixture()
def fake_digipay(client, monkeypatch):
    from app.main import app
    from app.services import digipay

    # DigiPay is parked in production; this test opts the settlement machinery in
    # explicitly through the predicate seam (the same one the pay route checks).
    monkeypatch.setattr(digipay, "checkout_enabled", lambda: True)
    fake = _FakeDigiPay()
    app.dependency_overrides[digipay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(digipay.client_dependency, None)


def test_gateway_callback_books_gateway_income_end_to_end(
    client, auth_headers, seeded, db, fake_digipay
):
    """The real callback path books the ledger row, not just the service call."""
    invoice_id, token = _approved_invoice_with_token(client, auth_headers)

    paid = client.post(f"{BASE}/invoices/{token}/pay")
    assert paid.status_code == 200, paid.text

    attempt = (
        db.query(CommercePaymentAttempt)
        .filter(CommercePaymentAttempt.invoice_id == invoice_id)
        .one()
    )
    assert attempt.state == "pending"

    callback = client.post(
        CALLBACK,
        data={
            "providerId": attempt.provider_id,
            "amount": str(attempt.amount_rial),
            "trackingCode": "TRK-E2E",
            "type": str(attempt.type),
            "result": "SUCCESS",
        },
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert "payment=success" in callback.headers["location"]

    db.expire_all()
    invoice = db.query(CommerceInvoice).filter(CommerceInvoice.id == invoice_id).one()
    assert invoice.state == "paid"

    txn = (
        db.query(AccountingTransaction)
        .filter(AccountingTransaction.invoice_id == invoice_id)
        .one()
    )
    assert txn.title == f"فروش فاکتور #{invoice_id} - مریم احمدی"
    assert txn.type == "income"
    assert txn.account_type == "gateway"
    assert txn.amount_toman == invoice.total_toman
    assert txn.transaction_date == _tehran_today()
    assert txn.order_id == invoice.order_id
