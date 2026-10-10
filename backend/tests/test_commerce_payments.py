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

# Documented (docs "UPG") response envelopes. Ticket/verify payloads carry their
# identity fields at the TOP level; only the outcome flag is nested in `result`.
UAT_REDIRECT = "https://uatweb.mydigipay.info/web-pay/tgs/v2:ab17ec383d654be3b009f9fc45202f80"
LIVE_REDIRECT = "https://web.mydigipay.com/web-pay/tgs/v2:ab17ec383d654be3b009f9fc45202f80"


def doc_ticket_response(*, redirect=UAT_REDIRECT, status=0, ticket="v2:ab17ec383d654be3b009f9fc45202f80"):
    return FakeResponse(200, {
        "result": {"title": "SUCCESS" if status == 0 else "ERROR", "status": status, "message": "m", "level": "INFO"},
        "ticket": ticket,
        "redirectUrl": redirect,
    })


def doc_verify_response(*, status=0, amount=3120000, provider_id="INV1-R1-abc", tracking_code="T1", payment_gateway=3):
    return FakeResponse(200, {
        "result": {"status": status, "message": "m", "level": "INFO"},
        "trackingCode": tracking_code,
        "providerId": provider_id,
        "amount": amount,
        "paymentGateway": payment_gateway,
    })


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


def test_create_ticket_reads_top_level_redirect_and_uses_type_11():
    from app.services.digipay import DIGIPAY_TICKET_TYPE

    client = make_client([TOKEN_OK, doc_ticket_response()])
    ticket = client.create_ticket(
        amount_rial=3120000,
        mobile="09123456789",
        provider_id="INV1-R1-abc",
        callback_url="https://spaghettiprints.ir/api/v1/commerce/digipay/callback",
    )
    # C1: the documented redirect lives at the TOP level of the response.
    assert ticket["redirect_url"] == UAT_REDIRECT
    assert ticket["ticket"] == "v2:ab17ec383d654be3b009f9fc45202f80"
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


def test_create_ticket_rejects_nested_only_redirect():
    """The old bug read redirectUrl out of `result`; a real response must not."""
    from app.services.digipay import DigiPayResponseError

    nested_only = FakeResponse(200, {
        "result": {"status": 0, "redirectUrl": UAT_REDIRECT},
        "ticket": "v2:x",
    })
    client = make_client([TOKEN_OK, nested_only])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_create_ticket_rejects_nonzero_result_status():
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, doc_ticket_response(status=5, redirect=UAT_REDIRECT)])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_verify_returns_full_documented_payload():
    client = make_client([TOKEN_OK, doc_verify_response()])
    result = client.verify(tracking_code="T1", provider_id="INV1-R1-abc", type=0)
    # C2: success flag is nested; identity/amount are top-level.
    assert result["result"]["status"] == 0
    assert result["amount"] == 3120000
    assert result["providerId"] == "INV1-R1-abc"
    assert result["paymentGateway"] == 3
    call = client._session.calls[1]
    assert "/purchases/verify" in call["url"]
    assert call["params"]["type"] == 0          # the method echoed from the callback
    assert call["json"] == {"trackingCode": "T1", "providerId": "INV1-R1-abc"}


def test_client_retries_once_after_401_with_fresh_token():
    client = make_client([
        TOKEN_OK,
        FakeResponse(401, {"error": "expired"}),
        FakeResponse(200, {"access_token": "tok2", "token_type": "bearer", "expires_in": 3600}),
        doc_ticket_response(redirect=UAT_REDIRECT),
    ])
    ticket = client.create_ticket(
        amount_rial=10000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb"
    )
    assert ticket["redirect_url"] == UAT_REDIRECT
    urls = [c["url"] for c in client._session.calls]
    assert sum("oauth/token" in u for u in urls) == 2
    assert client._session.calls[3]["headers"]["Authorization"] == "Bearer tok2"


def test_client_refuses_non_digipay_redirect_host():
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, doc_ticket_response(redirect="https://evil.example/pay/x")])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_client_refuses_http_redirect():
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, doc_ticket_response(redirect="http://uatweb.mydigipay.info/pay/x")])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_client_refuses_unlisted_mydigipay_host():
    """I3: only the documented web-pay host is allowed, not any *.mydigipay.* sibling."""
    from app.services.digipay import DigiPayResponseError

    client = make_client([TOKEN_OK, doc_ticket_response(redirect="https://pn.mydigipay.com/pay/x")])
    with pytest.raises(DigiPayResponseError):
        client.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")


def test_redirect_allowlist_is_environment_scoped():
    """A live client accepts only the live web-pay host; UAT only the UAT host."""
    from app.services.digipay import DigiPayResponseError, DIGIPAY_LIVE_BASE_URL

    live = make_client([TOKEN_OK, doc_ticket_response(redirect=LIVE_REDIRECT)], base_url=DIGIPAY_LIVE_BASE_URL)
    assert live.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P", callback_url="https://spaghettiprints.ir/cb")["redirect_url"] == LIVE_REDIRECT

    # A live client must refuse a UAT redirect...
    live2 = make_client([TOKEN_OK, doc_ticket_response(redirect=UAT_REDIRECT)], base_url=DIGIPAY_LIVE_BASE_URL)
    with pytest.raises(DigiPayResponseError):
        live2.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P2", callback_url="https://spaghettiprints.ir/cb")

    # ...and a UAT client must refuse a live redirect.
    uat = make_client([TOKEN_OK, doc_ticket_response(redirect=LIVE_REDIRECT)])
    with pytest.raises(DigiPayResponseError):
        uat.create_ticket(amount_rial=1000, mobile="09123456789", provider_id="P3", callback_url="https://spaghettiprints.ir/cb")


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
    """Records calls; scripts success/failure for ticket + verify.

    Returns the documented (docs "UPG") response envelopes so the service layer
    is exercised against real payload shapes, not a simplified fake.
    """

    def __init__(self, *, redirect_url=UAT_REDIRECT, verify_error=None, create_error=None, verify_status=0):
        self.redirect_url = redirect_url
        self.verify_error = verify_error
        self.create_error = create_error
        self.verify_status = verify_status
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
        return {
            "redirect_url": self.redirect_url,
            "ticket": "v2:fake-ticket",
            "provider_id": provider_id,
        }

    def verify(self, *, tracking_code, provider_id, type):
        if self.verify_error:
            raise self.verify_error
        self.verify_calls.append({"tracking_code": tracking_code, "provider_id": provider_id, "type": type})
        ticket = self.tickets.get(provider_id, {})
        payload = {
            "result": {"status": self.verify_status, "message": "m", "level": "INFO"},
            "providerId": provider_id,
            "amount": ticket.get("amount_rial"),
            "paymentGateway": 3,
        }
        # A real gateway echoes the ``trackingCode`` only for the transaction it
        # actually holds. For a ticket it recognises it still echoes
        # providerId/amount (which is exactly why those two are *not* on their
        # own evidence of a failure), but a terminal non-success / "not found"
        # reply carries no tracking echo.
        if self.verify_status == 0:
            payload["trackingCode"] = tracking_code
        return payload


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
        {"type": "5"},                           # credit (type=5) → unsupported in v1
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
    fake_provider.verify = lambda **kw: {
        "result": {"status": 5},
        "amount": attempt.amount_rial,
        "providerId": attempt.provider_id,
    }
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
    fake_provider.verify = lambda **kw: {
        "result": {"status": 0},
        "amount": attempt.amount_rial + 1,
        "providerId": attempt.provider_id,
    }
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


# ══════════════════════════════════════════════════════════════════════
# I1 — the callback `type` is the method actually used (IPG=0 / Wallet=11)
# ══════════════════════════════════════════════════════════════════════

def test_callback_ipg_type_is_verified_with_callback_type(client, auth_headers, fake_provider):
    """An IPG (type=0) callback must verify with type=0, never the ticket's 11."""
    from app.models import CommercePaymentAttempt, CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)
    assert "payment=success" in r.headers["location"]
    assert fake_provider.verify_calls[-1]["type"] == 0

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "paid"
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "verified"
        assert row.payment_method == 0   # the method recorded, not the ticket type
        assert row.type == 11            # UPG ticket type preserved
    finally:
        db.close()


@pytest.mark.parametrize("ctype", ["5", "13", "24"])
def test_callback_rejects_credit_methods_without_verifying(client, auth_headers, fake_provider, ctype):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt, type=ctype), follow_redirects=False)
    assert "payment=success" not in r.headers["location"]
    assert fake_provider.verify_calls == []      # credit/BNPL never verified
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        # N1: an untrusted callback must NOT terminally fail the attempt — that
        # would release the invoice lock and hide the row from reconciliation.
        assert row.state == "unknown"
        # An unsupported method is never trusted: nothing is persisted from the
        # untrusted callback (no poisoning of the attempt's identity).
        assert row.payment_method is None
        assert row.tracking_code is None
    finally:
        db.close()


def test_callback_wallet_type_11_verifies_with_11(client, auth_headers, fake_provider):
    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    # callback_payload defaults to the attempt's ticket type 11 == Wallet
    r = client.post(CALLBACK, data=callback_payload(attempt, type="11"), follow_redirects=False)
    assert "payment=success" in r.headers["location"]
    assert fake_provider.verify_calls[-1]["type"] == 11


# ══════════════════════════════════════════════════════════════════════
# I2 — bounded staff reconciliation of stuck attempts
# ══════════════════════════════════════════════════════════════════════

def test_staff_reconcile_after_transient_verify_settles(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from app.services.digipay import DigiPayError
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    fake_provider.verify_error = DigiPayError("timeout")
    client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"        # preserved, NOT failed by timeout
        assert row.payment_method == 0
        assert row.tracking_code == "TRK-1"
    finally:
        db.close()

    fake_provider.verify_error = None
    r = client.post(f"{BASE}/staff/payments/{attempt.id}/reconcile", json={"action": "verify"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "verified"
    assert fake_provider.verify_calls[-1]["type"] == 0   # method, not the ticket type

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "paid"
    finally:
        db.close()


def test_reconcile_without_callback_never_guesses_method(client, auth_headers, fake_provider):
    """A pending attempt with no callback must not be verified with type=11."""
    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(f"{BASE}/staff/payments/{attempt.id}/reconcile", json={"action": "verify"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "pending"        # held open, never auto-failed
    assert fake_provider.verify_calls == []      # method unknown → no provider call


def test_reconcile_abandon_releases_invoice_lock(client, auth_headers, fake_provider):
    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "abandon", "reason": "customer cancelled"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "failed"
    # The invoice is no longer locked: a fresh attempt can start.
    assert pay(client, token).status_code == 200


def test_staff_list_stuck_attempts_is_bounded_and_auth_gated(client, auth_headers, fake_provider):
    from app.services.digipay import DigiPayError

    fake_provider.create_error = DigiPayError("network down")
    invoice_id, token = make_approved(client, auth_headers)
    assert pay(client, token).status_code in (502, 503)
    stuck = latest_attempt(invoice_id)

    assert client.get(f"{BASE}/staff/payments").status_code in (401, 403)  # no auth
    r = client.get(f"{BASE}/staff/payments", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(a["id"] == stuck.id for a in r.json())


def test_reconcile_rejects_unknown_action(client, auth_headers, fake_provider):
    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(f"{BASE}/staff/payments/{attempt.id}/reconcile", json={"action": "nuke"}, headers=auth_headers)
    assert r.status_code == 422


def test_reconcile_missing_attempt_404(client, auth_headers, fake_provider):
    r = client.post(f"{BASE}/staff/payments/999999/reconcile", json={"action": "abandon"}, headers=auth_headers)
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# N1 — untrusted callbacks must not terminally fail or unlock a payment
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "override",
    [
        {"type": "5"},      # unsupported credit method (untrusted callback signal)
        {"amount": "1"},    # callback amount mismatch (untrusted callback signal)
    ],
)
def test_untrusted_callback_keeps_lock_and_blocks_second_payment(client, auth_headers, fake_provider, override):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt, **override), follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "payment=success" not in r.headers["location"]
    # Unsupported/mismatched callbacks never trigger a provider verify.
    assert fake_provider.verify_calls == []

    # The attempt stays active (unknown) → the invoice lock is held, so a second
    # pay click resumes the same session instead of starting a second payment.
    second = pay(client, token)
    assert second.status_code == 200, second.text
    assert second.json()["redirect_url"] == attempt.redirect_url

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"   # never paid
        rows = db.query(CommercePaymentAttempt).filter_by(invoice_id=invoice_id).all()
        assert len(rows) == 1                                            # no 2nd attempt
        assert rows[0].state == "unknown"
    finally:
        db.close()

    # Staff can see the held attempt for manual reconciliation.
    listing = client.get(f"{BASE}/staff/payments", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    surfaced = [a for a in listing.json() if a["id"] == attempt.id]
    assert len(surfaced) == 1
    assert surfaced[0]["state"] == "unknown"


def test_callback_amount_mismatch_does_not_poison_identity(client, auth_headers, fake_provider):
    """A callback that lies about the amount must not pin method/tracking."""
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    client.post(CALLBACK, data=callback_payload(attempt, amount="1"), follow_redirects=False)

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"          # held, never failed
        assert row.payment_method is None      # untrusted hint not persisted
        assert row.tracking_code is None
    finally:
        db.close()

    # With no trusted identity, staff reconcile cannot verify and must hold —
    # an untrusted callback never releases the invoice lock.
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "unknown"
    assert fake_provider.verify_calls == []

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()


def test_forged_callback_cannot_overwrite_pinned_identity(client, auth_headers, fake_provider):
    """A genuine callback's method/tracking, once pinned, is never overwritten.

    ``providerId`` is exposed in the redirect URL, so an attacker can POST the
    callback endpoint directly. That forged callback must not replace the
    method/tracking a real callback pinned, and must not fail/unlock the attempt.
    """
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from app.services.digipay import DigiPayError
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)

    # Genuine IPG (type=0) callback pins method=0 / tracking=TRK-1; the verify
    # times out, so the attempt is held (unknown) with its identity pinned.
    fake_provider.verify_error = DigiPayError("timeout")
    client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"
        assert row.payment_method == 0
        assert row.tracking_code == "TRK-1"
    finally:
        db.close()

    # A forged callback (attacker-chosen wallet type + tracking) must not
    # overwrite the pinned identity, nor move the attempt to failed.
    forged = callback_payload(attempt, type="11", trackingCode="FORGED")
    r = client.post(CALLBACK, data=forged, follow_redirects=False)
    assert "payment=success" not in r.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.payment_method == 0        # unchanged
        assert row.tracking_code == "TRK-1"   # unchanged
        assert row.state == "unknown"         # still held
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()

    # Once the provider recovers, staff reconcile verifies with the *pinned*
    # identity — never the forged values.
    fake_provider.verify_error = None
    r2 = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "verified"
    assert fake_provider.verify_calls[-1] == {
        "tracking_code": "TRK-1", "provider_id": attempt.provider_id, "type": 0,
    }


def test_forged_first_callback_does_not_block_genuine_settlement(client, auth_headers, fake_provider):
    """A forged callback arriving FIRST must not pin authority nor block the real one.

    ``providerId`` is exposed in the redirect, so an attacker can POST a
    self-consistent callback (matching amount, supported type, any bogus
    tracking) before the customer's genuine one. That forged hint must (a) not
    terminally fail/unlock the attempt and (b) not prevent the later genuine
    callback — carrying the real tracking code — from settling exactly once.
    """
    from app.models import CommerceInvoice, CommercePaymentAttempt, Order
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    real_amount = attempt.amount_rial

    # The provider only recognises the tracking code it actually issued; any
    # other code gets a non-success with no providerId/amount linkage (so it is
    # not authoritative for our ticket).
    def scripted_verify(*, tracking_code, provider_id, type):
        fake_provider.verify_calls.append(
            {"tracking_code": tracking_code, "provider_id": provider_id, "type": type}
        )
        if tracking_code == "TRK-REAL":
            return {
                "result": {"status": 0},
                "trackingCode": tracking_code,
                "providerId": provider_id,
                "amount": real_amount,
            }
        return {"result": {"status": 4, "message": "transaction not found"}}

    fake_provider.verify = scripted_verify

    # Forged callback FIRST (attacker-chosen bogus tracking code).
    r_forged = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="FORGED"),
        follow_redirects=False,
    )
    assert "payment=success" not in r_forged.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"                                  # held, never failed
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # lock held
    finally:
        db.close()

    # The invoice is still locked: a second pay click resumes the same session.
    second = pay(client, token)
    assert second.status_code == 200, second.text
    assert second.json()["redirect_url"] == attempt.redirect_url

    # The GENUINE callback now arrives with the real tracking code.
    r_real = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="TRK-REAL"),
        follow_redirects=False,
    )
    assert "payment=success" in r_real.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "verified"
        assert row.tracking_code == "TRK-REAL"          # confirmed identity recorded
        assert db.get(CommerceInvoice, invoice_id).state == "paid"
        assert db.query(Order).count() == 1             # settled exactly once
    finally:
        db.close()

    # Replay of the genuine callback stays idempotent (no second order).
    replay = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="TRK-REAL"),
        follow_redirects=False,
    )
    assert "payment=success" in replay.headers["location"]
    db = TestSessionLocal()
    try:
        assert db.query(Order).count() == 1
    finally:
        db.close()


def test_callback_non_success_for_callback_supplied_tracking_keeps_lock(client, auth_headers, fake_provider):
    """A provider non-success tied ONLY to a callback tracking must not fail/unlock.

    The tracking code was supplied by an untrusted (possibly forged) callback, so
    the provider's "not found" says nothing about the invoice we issued. The
    attempt must stay active and its lock held — and staff reconcile must not be
    able to conclude a failure from it either.
    """
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    # Explicit non-success, but with no providerId/amount linkage to our ticket.
    fake_provider.verify = lambda **kw: {"result": {"status": 5, "message": "not found"}}
    r = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="BOGUS"),
        follow_redirects=False,
    )
    assert "payment=success" not in r.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"                                  # held, NOT failed
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # lock held
    finally:
        db.close()

    # Staff reconcile cannot conclude a failure from a non-authoritative reply.
    r2 = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "unknown"

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"   # still locked
    finally:
        db.close()

    # The lock is intact: a second pay click resumes the same payment session.
    assert pay(client, token).json()["redirect_url"] == attempt.redirect_url


def test_reconcile_unknown_verify_response_does_not_unlock(client, auth_headers, fake_provider):
    """An unrecognized/identity-mismatched verify reply is not a failure."""
    from app.models import CommerceInvoice
    from app.services.digipay import DigiPayError
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    # Pin a trusted identity via a genuine callback whose verify timed out.
    fake_provider.verify_error = DigiPayError("timeout")
    client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)
    fake_provider.verify_error = None

    # Provider answers with no recognized status → cannot conclude a failure.
    fake_provider.verify = lambda **kw: {"foo": "bar"}
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "unknown"          # held, NOT failed
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"   # lock held
    finally:
        db.close()

    # A provider "success" whose identity does not match is equally not a failure.
    fake_provider.verify = lambda **kw: {
        "result": {"status": 0},
        "amount": attempt.amount_rial,
        "providerId": "someone-else",
    }
    r2 = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "unknown"
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()


def test_reconcile_provider_confirmed_non_success_fails(client, auth_headers, fake_provider):
    """Only a provider-confirmed non-success tied to the issued ticket closes it."""
    from app.services.digipay import DigiPayError

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    fake_provider.verify_error = DigiPayError("timeout")
    client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)
    fake_provider.verify_error = None
    # An *authoritative* terminal non-success: the reply is explicitly tied to
    # the ticket we issued (echoes our unique providerId and the issued amount).
    fake_provider.verify = lambda **kw: {
        "result": {"status": 5},
        "trackingCode": "TRK-1",
        "providerId": attempt.provider_id,
        "amount": attempt.amount_rial,
    }
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "failed"


def test_reconcile_non_authoritative_non_success_keeps_lock(client, auth_headers, fake_provider):
    """A non-success resting only on a callback-supplied tracking must hold.

    The reply carries no ``providerId``/``amount`` linkage to the issued ticket,
    so it says nothing about our attempt — the lock must stay held (no unlock).
    """
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from app.services.digipay import DigiPayError
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    fake_provider.verify_error = DigiPayError("timeout")
    client.post(CALLBACK, data=callback_payload(attempt, type="0"), follow_redirects=False)
    fake_provider.verify_error = None
    # Explicit non-success, but only the callback tracking links it to us.
    fake_provider.verify = lambda **kw: {"result": {"status": 5, "message": "not found"}}
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "unknown"        # held, NOT failed
    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"   # lock held
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"
    finally:
        db.close()


def test_forged_first_staff_reconcile_echoing_provider_keeps_lock(client, auth_headers, fake_provider):
    """Staff reconcile must not unlock a forged-first attempt on a providerId/amount echo.

    ``providerId`` and ``amount`` are visible in the gateway redirect, so a
    forged, self-consistent callback can pin a bogus tracking code *first*. A
    later staff reconciliation then asks the provider about that bogus tracking;
    the gateway (default fake reply) answers with a terminal **non-success**
    while still echoing our ``providerId`` and ``amount`` — but with no matching
    tracking echo. That is not a proven failure of OUR ticket, so the attempt
    must stay open (invoice lock held). Only once the genuine callback — the one
    carrying the tracking code the gateway actually recognises — arrives does the
    attempt settle, exactly once.
    """
    from app.models import CommerceInvoice, CommercePaymentAttempt, Order
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)

    # The gateway reports a terminal non-success for a tracking code it does not
    # hold, yet still echoes the providerId/amount of the ticket it recognises.
    fake_provider.verify_status = 4

    # Forged callback FIRST: self-consistent (matching amount, supported type)
    # but an attacker-chosen bogus tracking code.
    r_forged = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="FORGED"),
        follow_redirects=False,
    )
    assert "payment=success" not in r_forged.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"                                   # held, never failed
        assert row.tracking_code == "FORGED"                            # provisional hint only
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # lock held
    finally:
        db.close()

    # Staff reconcile of the still-bogus hint must NOT release the lock merely
    # because the provider echoed our providerId/amount.
    r_rec = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert r_rec.status_code == 200, r_rec.text
    assert r_rec.json()["state"] == "unknown"                           # NOT failed

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "unknown"
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # lock held
    finally:
        db.close()

    # The lock is intact: a second pay click resumes the same payment session.
    assert pay(client, token).json()["redirect_url"] == attempt.redirect_url

    # The GENUINE callback now arrives with the tracking the gateway recognises.
    fake_provider.verify_status = 0
    r_real = client.post(
        CALLBACK,
        data=callback_payload(attempt, type="0", trackingCode="TRK-REAL"),
        follow_redirects=False,
    )
    assert "payment=success" in r_real.headers["location"]

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "verified"
        assert row.tracking_code == "TRK-REAL"          # confirmed identity recorded
        assert db.get(CommerceInvoice, invoice_id).state == "paid"
        assert db.query(Order).count() == 1             # settled exactly once
    finally:
        db.close()


def test_reconcile_abandon_requires_explicit_reason(client, auth_headers, fake_provider):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)

    # No reason → refused, the attempt is NOT silently released.
    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "abandon"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text

    db = TestSessionLocal()
    try:
        row = db.query(CommercePaymentAttempt).filter_by(provider_id=attempt.provider_id).one()
        assert row.state == "pending"                        # untouched
        assert db.get(CommerceInvoice, invoice_id).state == "approved"
    finally:
        db.close()

    # A whitespace-only reason is equally refused.
    r2 = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "abandon", "reason": "   "},
        headers=auth_headers,
    )
    assert r2.status_code == 422, r2.text


def test_staff_list_exposes_min_age_seconds(client, auth_headers, fake_provider):
    from app.services.digipay import DigiPayError

    fake_provider.create_error = DigiPayError("network down")
    invoice_id, token = make_approved(client, auth_headers)
    assert pay(client, token).status_code in (502, 503)
    stuck = latest_attempt(invoice_id)

    # A fresh attempt is excluded by a large min-age floor...
    r = client.get(
        f"{BASE}/staff/payments",
        params={"min_age_seconds": 3600},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert all(a["id"] != stuck.id for a in r.json())
    # ...and included without one.
    r2 = client.get(f"{BASE}/staff/payments", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    assert any(a["id"] == stuck.id for a in r2.json())


# ══════════════════════════════════════════════════════════════════════
# I1/I2 — settlement binding + reconciliation queue
#
# A genuine, server-verified payment must never settle an invoice it was not
# issued for. If the attempt's revision/amount no longer match the *current*
# invoice, or the invoice is no longer payable (revoked/revised), the callback
# must NOT 500, must NOT mark the invoice paid, and must preserve the verified
# evidence (state=verified + tracking/verified_at) in the staff reconciliation
# queue (``reconciliation_required``) — never silently drop it.
# ══════════════════════════════════════════════════════════════════════

def _mutate_invoice(invoice_id, *, revision_delta=0, total_delta=0, state=None):
    """Move an invoice out from under an already-issued attempt."""
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        inv = db.get(CommerceInvoice, invoice_id)
        if revision_delta:
            inv.revision = (inv.revision or 1) + revision_delta
        if total_delta:
            inv.total_toman = inv.total_toman + total_delta
        if state is not None:
            inv.state = state
        db.commit()
    finally:
        db.close()


def _pin_attempt_identity(attempt_id, *, method=11, tracking="TRK-1"):
    """Give an attempt the provider-verifiable identity a real callback pins."""
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        a = db.get(CommercePaymentAttempt, attempt_id)
        a.payment_method = method
        a.tracking_code = tracking
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    "mutate",
    [
        {"revision_delta": 1},                      # revision moved on
        {"total_delta": 50000},                     # same revision, re-priced
        {"revision_delta": 1, "total_delta": 50000},
    ],
)
def test_stale_genuine_callback_never_settles_current_invoice(
    client, auth_headers, fake_provider, mutate
):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    _mutate_invoice(invoice_id, **mutate)

    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    location = r.headers["location"]
    assert "payment=pending" in location
    assert "payment=success" not in location
    assert token not in location

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # never paid
        refreshed = (
            db.query(CommercePaymentAttempt)
            .filter_by(provider_id=attempt.provider_id)
            .one()
        )
        # Verified evidence preserved and explicitly queued for staff.
        assert refreshed.state == "verified"
        assert refreshed.reconciliation_required is True
        assert refreshed.tracking_code == "TRK-1"
        assert refreshed.verified_at is not None
    finally:
        db.close()

    listing = client.get(
        f"{BASE}/staff/payments",
        params={"needs_reconciliation": "true"},
        headers=auth_headers,
    )
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()}
    assert attempt.id in rows
    assert rows[attempt.id]["reconciliation_required"] is True
    assert rows[attempt.id]["state"] == "verified"


def test_revoked_invoice_verified_payment_preserved_and_queued(
    client, auth_headers, fake_provider
):
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    # Simulate a revoke that landed after the gateway session went live but
    # before its callback (attempt still pending/locked).
    _mutate_invoice(invoice_id, state="revoked")

    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    assert "payment=pending" in r.headers["location"]
    assert "payment=success" not in r.headers["location"]

    db = TestSessionLocal()
    try:
        inv = db.get(CommerceInvoice, invoice_id)
        assert inv.state == "revoked"        # never flipped to paid
        assert inv.order_id is None          # no order fabricated
        refreshed = (
            db.query(CommercePaymentAttempt)
            .filter_by(provider_id=attempt.provider_id)
            .one()
        )
        assert refreshed.state == "verified"
        assert refreshed.reconciliation_required is True
        assert refreshed.tracking_code == "TRK-1"
        assert refreshed.last_error and "not payable" in refreshed.last_error
    finally:
        db.close()

    # Must remain visible in the DEFAULT staff queue (not disappear).
    default_list = client.get(f"{BASE}/staff/payments", headers=auth_headers)
    assert default_list.status_code == 200, default_list.text
    assert attempt.id in {row["id"] for row in default_list.json()}


def test_staff_reconcile_of_stale_verified_payment_flags_not_settles(
    client, auth_headers, fake_provider
):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    _pin_attempt_identity(attempt.id)           # callback pinned IPG identity
    _mutate_invoice(invoice_id, revision_delta=1, total_delta=50000)

    r = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify", "reason": ""},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reconciliation_required"] is True
    assert body["state"] == "verified"
    assert body["tracking_code"] == "TRK-1"

    db = TestSessionLocal()
    try:
        assert db.get(CommerceInvoice, invoice_id).state == "approved"  # not paid
    finally:
        db.close()


def test_callback_never_500s_when_handler_raises(client, fake_provider, monkeypatch):
    from app.services import commerce as commerce_service

    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected settlement error")

    monkeypatch.setattr(commerce_service, "handle_digipay_callback", _boom)
    r = client.post(
        CALLBACK,
        data={
            "providerId": "p",
            "amount": "1",
            "type": "11",
            "result": "SUCCESS",
            "trackingCode": "t",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert "payment=pending" in r.headers["location"]


def test_settled_attempt_is_not_flagged_for_reconciliation(
    client, auth_headers, fake_provider
):
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    invoice_id, token, attempt = _pay_and_get_attempt(client, auth_headers, fake_provider)
    r = client.post(CALLBACK, data=callback_payload(attempt), follow_redirects=False)
    assert "payment=success" in r.headers["location"]

    db = TestSessionLocal()
    try:
        refreshed = (
            db.query(CommercePaymentAttempt)
            .filter_by(provider_id=attempt.provider_id)
            .one()
        )
        assert refreshed.state == "verified"
        assert not refreshed.reconciliation_required
    finally:
        db.close()

    only = client.get(
        f"{BASE}/staff/payments",
        params={"needs_reconciliation": "true"},
        headers=auth_headers,
    )
    assert only.status_code == 200, only.text
    assert attempt.id not in {row["id"] for row in only.json()}
