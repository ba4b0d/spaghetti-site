"""Task 3 — DigiPay UPG adapter + durable payment attempts (backend only).

Two layers are covered:

* ``DigiPayClient`` unit tests with an injected fake HTTP session (no network).
* Endpoint/settlement tests against the real routers with a fake provider
  injected through the ``client_dependency`` FastAPI override.

Nothing here talks to a live gateway: every provider response is scripted.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

BASE = "/api/v1/commerce"
CALLBACK = f"{BASE}/digipay/callback"


@pytest.fixture(autouse=True)
def reset_limits(client):
    from app.main import app
    app.state.limiter._limiter.storage.reset()


# ══════════════════════════════════════════════════════════════════════
# Fake HTTP session for the DigiPay client unit tests
# ══════════════════════════════════════════════════════════════════════

class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.headers = {}

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


def make_client(responses, **overrides):
    from app.services.digipay import DigiPayClient, DIGIPAY_UAT_BASE_URL

    kwargs = dict(
        client_id="cid",
        client_secret="csecret",
        username="digiuser",
        password="digipass",
        base_url=DIGIPAY_UAT_BASE_URL,
        session=FakeSession(responses),
    )
    kwargs.update(overrides)
    return DigiPayClient(**kwargs)


TOKEN_OK = FakeResponse(200, {"access_token": "tok1", "token_type": "bearer", "expires_in": 3600})


# ══════════════════════════════════════════════════════════════════════
# DigiPay client unit tests
# ══════════════════════════════════════════════════════════════════════

def test_login_uses_basic_auth_and_password_grant():
    client = make_client([TOKEN_OK])
    token = client.login()
    assert token == "tok1"
    call = client._session.calls[0]
    assert call["url"].endswith("/oauth/token")
    assert call["headers"]["Authorization"].startswith("Basic ")
    assert call["data"]["grant_type"] == "password"
    assert call["data"]["username"] == "digiuser"
    assert call["data"]["password"] == "digipass"
    assert call["timeout"] is not None


def test_create_ticket_uses_type_11_and_documented_headers():
    from app.services.digipay import DIGIPAY_TICKET_TYPE

    client = make_client([TOKEN_OK, FakeResponse(200, {"result": {"redirectUrl": "https://pn.mydigipay.com/pay/x"}})])
    ticket = client.create_ticket(
        amount_rial=3120000,
        mobile="09123456789",
        provider_id="INV1-R1-abc",
        callback_url="https://spaghettiprints.ir/api/v1/commerce/digipay/callback",
    )
    assert ticket["redirect_url"] == "https://pn.mydigipay.com/pay/x"
    call = client._session.calls[1]
    assert "/tickets/business" in call["url"]
    assert call["params"]["type"] == DIGIPAY_TICKET_TYPE == 11
    assert call["json"]["amount"] == 3120000
    assert call["json"]["cellNumber"] == "09123456789"
    assert call["json"]["providerId"] == "INV1-R1-abc"
    assert call["json"]["callbackUrl"].endswith("/api/v1/commerce/digipay/callback")
    assert call["headers"]["Agent"] == "WEB"
    assert call["headers"]["Digipay-Version"] == "2022-02-02"
    assert call["headers"]["Authorization"] == "Bearer tok1"


def test_verify_posts_tracking_and_provider_id():
    client = make_client([
        TOKEN_OK,
        FakeResponse(200, {"result": {"status": 0, "amount": 3120000, "providerId": "INV1-R1-abc", "trackingCode": "T1", "type": 11}}),
    ])
    result = client.verify(tracking_code="T1", provider_id="INV1-R1-abc", type=11)
    assert result["status"] == 0 and result["amount"] == 3120000
    call = client._session.calls[1]
    assert "/purchases/verify" in call["url"]
    assert call["params"]["type"] == 11
    assert call["json"] == {"trackingCode": "T1", "providerId": "INV1-R1-abc"}


def test_client_retries_once_after_401_with_fresh_token():
    client = make_client([
        TOKEN_OK,
        FakeResponse(401, {"error": "expired"}),
        FakeResponse(200, {"access_token": "tok2", "token_type": "bearer", "expires_in": 3600}),
        FakeResponse(200, {"result": {"redirectUrl": "https://pn.mydigipay.com/pay/y"}}),
    ])
    ticket = client.create_ticket(
        amount_rial=10000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb"
    )
    assert ticket["redirect_url"] == "https://pn.mydigipay.com/pay/y"
    urls = [c["url"] for c in client._session.calls]
    assert sum("oauth/token" in u for u in urls) == 2
    assert client._session.calls[3]["headers"]["Authorization"] == "Bearer tok2"


def test_client_refuses_non_digipay_redirect_host():
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, FakeResponse(200, {"result": {"redirectUrl": "https://evil.example/pay/x"}})])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_client_refuses_http_redirect():
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, FakeResponse(200, {"result": {"redirectUrl": "http://pn.mydigipay.com/pay/x"}})])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_base_url_selection_is_allowlisted(monkeypatch):
    from app.services import digipay

    monkeypatch.delenv("DIGIPAY_BASE_URL", raising=False)
    monkeypatch.setenv("DIGIPAY_ENV", "staging")
    assert digipay.resolve_base_url() == digipay.DIGIPAY_UAT_BASE_URL
    monkeypatch.setenv("DIGIPAY_ENV", "production")
    assert digipay.resolve_base_url() == digipay.DIGIPAY_LIVE_BASE_URL
    # An arbitrary override host is refused.
    monkeypatch.setenv("DIGIPAY_BASE_URL", "https://attacker.example/api")
    with pytest.raises(digipay.DigiPayConfigError):
        digipay.resolve_base_url()


def test_get_client_requires_credentials(monkeypatch):
    from app.services import digipay

    for var in ("DIGIPAY_CLIENT_ID", "DIGIPAY_CLIENT_SECRET", "DIGIPAY_USERNAME", "DIGIPAY_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(digipay.DigiPayConfigError):
        digipay.get_client()


def test_toman_to_rial_is_exact_times_ten():
    from app.services.commerce import toman_to_rial

    assert toman_to_rial(1) == 10
    assert toman_to_rial(312000) == 3120000
    assert isinstance(toman_to_rial(312000), int)


# ══════════════════════════════════════════════════════════════════════
# Fake provider injected into the routers
# ══════════════════════════════════════════════════════════════════════

class FakeDigiPay:
    """Records calls; scripts success/failure for ticket + verify."""

    def __init__(self, *, redirect_url="https://pn.mydigipay.com/pay/live", verify_error=None, create_error=None):
        self.redirect_url = redirect_url
        self.verify_error = verify_error
        self.create_error = create_error
        self.tickets = {}
        self.verify_calls = []

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        if self.create_error:
            raise self.create_error
        self.tickets[provider_id] = {
            "amount_rial": amount_rial,
            "mobile": mobile,
            "callback_url": callback_url,
        }
        return {"redirect_url": self.redirect_url, "provider_id": provider_id}

    def verify(self, *, tracking_code, provider_id, type):
        if self.verify_error:
            raise self.verify_error
        self.verify_calls.append({"tracking_code": tracking_code, "provider_id": provider_id, "type": type})
        ticket = self.tickets.get(provider_id, {})
        return {
            "status": 0,
            "amount": ticket.get("amount_rial"),
            "providerId": provider_id,
            "trackingCode": tracking_code,
            "type": type,
        }


@pytest.fixture()
def fake_provider(client):
    from app.main import app
    from app.services import digipay

    fake = FakeDigiPay()
    app.dependency_overrides[digipay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(digipay.client_dependency, None)


# ══════════════════════════════════════════════════════════════════════
# Invoice + pay helpers
# ══════════════════════════════════════════════════════════════════════

def draft(**changes):
    data = {
        "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
        "specification": "رنگ آبی", "internal_note": "private-note", "shipping_toman": 12000,
        "items": [{"description": "قطعه سفارشی", "qty": 2, "unit_toman": 150000}],
    }
    data.update(changes)
    return data


def make_approved(client, auth_headers, **changes):
    r = client.post(f"{BASE}/staff/invoices", json=draft(**changes), headers=auth_headers)
    assert r.status_code == 201, r.text
    invoice_id = r.json()["id"]
    approved = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    token = approved.json()["share_url"].rsplit("/", 1)[-1]
    return invoice_id, token


def pay(client, token):
    return client.post(f"{BASE}/invoices/{token}/pay")


def latest_attempt(invoice_id):
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


def callback_payload(attempt, **overrides):
    data = {
        "providerId": attempt.provider_id,
        "amount": str(attempt.amount_rial),
        "trackingCode": "TRK-1",
        "type": str(attempt.type),
        "result": "SUCCESS",
    }
    data.update(overrides)
    return data


# ══════════════════════════════════════════════════════════════════════
# /pay endpoint
# ══════════════════════════════════════════════════════════════════════

def test_pay_returns_redirect_and_durable_attempt(client, auth_headers, fake_provider):
    invoice_id, token = make_approved(client, auth_headers)
    r = pay(client, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["redirect_url"] == fake_provider.redirect_url

    attempt = latest_attempt(invoice_id)
    assert attempt is not None
    assert attempt.provider == "digipay"
    assert attempt.state == "pending"
    assert attempt.amount_rial == 3120000          # 312000 toman * 10, exactly once
    assert attempt.invoice_revision == 1
    assert attempt.type == 11
    assert attempt.redirect_url == fake_provider.redirect_url
    assert fake_provider.tickets[attempt.provider_id]["amount_rial"] == 3120000


def test_pay_repeat_clicks_are_idempotent(client, auth_headers, fake_provider):
    invoice_id, token = make_approved(client, auth_headers)
    first = pay(client, token).json()["redirect_url"]
    second = pay(client, token).json()["redirect_url"]
    assert first == second
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        count = db.query(CommercePaymentAttempt).filter(CommercePaymentAttempt.invoice_id == invoice_id).count()
    finally:
        db.close()
    assert count == 1


def test_pay_rejected_for_draft_expired_and_paid(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    # draft invoice has no live token at all
    r = client.post(f"{BASE}/staff/invoices", json=draft(), headers=auth_headers)
    draft_id = r.json()["id"]
    assert pay(client, "not-a-real-token").status_code == 404

    invoice_id, token = make_approved(client, auth_headers)
    # expire the link
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id).token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert pay(client, token).status_code == 410

    # a paid invoice cannot be started again
    invoice_id2, token2 = make_approved(client, auth_headers)
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id2).state = "paid"
        db.commit()
    finally:
        db.close()
    assert pay(client, token2).status_code == 409
    assert draft_id  # draft exists but was never payable


def test_pay_without_configuration_returns_503(client, auth_headers, monkeypatch):
    invoice_id, token = make_approved(client, auth_headers)
    for var in ("DIGIPAY_CLIENT_ID", "DIGIPAY_CLIENT_SECRET", "DIGIPAY_USERNAME", "DIGIPAY_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    from app.main import app
    from app.services import digipay
    app.dependency_overrides.pop(digipay.client_dependency, None)
    assert pay(client, token).status_code in (502, 503)


def test_pay_gateway_failure_leaves_recoverable_unknown(client, auth_headers, fake_provider):
    from app.services.digipay import DigiPayError

    fake_provider.create_error = DigiPayError("network down")
    invoice_id, token = make_approved(client, auth_headers)
    r = pay(client, token)
    assert r.status_code in (502, 503)
    attempt = latest_attempt(invoice_id)
    assert attempt.state == "unknown"
    assert attempt.redirect_url is None


def test_pay_sets_no_store_headers(client, auth_headers, fake_provider):
    _, token = make_approved(client, auth_headers)
    r = pay(client, token)
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["Referrer-Policy"] == "no-referrer"


# ══════════════════════════════════════════════════════════════════════
# /digipay/callback
# ══════════════════════════════════════════════════════════════════════

def _pay_and_get_attempt(client, auth_headers, fake_provider):
    invoice_id, token = make_approved(client, auth_headers)
    assert pay(client, token).status_code == 200
    return invoice_id, token, latest_attempt(invoice_id)


def test_callback_success_settles_once_and_links_one_order(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice, Order, OrderItem
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    location = r.headers["location"]
    assert "payment=success" in location
    assert token not in location          # no bearer leak into the redirect
    assert attempt.provider_id not in location

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        assert invoice.state == "paid"
        assert invoice.order_id is not None
        order = db.get(Order, invoice.order_id)
        assert order is not None
        assert order.paid_amount == 312000
        assert order.status == "new"      # fulfillment stays staff-controlled
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        assert sum(i.unit_price * i.qty for i in items) == 312000
        refreshed = (
            db.query(type(attempt)).filter_by(provider_id=attempt.provider_id).one()
        )
        assert refreshed.state == "verified"
        assert refreshed.tracking_code == "TRK-1"
    finally:
        db.close()


def test_callback_duplicate_replay_does_not_double_account(client, auth_headers, fake_provider):
    from app.models import Order
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    payload = callback_payload(attempt)
    first = client.post(CALLBACK, data=payload, follow_redirects=False)
    second = client.post(CALLBACK, data=payload, follow_redirects=False)
    assert "payment=success" in first.headers["location"]
    assert "payment=success" in second.headers["location"]

    db = TestSessionLocal()
    try:
        orders = db.query(Order).all()
        assert len(orders) == 1
    finally:
        db.close()


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "999"},                       # amount mismatch
        {"type": "5"},                           # type mismatch
        {"providerId": "unknown-provider-id"},   # unknown attempt
        {"result": "FAILURE"},                   # provider reports failure
        {"trackingCode": ""},                    # missing tracking code
    ],
)
def test_callback_mismatch_does_not_mark_paid(client, auth_headers, fake_provider, override):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt, **override), follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "payment=success" not in r.headers["location"]

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()


def test_callback_verify_status_nonzero_refuses(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    # Server-side verify says not settled even though the callback claimed success.
    fake_provider.verify = lambda **kw: {"status": 5, "amount": attempt.amount_rial, "providerId": attempt.provider_id, "type": attempt.type}
    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert "payment=success" not in r.headers["location"]
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()


def test_callback_verify_amount_mismatch_refuses(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    fake_provider.verify = lambda **kw: {"status": 0, "amount": attempt.amount_rial + 1, "providerId": attempt.provider_id, "type": attempt.type}
    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert "payment=success" not in r.headers["location"]
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()


def test_callback_transient_verify_error_leaves_pending_unknown(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice
    from app.services.commerce import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal
    from app.services.digipay import DigiPayError

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    fake_provider.verify_error = DigiPayError("timeout")
    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert "payment=success" not in r.headers["location"]

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # not claimed paid
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"
    finally:
        db.close()


def test_two_attempts_settle_invoice_exactly_once(client, auth_headers, fake_provider):
    """Double-settlement guard: a second verified attempt cannot create a 2nd order."""
    from app.models import Order
    from app.services import commerce as commerce_service
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)

    # A second, independent attempt racing on the same (now paid) invoice.
    db = TestSessionLocal()
    try:
        from app.models import CommerceInvoice
        invoice = db.get(CommerceInvoice, invoice_id)
        second = commerce_service.CommercePaymentAttempt(
            invoice_id=invoice_id, provider="digipay", state="pending",
            provider_id="INV1-R1-second", amount_rial=3120000,
            invoice_revision=1, type=11, redirect_url=fake_provider.redirect_url,
        )
        db.add(second)
        db.commit()
        commerce_service.settle_verified_payment(db, second, tracking_code="TRK-2")
        orders = db.query(Order).all()
        assert len(orders) == 1
        assert db.get(CommerceInvoice, invoice_id).order_id == orders[0].id
    finally:
        db.close()
