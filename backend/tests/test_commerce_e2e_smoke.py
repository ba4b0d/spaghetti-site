"""Task 4 Step 3 — local end-to-end commerce smoke (fake provider, no live I/O).

Drives the whole reviewed-commerce path through the real FastAPI app with the
real routers, models and service transitions, but with every outbound side
effect replaced by an in-process double:

* ``FakeDigiPay`` is injected through the ``digipay.client_dependency`` override,
  so ``start_payment`` / the callback ``verify`` never touch the gateway.
* The three notification channel entrypoints are monkeypatched, so Telegram,
  SMS.ir and SMTP are never contacted; every channel is nonetheless switched on
  with throwaway credentials so each event fans out to all three and the alert
  is asserted per channel. Live DigiPay credentials are also removed from the
  environment so a leaked env var cannot open a real client.
* The app lifespan's Telegram receive-poll thread is neutralised suite-wide
  (see ``conftest.client``), so entering ``TestClient`` never opens a live
  ``getUpdates`` socket even though the Settings table holds a real token.

Two invoices are exercised end to end:

1. Website request → staff invoice → approve → public token read → initiate pay
   → matching callback (one paid Order) → duplicate callback (unchanged).
2. Manual (chat) invoice → the same approve → read → pay → callback path.

Nothing here reads credentials, mutates production data, or sends anything.
"""
import pytest

BASE = "/api/v1/commerce"
CALLBACK = f"{BASE}/digipay/callback"

UAT_REDIRECT = "https://uatweb.mydigipay.info/web-pay/tgs/v2:e2e-smoke-ticket"


class FakeDigiPay:
    """Scripted UPG double: records tickets/verify calls, returns doc envelopes."""

    def __init__(self, *, verify_status=0):
        self.redirect_url = UAT_REDIRECT
        self.verify_status = verify_status
        self.tickets = {}
        self.verify_calls = []

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        self.tickets[provider_id] = {
            "amount_rial": amount_rial,
            "mobile": mobile,
            "callback_url": callback_url,
        }
        return {
            "redirect_url": self.redirect_url,
            "ticket": "v2:e2e-smoke-ticket",
            "provider_id": provider_id,
        }

    def verify(self, *, tracking_code, provider_id, type):
        self.verify_calls.append(
            {"tracking_code": tracking_code, "provider_id": provider_id, "type": type}
        )
        payload = {
            "result": {"status": self.verify_status, "message": "m", "level": "INFO"},
            "providerId": provider_id,
            "amount": self.tickets.get(provider_id, {}).get("amount_rial"),
            "paymentGateway": 3,
        }
        if self.verify_status == 0:
            payload["trackingCode"] = tracking_code
        return payload


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    """Replace all three notification transports, scrub DigiPay credentials.

    Every channel toggle is switched on and given throwaway credentials so the
    real notification fan-out runs for all three; the transport entrypoints
    themselves are replaced by in-process doubles, so nothing is ever sent.
    """
    from app.services import commerce_notifications as cn

    records = {"telegram": [], "sms": [], "email": []}
    monkeypatch.setattr(
        cn, "send_telegram_message",
        lambda text: records["telegram"].append(text) or cn.SENT,
    )
    monkeypatch.setattr(
        cn, "send_sms_alert",
        lambda parameters: records["sms"].append(parameters) or cn.SENT,
    )
    monkeypatch.setattr(
        cn, "send_email_alert",
        lambda subject, body: records["email"].append((subject, body)) or cn.SENT,
    )

    # Configure all three channels (throwaway values) so each event is expected
    # to fan out to Telegram *and* SMS *and* email; the doubles above mean no
    # live send happens regardless.
    for var, value in (
        ("COMMERCE_NOTIFY_TELEGRAM", "1"),
        ("COMMERCE_NOTIFY_SMS", "1"),
        ("SMS_IR_API_KEY", "test-key"),
        ("SMS_IR_TEMPLATE_ID", "100"),
        ("SMS_IR_ADMIN_MOBILE", "09120000000"),
        ("COMMERCE_NOTIFY_SMTP", "1"),
        ("SMTP_HOST", "smtp.test.invalid"),
        ("SMTP_PORT", "587"),
        ("SMTP_USERNAME", "mailer"),
        ("SMTP_PASSWORD", "test-secret"),
        ("SMTP_FROM", "no-reply@test.invalid"),
        ("SMTP_ADMIN_TO", "owner@test.invalid"),
    ):
        monkeypatch.setenv(var, value)

    for var in (
        "DIGIPAY_CLIENT_ID", "DIGIPAY_CLIENT_SECRET",
        "DIGIPAY_USERNAME", "DIGIPAY_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    return records


@pytest.fixture()
def fake_provider(client):
    from app.main import app
    from app.services import digipay

    fake = FakeDigiPay()
    app.dependency_overrides[digipay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(digipay.client_dependency, None)


# ── helpers ──────────────────────────────────────────────────────────

def _create_product(client, auth_headers):
    r = client.post(
        "/api/v1/products",
        json={"name": "محصول اسموک", "weight_g": 40, "print_time_hours": 1, "final_price": 50000},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _website_request(client, auth_headers, product_id):
    r = client.post(
        f"{BASE}/requests",
        json={
            "customer_name": "رضا",
            "mobile": "09123456789",
            "messenger": "telegram",
            "items": [{"product_id": product_id, "qty": 2}],
        },
    )
    assert r.status_code == 200, r.text
    receipt_id = r.json()["receipt_id"]
    # The staff invoice links the numeric request id, not the receipt string.
    rows = client.get(f"{BASE}/staff/requests", headers=auth_headers).json()
    match = next(row for row in rows if row["receipt_id"] == receipt_id)
    return match["id"]


def _draft_from_request(client, auth_headers, request_id):
    r = client.post(
        f"{BASE}/staff/invoices",
        json={
            "request_id": request_id,
            "customer_name": "رضا",
            "mobile": "09123456789",
            "messenger": "telegram",
            "shipping_toman": 12000,
            "items": [{"description": "قطعه سفارشی", "qty": 2, "unit_toman": 150000}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _draft_manual(client, auth_headers):
    r = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "سمیرا",
            "mobile": "09120000000",
            "messenger": "bale",
            "items": [{"description": "سفارش دستی", "qty": 1, "unit_toman": 200000}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _approve(client, auth_headers, invoice_id):
    r = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
    token = r.json()["share_url"].rsplit("/", 1)[-1]
    return token


def _latest_attempt(invoice_id):
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return (
            db.query(CommercePaymentAttempt)
            .filter(CommercePaymentAttempt.invoice_id == invoice_id)
            .order_by(CommercePaymentAttempt.id.desc())
            .first()
        )
    finally:
        db.close()


def _callback_payload(attempt):
    return {
        "providerId": attempt.provider_id,
        "amount": str(attempt.amount_rial),
        "trackingCode": "TRK-E2E",
        "type": "11",
        "result": "SUCCESS",
    }


def _drive_payment_to_paid(client, auth_headers, invoice_id, *, expected_toman):
    """approve → public read → initiate pay → one matching callback → paid."""
    token = _approve(client, auth_headers, invoice_id)

    read = client.get(f"{BASE}/invoices/{token}")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["state"] == "approved"
    assert body["total_toman"] == expected_toman
    # Public read must not leak contact PII.
    assert "mobile" not in body and "customer_name" not in body

    pay = client.post(f"{BASE}/invoices/{token}/pay")
    assert pay.status_code == 200, pay.text
    assert pay.json()["redirect_url"] == UAT_REDIRECT

    attempt = _latest_attempt(invoice_id)
    assert attempt is not None and attempt.state == "pending"
    assert attempt.amount_rial == expected_toman * 10

    first = client.post(CALLBACK, data=_callback_payload(attempt), follow_redirects=False)
    assert first.status_code in (302, 303), first.text
    assert "payment=success" in first.headers["location"]
    assert token not in first.headers["location"]
    return token, attempt


def _assert_invoice_and_single_order(invoice_id, *, expected_toman, expected_orders):
    from app.models import CommerceInvoice, Order, OrderItem, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        assert invoice.state == "paid"
        assert invoice.order_id is not None
        order = db.get(Order, invoice.order_id)
        assert order is not None
        assert order.paid_amount == expected_toman
        assert order.status == "new"  # fulfillment stays staff-controlled
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        assert sum(i.unit_price * i.qty for i in items) == expected_toman
        attempt = (
            db.query(CommercePaymentAttempt)
            .filter(CommercePaymentAttempt.invoice_id == invoice_id)
            .order_by(CommercePaymentAttempt.id.desc())
            .first()
        )
        assert attempt.state == "verified"
        assert db.query(Order).count() == expected_orders
        return invoice.order_id
    finally:
        db.close()


def _sms_event_values(records):
    """The ``EVENT`` label of each SMS fan-out (one parameter list per event).

    SMS.ir requires the *exact* approved-template parameter name; template
    ``309349`` is approved with ``#EVENT#`` / ``#CODE#`` (uppercase), so the
    fan-out must carry ``EVENT`` — a lowercase ``event`` is not substituted.
    """
    return [
        next(p["value"] for p in params if p["name"] == "EVENT")
        for params in records["sms"]
    ]


def _email_subjects(records):
    """The subject line of each email fan-out."""
    return [subject for subject, _body in records["email"]]


# ── the two end-to-end scenarios ─────────────────────────────────────

def test_website_request_full_path_pays_once(client, auth_headers, fake_provider, no_live_io):
    product = _create_product(client, auth_headers)
    product_id = product["id"]

    # 1. public request
    request_id = _website_request(client, auth_headers, product_id)

    # 2. staff picks the request into a draft invoice
    invoice_id = _draft_from_request(client, auth_headers, request_id)

    # 3–6. approve → read → pay → matching callback
    token, attempt = _drive_payment_to_paid(client, auth_headers, invoice_id, expected_toman=312000)
    _assert_invoice_and_single_order(invoice_id, expected_toman=312000, expected_orders=1)

    # 7. duplicate callback leaves the settled state untouched
    dup = client.post(CALLBACK, data=_callback_payload(attempt), follow_redirects=False)
    assert "payment=success" in dup.headers["location"]
    _assert_invoice_and_single_order(invoice_id, expected_toman=312000, expected_orders=1)

    # Notifications: request_created + invoice_approved + payment_verified, once
    # each, on every configured channel.
    records = no_live_io
    tg, sms, email = records["telegram"], records["sms"], records["email"]

    assert len(tg) == 3 and len(sms) == 3 and len(email) == 3

    assert sum("درخواست جدید وبسایت" in t for t in tg) == 1
    assert sum("تأیید فاکتور" in t for t in tg) == 1
    assert sum("پرداخت موفق فاکتور" in t for t in tg) == 1
    assert sum("REQ-" in t for t in tg) == 1  # the request receipt code

    # SMS + email fan out the identical three events (one apiece).
    assert sorted(_sms_event_values(records)) == sorted(["درخواست", "فاکتور", "پرداخت"])
    subjects = _email_subjects(records)
    assert sum("درخواست جدید وبسایت" in s for s in subjects) == 1
    assert sum("تأیید فاکتور" in s for s in subjects) == 1
    assert sum("پرداخت موفق فاکتور" in s for s in subjects) == 1

    # The private bearer token is never broadcast on any channel.
    assert all(token not in t for t in tg)
    assert all(token not in str(params) for params in sms)
    assert all(token not in subject and token not in body for subject, body in email)


def test_manual_invoice_full_path_pays_once(client, auth_headers, fake_provider, no_live_io):
    invoice_id = _draft_manual(client, auth_headers)

    token, attempt = _drive_payment_to_paid(client, auth_headers, invoice_id, expected_toman=200000)
    _assert_invoice_and_single_order(invoice_id, expected_toman=200000, expected_orders=1)

    dup = client.post(CALLBACK, data=_callback_payload(attempt), follow_redirects=False)
    assert "payment=success" in dup.headers["location"]
    _assert_invoice_and_single_order(invoice_id, expected_toman=200000, expected_orders=1)

    # A manual invoice starts from no website request, so it emits only the
    # approval + paid alerts — never a request_created one — on every channel.
    records = no_live_io
    tg, sms, email = records["telegram"], records["sms"], records["email"]

    assert len(tg) == 2 and len(sms) == 2 and len(email) == 2
    assert sum("تأیید فاکتور" in t for t in tg) == 1
    assert sum("پرداخت موفق فاکتور" in t for t in tg) == 1

    # No request_created alert anywhere: no request label, no REQ- receipt code.
    assert not [t for t in tg if "درخواست جدید وبسایت" in t or "REQ-" in t]
    assert sorted(_sms_event_values(records)) == sorted(["فاکتور", "پرداخت"])
    assert not [s for s in _email_subjects(records) if "درخواست جدید وبسایت" in s]

    # The private bearer token stays out of every channel.
    assert all(token not in t for t in tg)
    assert all(token not in str(params) for params in sms)
    assert all(token not in subject and token not in body for subject, body in email)
