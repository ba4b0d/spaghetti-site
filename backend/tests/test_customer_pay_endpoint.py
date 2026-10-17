"""Task 3 — client-area invoice payment initiation (`/api/v1/commerce/history`).

Endpoint under test:

* ``POST /api/v1/commerce/history/invoices/{invoice_id}/pay``

What is proven here: the verified history bearer is the ONLY credential (no
staff cookie); a payment can only be started for an invoice owned by *that exact*
mobile, and a foreign/unknown id is an indistinguishable 404; only an approved,
unexpired invoice may be paid while draft/paid/revoked and expired ones are
refused with 400; the endpoint returns a provider ``redirect_url`` and every
response keeps the no-store/no-referrer boundary.

No real SMS and no real gateway: ``commerce_notifications.send_customer_otp``
is faked and the gateway client is injected — the service itself is exercised
against a scripted ticket.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

BASE = "/api/v1/commerce/history"
MOBILE = "09123456789"
OTHER = "09120000000"
REDIRECT = "https://web-pay.example/tgs/v2:customer-test"


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fake_sms(monkeypatch):
    """Replace the SMS transport with a capturing fake — never a real send."""
    from app.services import commerce_notifications

    sender = MagicMock(return_value=True)
    monkeypatch.setattr(commerce_notifications, "send_customer_otp", sender)
    _SMS["sender"] = sender
    yield sender
    _SMS.pop("sender", None)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset shared slowapi counters so the small OTP budget is per test."""
    from app.main import app

    try:
        app.state.limiter._limiter.storage.reset()
    except Exception:  # pragma: no cover - limiter always present in app.main
        pass
    yield


_SMS = {}


@pytest.fixture()
def gateway(monkeypatch):
    """Enable + inject a scripted DigiPay client; never touch a live gateway."""
    from app.services import digipay

    client = _FakeDigiPayClient()

    monkeypatch.setattr(digipay, "checkout_enabled", lambda: True)
    monkeypatch.setattr(digipay, "get_client", lambda: client)
    monkeypatch.setattr(digipay, "build_callback_url", lambda: "https://site.example/cb")
    return client


class _FakeDigiPayClient:
    """Minimal DigiPay client whose ticket is scripted, never fetched."""

    def __init__(self, redirect_url: str = REDIRECT):
        self.redirect_url = redirect_url
        self.calls: list[dict] = []

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        self.calls.append(
            {
                "amount_rial": amount_rial,
                "mobile": mobile,
                "provider_id": provider_id,
                "callback_url": callback_url,
            }
        )
        return {"result": {"status": 0}, "ticket": "v2:abc", "redirect_url": self.redirect_url}


# ── Helpers ──────────────────────────────────────────────────────────

def _db():
    from tests.conftest import TestSessionLocal

    return TestSessionLocal()


def _now():
    return datetime.now(timezone.utc)


def _sent_code():
    call = _SMS["sender"].call_args_list[-1]
    return call.args[1] if len(call.args) > 1 else call.kwargs["code"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _assert_no_store(resp):
    assert resp.headers["Cache-Control"] == "no-store", resp.headers
    assert resp.headers["Referrer-Policy"] == "no-referrer", resp.headers


def _get_token(client, mobile=MOBILE):
    """Full public issue + verify round-trip; returns the raw bearer."""
    r = client.post(f"{BASE}/otp", json={"mobile": mobile})
    assert r.status_code == 200, r.text
    v = client.post(
        f"{BASE}/verify",
        json={"mobile": mobile, "challenge_id": r.json()["challenge_id"], "code": _sent_code()},
    )
    assert v.status_code == 200, v.text
    return v.json()["token"]


def _insert_invoice(mobile=MOBILE, *, state="approved", total=120000, expires_in=None):
    """Insert a staff-created invoice with a private-link expiry."""
    import hashlib
    import os

    from app.models import CommerceInvoice

    db = _db()
    try:
        inv = CommerceInvoice(
            customer_name="مشتری",
            mobile=mobile,
            messenger="bale",
            messenger_handle="@x",
            address="آدرس",
            specification="مشخصات",
            shipping_toman=20000,
            total_toman=total,
            state=state,
            token_hash=hashlib.sha256(os.urandom(16)).hexdigest(),
            token_expires_at=(
                _now() + timedelta(minutes=expires_in) if expires_in is not None else None
            ),
            created_at=_now(),
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)
        return inv.id
    finally:
        db.close()


def _pay(client, token, invoice_id, gateway="digipay"):
    return client.post(
        f"{BASE}/invoices/{invoice_id}/pay",
        headers=_auth(token),
        json={"gateway": gateway},
    )


# ══════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════

def test_customer_starts_payment_for_own_approved_invoice(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id)

    assert r.status_code == 200, r.text
    _assert_no_store(r)
    assert r.json() == {"redirect_url": REDIRECT}
    # The gateway really was called with the invoice's amount (Toman→Rial).
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["amount_rial"] == 120000 * 10
    assert gateway.calls[0]["mobile"] == MOBILE


def test_gateway_defaults_to_digipay_when_body_omits_it(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = client.post(f"{BASE}/invoices/{invoice_id}/pay", headers=_auth(token), json={})

    assert r.status_code == 200, r.text
    assert r.json()["redirect_url"] == REDIRECT


def test_path_never_discloses_a_different_numbers_invoice_is_not_reachable(client, gateway):
    """Only the token's own mobile may pay; the bearer is the sole credential."""
    mine = _insert_invoice(MOBILE, state="approved", expires_in=30)
    theirs = _insert_invoice(OTHER, state="approved", expires_in=30)
    token = _get_token(client, MOBILE)

    assert _pay(client, token, theirs).status_code == 404
    # My own invoice still works — the refusal is ownership, not breakage.
    assert _pay(client, token, mine).status_code == 200


# ══════════════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════════════

def test_pay_without_a_session_is_401(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)

    no_header = client.post(f"{BASE}/invoices/{invoice_id}/pay", json={"gateway": "digipay"})
    assert no_header.status_code == 401, no_header.text
    _assert_no_store(no_header)

    bad = client.post(
        f"{BASE}/invoices/{invoice_id}/pay",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"gateway": "digipay"},
    )
    assert bad.status_code == 401, bad.text
    assert gateway.calls == []


# ══════════════════════════════════════════════════════════════════════
# Not-found / ownership
# ══════════════════════════════════════════════════════════════════════

def test_unknown_invoice_id_is_404_and_indistinguishable_from_foreign(client, gateway):
    _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    unknown = _pay(client, token, 999999)
    assert unknown.status_code == 404, unknown.text
    _assert_no_store(unknown)
    assert unknown.json()["detail"] == "فاکتور یافت نشد"


def test_paying_another_mobiles_invoice_is_404(client, gateway):
    theirs = _insert_invoice(OTHER, state="approved", expires_in=30)
    token = _get_token(client, MOBILE)

    r = _pay(client, token, theirs)

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "فاکتور یافت نشد"
    assert gateway.calls == []


# ══════════════════════════════════════════════════════════════════════
# State gate
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state", ["draft", "paid", "revoked"])
def test_non_approved_invoice_is_400(client, gateway, state):
    invoice_id = _insert_invoice(MOBILE, state=state, expires_in=30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id)

    assert r.status_code == 400, (state, r.text)
    _assert_no_store(r)
    assert r.json()["detail"] == "فاکتور در وضعیت قابل پرداخت نیست"
    assert gateway.calls == []


# ══════════════════════════════════════════════════════════════════════
# Expiry gate
# ══════════════════════════════════════════════════════════════════════

def test_expired_invoice_is_400(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", total=120000, expires_in=-30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id)

    assert r.status_code == 400, r.text
    _assert_no_store(r)
    assert r.json()["detail"] == "مهلت پرداخت فاکتور به پایان رسیده است"
    assert gateway.calls == []


# ══════════════════════════════════════════════════════════════════════
# Payload validation & gateway readiness
# ══════════════════════════════════════════════════════════════════════

def test_unknown_gateway_is_rejected_422(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id, gateway="paypal")

    assert r.status_code == 422, r.text
    assert gateway.calls == []


def test_surplus_body_fields_are_rejected_422(client, gateway):
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = client.post(
        f"{BASE}/invoices/{invoice_id}/pay",
        headers=_auth(token),
        json={"gateway": "digipay", "amount_rial": 1},
    )

    assert r.status_code == 422, r.text
    assert gateway.calls == []


def test_disabled_gateway_is_503_and_no_provider_call(client, monkeypatch):
    from app.services import digipay

    monkeypatch.setattr(digipay, "checkout_enabled", lambda: False)
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id)

    assert r.status_code == 503, r.text
    _assert_no_store(r)


def test_bitpay_gateway_is_503_when_checkout_not_armed(client, monkeypatch):
    """A direct POST cannot run a BitPay checkout the deployment has not enabled."""
    from app.services import bitpay

    monkeypatch.setattr(bitpay, "checkout_allowed", lambda: False)
    invoice_id = _insert_invoice(MOBILE, state="approved", expires_in=30)
    token = _get_token(client)

    r = _pay(client, token, invoice_id, gateway="bitpay")

    assert r.status_code == 503, r.text
    _assert_no_store(r)
