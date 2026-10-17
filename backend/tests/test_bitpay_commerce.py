"""Task 2 — BitPay gateway v2.2 commerce wiring (backend only).

Three layers are covered, all offline (no live/sandbox call):

* the provider-explicit initiation endpoint ``POST
  /api/v1/commerce/invoices/{token}/pay/bitpay`` and its durable attempt;
* the dedicated ``GET /api/v1/commerce/bitpay/callback`` — untrusted
  ``trans_id``/``id_get`` query, server-to-server verify, amount+factorId+
  revision matching, idempotency, forgery/duplicate/timeout/stale handling;
* the access-log protection (nginx config + uvicorn query redaction) that keeps
  the callback query out of every log.

The provider is injected through the ``bitpay.client_dependency`` FastAPI
override, exactly as the DigiPay suite injects its fake; every response is
scripted and no socket is opened.
"""
import logging
import re

import pytest

BASE = "/api/v1/commerce"
BITPAY_CALLBACK = f"{BASE}/bitpay/callback"
BITPAY_CB_PATH = "/api/v1/commerce/bitpay/callback"

# The documented gateway ``factorId`` is a Latin integer only.
_LATIN_DECIMAL = re.compile(r"[0-9]+")


@pytest.fixture(autouse=True)
def reset_limits(client):
    from app.main import app

    app.state.limiter._limiter.storage.reset()


# ══════════════════════════════════════════════════════════════════════
# Fake BitPay provider (real adapter dataclasses; no network)
# ══════════════════════════════════════════════════════════════════════

class FakeBitPay:
    """Records calls; scripts create/verify outcomes for the service layer.

    Uses the adapter's own ``BitPaySession`` / ``BitPayVerification`` shapes so
    the service is exercised against the documented payload, not a simplified
    fake. By default ``verify`` succeeds and echoes the amount + factorId it was
    given at create time (a real gateway echoes both).
    """

    def __init__(self):
        self.id_get = 987654
        self.redirect_url = f"https://bitpay.ir/payment/gateway-{self.id_get}-get"
        self.sessions = {}          # id_get -> {factor_id, amount_rial, callback_url}
        self.verify_calls = []
        self.create_error = None
        self.verify_error = None
        self.verify_status = 1       # 1 = fresh success, 11 = already verified
        self.amount_override = None  # force a (wrong) echoed amount
        self.factor_override = None  # force a (wrong/absent) echoed factorId

    def create_payment(
        self, *, amount_rial, redirect_url, factor_id=None, name=None,
        email=None, description=None, mobile=None, card_num=None,
    ):
        if self.create_error:
            raise self.create_error
        self.sessions[self.id_get] = {
            "factor_id": factor_id,
            "amount_rial": amount_rial,
            "callback_url": redirect_url,
        }
        from app.services.bitpay import BitPaySession

        return BitPaySession(id_get=self.id_get, redirect_url=self.redirect_url, factor_id=factor_id)

    def verify(self, *, trans_id, id_get):
        if self.verify_error:
            raise self.verify_error
        self.verify_calls.append({"trans_id": trans_id, "id_get": id_get})
        sess = self.sessions.get(id_get, {})
        amount = self.amount_override if self.amount_override is not None else sess.get("amount_rial")
        factor = self.factor_override if self.factor_override is not None else sess.get("factor_id")
        # Documented BitPay behaviour: a ``factorId`` that is not a Latin-decimal
        # integer is silently coerced to ``0`` on the verify reply. This is the
        # exact silent coercion that broke matching of the historical alnum
        # ``INV<id>-R<rev>-<hex>`` merchant reference.
        if factor is not None and not _LATIN_DECIMAL.fullmatch(str(factor).strip()):
            factor = "0"
        from app.services.bitpay import BitPayVerification

        return BitPayVerification(
            status=self.verify_status,
            is_success=self.verify_status in (1, 11),
            already_verified=self.verify_status == 11,
            amount_rial=amount,
            card_num="6037990000001234",
            factor_id=factor,
        )


@pytest.fixture()
def fake_bitpay(client, monkeypatch):
    from app.main import app
    from app.services import bitpay

    # The initiation route enforces the *same* Task-4 sandbox gate as the public
    # readiness snapshot (see the gate tests below), so the offline fake is only
    # usable from a fully-formed, non-production test deployment — the exact
    # shape the gate requires. This is test-environment *configuration*, not a
    # bypass: the production condition is still evaluated on every request, and
    # the injected client never short-circuits it.
    monkeypatch.setenv("BITPAY_API_KEY", "sk_test_offline-fake-not-a-real-key")
    monkeypatch.setenv("BITPAY_ENV", "test")
    monkeypatch.setenv("BITPAY_ENABLE_TEST_CHECKOUT", "1")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "https://staging.spaghettiprints.ir")

    fake = FakeBitPay()
    app.dependency_overrides[bitpay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(bitpay.client_dependency, None)


# ══════════════════════════════════════════════════════════════════════
# Helpers
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


def bitpay_pay(client, token):
    return client.post(f"{BASE}/invoices/{token}/pay/bitpay")


def bitpay_callback(client, *, trans_id, id_get, factor_id=None):
    params = {"trans_id": trans_id, "id_get": id_get}
    if factor_id is not None:
        params["factorId"] = factor_id
    return client.get(BITPAY_CALLBACK, params=params, follow_redirects=False)


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


def invoice_state(invoice_id):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return db.get(CommerceInvoice, invoice_id).state
    finally:
        db.close()


def order_for(invoice_id):
    from app.models import CommerceInvoice, Order
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        inv = db.get(CommerceInvoice, invoice_id)
        return db.get(Order, inv.order_id) if inv.order_id else None
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Initiation — POST /invoices/{token}/pay/bitpay
# ══════════════════════════════════════════════════════════════════════

def test_bitpay_pay_returns_redirect_and_durable_attempt(client, auth_headers, fake_bitpay):
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "bitpay"
    assert body["redirect_url"] == fake_bitpay.redirect_url

    attempt = latest_attempt(invoice_id)
    assert attempt is not None
    assert attempt.provider == "bitpay"
    assert attempt.state == "pending"
    assert attempt.amount_rial == 3120000            # 312000 toman * 10, exactly once
    assert attempt.invoice_revision == 1
    assert attempt.type == 0                          # BitPay sentinel (no UPG ticket type)
    assert attempt.redirect_url == fake_bitpay.redirect_url
    # the id_get the callback will be matched on is durably persisted
    assert attempt.tracking_code == str(fake_bitpay.id_get)
    assert fake_bitpay.sessions[fake_bitpay.id_get]["factor_id"] == attempt.provider_id
    # the outbound factorId is the attempt's own Latin-decimal id (the documented
    # gateway integer), persisted as the expected reference in provider_id
    assert _LATIN_DECIMAL.fullmatch(str(attempt.provider_id))
    assert attempt.provider_id == str(attempt.id)
    assert str(fake_bitpay.sessions[fake_bitpay.id_get]["factor_id"]) == str(attempt.id)


def test_bitpay_pay_repeat_clicks_are_idempotent(client, auth_headers, fake_bitpay):
    invoice_id, token = make_approved(client, auth_headers)
    first = bitpay_pay(client, token).json()["redirect_url"]
    second = bitpay_pay(client, token).json()["redirect_url"]
    assert first == second
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        count = (
            db.query(CommercePaymentAttempt)
            .filter(CommercePaymentAttempt.invoice_id == invoice_id)
            .count()
        )
    finally:
        db.close()
    assert count == 1


def test_bitpay_pay_rejected_for_draft_expired_and_paid(client, auth_headers, fake_bitpay):
    from datetime import datetime, timedelta, timezone

    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    assert bitpay_pay(client, "not-a-real-token").status_code == 404

    invoice_id, token = make_approved(client, auth_headers)
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id).token_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        db.commit()
    finally:
        db.close()
    assert bitpay_pay(client, token).status_code == 410

    invoice_id2, token2 = make_approved(client, auth_headers)
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id2).state = "paid"
        db.commit()
    finally:
        db.close()
    assert bitpay_pay(client, token2).status_code == 409


def test_bitpay_pay_without_configuration_returns_503(client, auth_headers, monkeypatch):
    _, token = make_approved(client, auth_headers)
    for var in ("BITPAY_API_KEY", "BITPAY_ENV", "BITPAY_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    from app.main import app
    from app.services import bitpay

    app.dependency_overrides.pop(bitpay.client_dependency, None)
    assert bitpay_pay(client, token).status_code in (502, 503)


def test_bitpay_pay_gateway_failure_leaves_recoverable_unknown(client, auth_headers, fake_bitpay):
    from app.services.bitpay import BitPayError

    fake_bitpay.create_error = BitPayError("network down")
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code in (502, 503)
    attempt = latest_attempt(invoice_id)
    assert attempt.state == "unknown"
    assert attempt.redirect_url is None
    assert attempt.tracking_code is None             # never reached the gateway id_get


def test_bitpay_pay_sets_no_store_headers(client, auth_headers, fake_bitpay):
    _, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_bitpay_pay_composes_https_callback_url(client, auth_headers, fake_bitpay, monkeypatch):
    # The gate now requires a non-production PUBLIC_SITE_ORIGIN, so the callback
    # is (and must be) composed from that validated origin rather than the
    # production default; the composition + HTTPS guarantee is what this pins.
    monkeypatch.delenv("BITPAY_CALLBACK_URL", raising=False)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "https://staging.spaghettiprints.ir")
    _, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 200
    from app.services import bitpay

    recorded = next(iter(fake_bitpay.sessions.values()))
    assert recorded["callback_url"] == "https://staging.spaghettiprints.ir" + bitpay.CALLBACK_PATH
    assert recorded["callback_url"].startswith("https://")


# ── Task 4 (fix) — the sandbox gate is enforced at *initiation* ──────
#
# Readiness hiding the CTA is not enough: the provider-explicit initiation
# endpoint is public and unauthenticated, so a direct POST must be refused just
# like the UI surface. These tests inject the offline fake (no socket) yet still
# expect the gate to win, proving an injected provider cannot bypass it.

def _production_style_env(monkeypatch, *, origin="https://spaghettiprints.ir", flag="1"):
    """A production host carrying an accidentally-copied sandbox key + test env.

    Exactly the accident the gate defends against: the key and ``BITPAY_ENV=test``
    are present; only the deployment flags differ per case.
    """
    monkeypatch.setenv("BITPAY_API_KEY", "sk_test_accidentally-copied-to-prod")
    monkeypatch.setenv("BITPAY_ENV", "test")
    if flag is None:
        monkeypatch.delenv("BITPAY_ENABLE_TEST_CHECKOUT", raising=False)
    else:
        monkeypatch.setenv("BITPAY_ENABLE_TEST_CHECKOUT", flag)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", origin)


def test_bitpay_pay_refused_on_production_even_with_key_and_test_env(
    client, auth_headers, fake_bitpay, monkeypatch
):
    """A direct POST cannot execute a sandbox payment on the production host."""
    _production_style_env(monkeypatch, origin="https://spaghettiprints.ir", flag="1")
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code == 503, r.text
    assert _attempt_count(invoice_id) == 0        # no attempt is ever recorded
    assert fake_bitpay.sessions == {}             # the provider was never asked
    assert r.headers["Cache-Control"] == "no-store"


def test_bitpay_pay_refused_for_trailing_dot_production_origin(
    client, auth_headers, fake_bitpay, monkeypatch
):
    """``spaghettiprints.ir.`` resolves to the same production host; it must lose."""
    _production_style_env(monkeypatch, origin="https://spaghettiprints.ir.", flag="1")
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 503
    assert _attempt_count(invoice_id) == 0


def test_bitpay_pay_refused_without_opt_in_flag_on_non_production(
    client, auth_headers, fake_bitpay, monkeypatch
):
    # non-production origin + test env + key, but the dedicated flag is missing
    monkeypatch.delenv("BITPAY_ENABLE_TEST_CHECKOUT", raising=False)
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 503
    assert _attempt_count(invoice_id) == 0


def test_bitpay_pay_allowed_for_valid_non_production_opt_in(
    client, auth_headers, fake_bitpay
):
    """The fixture configures a genuine non-production opt-in test deployment."""
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code == 200, r.text
    assert _attempt_count(invoice_id) == 1


# ── Live checkout activation need not bypass the gate ────────────────
#
# A live checkout is enabled by the *same* shared predicate as the readiness
# snapshot: it needs a production ``BITPAY_ENV``, the production origin, a key
# AND the dedicated ``BITPAY_ENABLE_LIVE_CHECKOUT`` opt-in. Anything less — a
# missing live opt-in, a staging origin, the sandbox opt-in instead — is a 503
# *before* the injected provider is used, exactly like the sandbox gate.

LIVE_FLAG = "BITPAY_ENABLE_LIVE_CHECKOUT"
LIVE_ORIGIN = "https://spaghettiprints.ir"


def _live_env(
    monkeypatch, *, origin=LIVE_ORIGIN, live_flag="1", test_flag=None, env="production"
):
    """Configure a fully-formed live production deployment."""
    monkeypatch.setenv("BITPAY_API_KEY", "sk_live_offline-fake-not-a-real-key")
    monkeypatch.setenv("BITPAY_ENV", env)
    if live_flag is None:
        monkeypatch.delenv(LIVE_FLAG, raising=False)
    else:
        monkeypatch.setenv(LIVE_FLAG, live_flag)
    if test_flag is None:
        monkeypatch.delenv("BITPAY_ENABLE_TEST_CHECKOUT", raising=False)
    else:
        monkeypatch.setenv("BITPAY_ENABLE_TEST_CHECKOUT", test_flag)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", origin)


@pytest.fixture()
def fake_bitpay_live(client, monkeypatch):
    """Offline fake usable from a fully-formed, *production* live deployment."""
    from app.main import app
    from app.services import bitpay

    _live_env(monkeypatch)
    fake = FakeBitPay()
    app.dependency_overrides[bitpay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(bitpay.client_dependency, None)


def test_bitpay_pay_allowed_for_valid_live_production_opt_in(
    client, auth_headers, fake_bitpay_live
):
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "bitpay"
    assert body["redirect_url"] == fake_bitpay_live.redirect_url
    assert _attempt_count(invoice_id) == 1


def test_bitpay_pay_refused_without_live_opt_in(client, auth_headers, fake_bitpay, monkeypatch):
    _live_env(monkeypatch, live_flag=None)
    invoice_id, token = make_approved(client, auth_headers)
    r = bitpay_pay(client, token)
    assert r.status_code == 503, r.text
    assert _attempt_count(invoice_id) == 0
    assert fake_bitpay.sessions == {}
    assert r.headers["Cache-Control"] == "no-store"


def test_bitpay_pay_refused_for_live_env_on_non_production_origin(
    client, auth_headers, fake_bitpay, monkeypatch
):
    _live_env(monkeypatch, origin="https://staging.spaghettiprints.ir")
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 503
    assert _attempt_count(invoice_id) == 0
    assert fake_bitpay.sessions == {}


def test_sandbox_opt_in_never_enables_live_pay(client, auth_headers, fake_bitpay, monkeypatch):
    _live_env(monkeypatch, live_flag=None, test_flag="1")
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 503
    assert _attempt_count(invoice_id) == 0
    assert fake_bitpay.sessions == {}


def test_bitpay_pay_refused_for_misconfigured_env(client, auth_headers, fake_bitpay, monkeypatch):
    _live_env(monkeypatch, env="prodction")
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 503
    assert _attempt_count(invoice_id) == 0
    assert fake_bitpay.sessions == {}


# ══════════════════════════════════════════════════════════════════════
# Callback — GET /bitpay/callback
# ══════════════════════════════════════════════════════════════════════

def _pay_and_attempt(client, auth_headers, fake_bitpay):
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 200
    return invoice_id, token, latest_attempt(invoice_id)


def test_bitpay_callback_success_settles_once_and_links_one_order(client, auth_headers, fake_bitpay):
    invoice_id, token, attempt = _pay_and_attempt(client, auth_headers, fake_bitpay)
    r = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert r.status_code == 303, r.text
    location = r.headers["location"]
    assert "payment=success" in location
    assert token not in location                      # no bearer leak into the redirect
    assert attempt.provider_id not in location

    # the verify call carried the callback trans_id + the persisted id_get
    assert fake_bitpay.verify_calls == [
        {"trans_id": 12345, "id_get": fake_bitpay.id_get}
    ]

    assert invoice_state(invoice_id) == "paid"
    order = order_for(invoice_id)
    assert order is not None
    assert order.paid_amount == 312000
    assert order.status == "new"
    assert "بیت‌پی" in order.notes                    # provider identity preserved
    refreshed = latest_attempt(invoice_id)
    assert refreshed.state == "verified"
    assert refreshed.tracking_code == str(fake_bitpay.id_get)
    assert refreshed.provider_trans_id == 12345


def test_bitpay_callback_duplicate_replay_is_idempotent(client, auth_headers, fake_bitpay):
    invoice_id, _, attempt = _pay_and_attempt(client, auth_headers, fake_bitpay)
    first = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    second = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    assert "payment=success" in first.headers["location"]
    assert "payment=success" in second.headers["location"]

    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        assert invoice.state == "paid"
        orders = db.query(type(invoice)).filter(CommerceInvoice.id == invoice_id).count()
        assert orders == 1                            # exactly one invoice, one order link
        assert invoice.order_id is not None
    finally:
        db.close()


def test_bitpay_callback_unknown_id_get_does_not_settle(client, auth_headers, fake_bitpay):
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    r = bitpay_callback(client, trans_id="1", id_get=424242)   # no such attempt
    assert "payment=failed" in r.headers["location"]
    assert invoice_state(invoice_id) == "approved"
    assert fake_bitpay.verify_calls == []             # never queried for an unknown id


def test_bitpay_callback_missing_params_returns_failed(client, auth_headers, fake_bitpay):
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    r = client.get(BITPAY_CALLBACK, follow_redirects=False)   # no trans_id / id_get
    assert "payment=failed" in r.headers["location"]
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_callback_gateway_error_returns_pending_and_holds_lock(
    client, auth_headers, fake_bitpay
):
    from app.services.bitpay import BitPayError

    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_error = BitPayError("timeout")
    r = bitpay_callback(client, trans_id="7", id_get=fake_bitpay.id_get)
    assert "payment=pending" in r.headers["location"]
    attempt = latest_attempt(invoice_id)
    assert attempt.state == "unknown"                 # lock held, not released
    assert attempt.provider_trans_id == 7             # provisional, for reconcile
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_callback_non_success_status_returns_failed_and_holds_lock(
    client, auth_headers, fake_bitpay
):
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_status = -4                    # transaction not found / unsuccessful
    r = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    assert "payment=failed" in r.headers["location"]
    assert latest_attempt(invoice_id).state == "unknown"
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_callback_amount_mismatch_never_settles(client, auth_headers, fake_bitpay):
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.amount_override = 1                   # self-consistent success, wrong amount
    r = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    assert "payment=failed" in r.headers["location"]
    assert latest_attempt(invoice_id).state == "unknown"
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_callback_factorid_mismatch_never_settles(client, auth_headers, fake_bitpay):
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    # a *different invoice's* numeric factorId: a self-consistent success that
    # must not settle this attempt
    fake_bitpay.factor_override = "999999"
    r = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    assert "payment=failed" in r.headers["location"]
    assert latest_attempt(invoice_id).state == "unknown"
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_pay_sends_latin_decimal_factor_id(client, auth_headers, fake_bitpay):
    """Regression: the outbound ``factorId`` must be the Latin-decimal attempt
    id — the documented integer — never the pre-fix alnum merchant reference."""
    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 200
    attempt = latest_attempt(invoice_id)
    assert _LATIN_DECIMAL.fullmatch(str(attempt.provider_id))
    assert attempt.provider_id == str(attempt.id)
    sent = fake_bitpay.sessions[fake_bitpay.id_get]["factor_id"]
    assert sent is not None
    assert _LATIN_DECIMAL.fullmatch(str(sent))
    assert str(sent) == str(attempt.id)


def test_digipay_callback_identity_lookup_ignores_bitpay_attempts(
    client, auth_headers, fake_bitpay
):
    """Hardening: the DigiPay callback resolves its row by ``provider_id``; a
    BitPay attempt now stores a short numeric id there, so the lookup must be
    scoped to DigiPay rows — a forged DigiPay callback carrying that number
    must not resolve (let alone settle) a BitPay attempt."""
    from app.services import commerce as commerce_service
    from tests.conftest import TestSessionLocal

    invoice_id, token = make_approved(client, auth_headers)
    assert bitpay_pay(client, token).status_code == 200
    attempt = latest_attempt(invoice_id)
    assert _LATIN_DECIMAL.fullmatch(str(attempt.provider_id))

    db = TestSessionLocal()
    try:
        assert (
            commerce_service.find_payment_attempt_by_provider_id(
                db, attempt.provider_id
            )
            is None
        )
    finally:
        db.close()


def test_bitpay_callback_alnum_factor_echo_is_coerced_to_zero_and_never_settles(
    client, auth_headers, fake_bitpay
):
    """A verify reply whose factorId is not a Latin integer is coerced to ``0``
    by the gateway; ``0`` can never match the numeric reference → no settle."""
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.factor_override = "INV-someone-elses"     # coerced to "0"
    r = bitpay_callback(client, trans_id="1", id_get=fake_bitpay.id_get)
    assert "payment=failed" in r.headers["location"]
    assert latest_attempt(invoice_id).state == "unknown"
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_callback_already_verified_status_11_settles(client, auth_headers, fake_bitpay):
    """The documented ``11`` (already verified) is a success too, and settles."""
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_status = 11
    r = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert "payment=success" in r.headers["location"]
    assert invoice_state(invoice_id) == "paid"


# ── Legacy (pre-fix) attempts: alnum provider_id, factorId coerced to 0 ──
#
# Attempts created before this fix sent ``factorId=INV<id>-R<rev>-<hex>``, which
# the gateway silently coerced to ``0`` on verify. Such a row can never be
# matched, so it MUST NOT auto-settle through the ordinary callback or a regular
# staff ``verify`` reconcile — the lock and the staff queue are preserved until
# an explicit, audited manual settlement releases it.
def _invoice_amount_rial(invoice_id):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return db.get(CommerceInvoice, invoice_id).total_toman * 10
    finally:
        db.close()


def _make_legacy_bitpay_attempt(
    invoice_id, *, id_get, provider_id="INV3-R1-deadbeef", state="unknown", trans_id=None
):
    """Insert a pre-fix BitPay attempt (alnum provider_id) directly."""
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        attempt = CommercePaymentAttempt(
            invoice_id=invoice_id,
            provider="bitpay",
            state=state,
            provider_id=provider_id,
            amount_rial=invoice.total_toman * 10,
            invoice_revision=invoice.revision,
            type=0,
            tracking_code=str(id_get),
            provider_trans_id=trans_id,
            redirect_url=f"https://bitpay.ir/payment/gateway-{id_get}-get",
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return attempt.id
    finally:
        db.close()


def test_bitpay_legacy_alnum_attempt_never_auto_settles_on_callback(
    client, auth_headers, fake_bitpay
):
    """A pre-fix paid attempt MUST NOT settle via the ordinary callback — even
    when the gateway verifies success with a matching amount — because its alnum
    factorId was coerced to ``0``. The lock and the staff queue are preserved."""
    invoice_id, token = make_approved(client, auth_headers)
    _make_legacy_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    fake_bitpay.sessions[fake_bitpay.id_get] = {
        "factor_id": "0", "amount_rial": _invoice_amount_rial(invoice_id)
    }
    r = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert "payment=failed" in r.headers["location"]
    assert invoice_state(invoice_id) == "approved"
    after = latest_attempt(invoice_id)
    assert after.state == "unknown"                  # lock held
    assert after.reconciliation_required is False    # not settled this way
    assert fake_bitpay.verify_calls == []            # legacy guard: never trusted


def test_bitpay_legacy_alnum_attempt_not_settled_by_staff_reconcile(
    client, auth_headers, fake_bitpay
):
    """A regular staff ``verify`` reconcile must not auto-settle a legacy alnum
    attempt either; only an explicit, audited manual settlement may."""
    invoice_id, token = make_approved(client, auth_headers)
    attempt_id = _make_legacy_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, trans_id=12345
    )
    fake_bitpay.sessions[fake_bitpay.id_get] = {
        "factor_id": "0", "amount_rial": _invoice_amount_rial(invoice_id)
    }
    rr = client.post(
        f"{BASE}/staff/payments/{attempt_id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["state"] == "unknown"
    assert rr.json()["reconciliation_required"] is False
    assert invoice_state(invoice_id) == "approved"
    assert fake_bitpay.verify_calls == []            # legacy guard, not auto-queried


def test_bitpay_legacy_attempt_can_still_be_abandoned_by_staff(
    client, auth_headers, fake_bitpay
):
    """The legacy row is not hard-locked forever: an explicit, audited staff
    ``abandon`` (with a reason) still releases the invoice lock."""
    invoice_id, token = make_approved(client, auth_headers)
    attempt_id = _make_legacy_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, trans_id=12345
    )
    rr = client.post(
        f"{BASE}/staff/payments/{attempt_id}/reconcile",
        json={"action": "abandon", "reason": "legacy alnum factorId; settled offline"},
        headers=auth_headers,
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["state"] == "failed"


def test_bitpay_staff_reconcile_foreign_numeric_factor_keeps_lock(
    client, auth_headers, fake_bitpay
):
    """A reconcile that returns a different invoice's numeric factorId must not
    settle: the lock is kept."""
    from app.services.bitpay import BitPayError

    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_error = BitPayError("timeout")
    held = bitpay_callback(client, trans_id="555", id_get=fake_bitpay.id_get)
    assert "payment=pending" in held.headers["location"]

    fake_bitpay.verify_error = None
    fake_bitpay.factor_override = "999999"           # a foreign numeric factor
    rr = client.post(
        f"{BASE}/staff/payments/{latest_attempt(invoice_id).id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["state"] == "unknown"
    assert invoice_state(invoice_id) == "approved"


def test_bitpay_staff_reconcile_stale_revision_preserves_evidence(
    client, auth_headers, fake_bitpay
):
    """A genuine reconcile success on an invoice revised after initiation is
    preserved for staff, never applied."""
    from app.models import CommerceInvoice
    from app.services.bitpay import BitPayError
    from tests.conftest import TestSessionLocal

    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_error = BitPayError("timeout")
    bitpay_callback(client, trans_id="555", id_get=fake_bitpay.id_get)
    fake_bitpay.verify_error = None

    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id).revision = 2   # revised after initiation
        db.commit()
    finally:
        db.close()

    rr = client.post(
        f"{BASE}/staff/payments/{latest_attempt(invoice_id).id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["state"] == "verified"
    assert rr.json()["reconciliation_required"] is True
    assert invoice_state(invoice_id) != "paid"


def test_bitpay_callback_success_then_forged_trans_id_does_not_settle(
    client, auth_headers, fake_bitpay
):
    """A callback with a valid id_get but a bogus trans_id cannot settle."""
    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    fake_bitpay.verify_status = -4                    # gateway rejects the bogus trans_id
    forged = bitpay_callback(client, trans_id="999999", id_get=fake_bitpay.id_get)
    assert "payment=failed" in forged.headers["location"]
    assert invoice_state(invoice_id) == "approved"

    # the genuine callback (correct trans_id) still settles — the forgery did
    # not pin the attempt into a dead end
    fake_bitpay.verify_status = 1
    genuine = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert "payment=success" in genuine.headers["location"]
    assert invoice_state(invoice_id) == "paid"


def test_bitpay_callback_verified_but_revoked_invoice_flags_for_staff(
    client, auth_headers, fake_bitpay
):
    """A late/foreign success on a non-payable invoice is preserved, not applied."""
    invoice_id, _, attempt = _pay_and_attempt(client, auth_headers, fake_bitpay)
    # A staff revoke is refused while a payment is in flight (409), so simulate
    # the invoice becoming non-payable by flipping its state directly — the
    # settle path is what this test pins, not the revoke route guard.
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id).state = "revoked"
        db.commit()
    finally:
        db.close()

    first = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert "payment=pending" in first.headers["location"]

    refreshed = latest_attempt(invoice_id)
    assert refreshed.state == "verified"              # evidence kept
    assert refreshed.reconciliation_required is True
    assert invoice_state(invoice_id) != "paid"

    # replay of the settled-but-flagged attempt reports the SAME pending outcome
    replay = bitpay_callback(client, trans_id="12345", id_get=fake_bitpay.id_get)
    assert "payment=pending" in replay.headers["location"]
    assert invoice_state(invoice_id) != "paid"


def test_bitpay_staff_reconcile_verifies_through_bitpay_client(
    client, auth_headers, fake_bitpay
):
    from app.services.bitpay import BitPayError

    invoice_id, _, _ = _pay_and_attempt(client, auth_headers, fake_bitpay)
    # Provider unreachable during the callback → attempt held open with trans_id.
    fake_bitpay.verify_error = BitPayError("timeout")
    held = bitpay_callback(client, trans_id="555", id_get=fake_bitpay.id_get)
    assert "payment=pending" in held.headers["location"]
    attempt = latest_attempt(invoice_id)
    assert attempt.state == "unknown" and attempt.provider_trans_id == 555

    # Provider recovers; staff reconcile re-queries via the BitPay adapter.
    fake_bitpay.verify_error = None
    rr = client.post(
        f"{BASE}/staff/payments/{attempt.id}/reconcile",
        json={"action": "verify"},
        headers=auth_headers,
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["state"] == "verified"
    assert invoice_state(invoice_id) == "paid"
    assert fake_bitpay.verify_calls[-1] == {"trans_id": 555, "id_get": fake_bitpay.id_get}


# ══════════════════════════════════════════════════════════════════════
# Access-log protection — uvicorn query redaction
# ══════════════════════════════════════════════════════════════════════

def test_redact_bitpay_query_unit():
    from app.log_redaction import REDACTED, redact_bitpay_query

    assert (
        redact_bitpay_query(f"{BITPAY_CB_PATH}?trans_id=1&id_get=2")
        == f"{BITPAY_CB_PATH}?{REDACTED}"
    )
    assert redact_bitpay_query(BITPAY_CB_PATH) == BITPAY_CB_PATH          # bare path unchanged
    assert (
        redact_bitpay_query(f"{BITPAY_CB_PATH}/extra?x=1")
        == f"{BITPAY_CB_PATH}/extra?{REDACTED}"
    )
    assert redact_bitpay_query("/api/v1/products?page=2") == "/api/v1/products?page=2"
    inv = "/api/v1/commerce/invoices/SEKRET/pay"
    assert redact_bitpay_query(inv) == inv


@pytest.mark.parametrize(
    "path",
    [
        f"{BITPAY_CB_PATH}?trans_id=1&id_get=BITPAYSENTINEL",
        f"{BITPAY_CB_PATH}?id_get=BITPAYSENTINEL",
        "/API/v1/Commerce/Bitpay/Callback?id_get=BITPAYSENTINEL",          # case variant
    ],
)
def test_bitpay_filter_scrubs_query_and_preserves_rest(path):
    from app.log_redaction import REDACTED, RedactBitpayCallbackFilter

    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", path, "HTTP/1.1", 303),
        None,
    )
    RedactBitpayCallbackFilter().filter(record)
    line = record.getMessage()
    assert "BITPAYSENTINEL" not in line
    assert BITPAY_CB_PATH in line.lower()
    assert REDACTED in line
    assert "GET" in line and "HTTP/1.1" in line and "303" in line


def test_bitpay_filter_leaves_ordinary_and_invoice_paths_untouched():
    from app.log_redaction import REDACTED, RedactBitpayCallbackFilter

    logger = logging.getLogger("uvicorn.access")
    for path in ("/api/v1/products?page=2", "/api/v1/commerce/invoices/AbC/pay"):
        record = logger.makeRecord(
            "uvicorn.access", logging.INFO, __file__, 0,
            '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4", "GET", path, "HTTP/1.1", 200),
            None,
        )
        before = record.args
        RedactBitpayCallbackFilter().filter(record)
        assert record.args == before
        assert REDACTED not in record.getMessage()


def test_bitpay_filter_installed_and_idempotent():
    from app.log_redaction import RedactBitpayCallbackFilter, install_access_log_redaction

    install_access_log_redaction()
    install_access_log_redaction()  # must not stack duplicates
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, RedactBitpayCallbackFilter) for f in filters) == 1


def test_bitpay_query_redacted_through_access_formatter():
    from app.log_redaction import REDACTED, RedactBitpayCallbackFilter

    formatter_cls = pytest.importorskip("uvicorn.logging").AccessFormatter
    formatter = formatter_cls()
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", f"{BITPAY_CB_PATH}?trans_id=1&id_get=BITPAYSENTINEL", "HTTP/1.1", 303),
        None,
    )
    RedactBitpayCallbackFilter().filter(record)
    line = formatter.format(record)
    assert "BITPAYSENTINEL" not in line
    assert f"{BITPAY_CB_PATH}?{REDACTED}" in line


# ══════════════════════════════════════════════════════════════════════
# Access-log protection — nginx config
# ══════════════════════════════════════════════════════════════════════

def _nginx_conf_text():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "frontend" / "nginx.conf").read_text(encoding="utf-8")


def _location_block(text, header):
    start = text.index(header)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(f"unbalanced location block: {header}")


def test_bitpay_nginx_prefix_block_disables_access_log_and_wins_over_generic():
    text = _nginx_conf_text()
    specific = f"location ^~ {BITPAY_CB_PATH} {{"
    generic = "location ^~ /api/ {"
    assert specific in text, "no dedicated no-log block for the BitPay callback"
    assert generic in text
    assert text.index(specific) < text.index(generic)      # longer prefix wins
    block = _location_block(text, specific)
    assert "access_log off;" in block
    assert "proxy_pass http://backend:8000;" in block


def test_bitpay_nginx_case_insensitive_companion_precedes_static_assets():
    text = _nginx_conf_text()
    comp = f"location ~* ^{BITPAY_CB_PATH} {{"
    assert comp in text
    block = _location_block(text, comp)
    assert "access_log off;" in block
    assert "proxy_pass http://backend:8000;" in block
    assert text.index(comp) < text.index("location ~* \\.(js|css|")


# ══════════════════════════════════════════════════════════════════════
# Cross-provider lock — one in-flight attempt per invoice, provider-scoped
# ══════════════════════════════════════════════════════════════════════

class FakeDigiPay:
    """Minimal DigiPay UPG stand-in for the cross-provider lock tests."""

    def __init__(self):
        self.redirect_url = "https://web.mydigipay.com/web-pay/v2:cross-provider"
        self.tickets = {}

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        self.tickets[provider_id] = {"amount_rial": amount_rial}
        return {
            "redirect_url": self.redirect_url,
            "ticket": "v2:cross-provider",
            "provider_id": provider_id,
        }


@pytest.fixture()
def fake_digipay(client, monkeypatch):
    from app.main import app
    from app.services import digipay

    # DigiPay is parked in production (the legacy initiation route is a hard
    # 503); the cross-provider lock tests still need a real DigiPay attempt, so
    # they opt in explicitly through the predicate seam.
    monkeypatch.setattr(digipay, "checkout_enabled", lambda: True)

    fake = FakeDigiPay()
    app.dependency_overrides[digipay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(digipay.client_dependency, None)


def digipay_pay(client, token):
    return client.post(f"{BASE}/invoices/{token}/pay")


def _attempt_count(invoice_id):
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return (
            db.query(CommercePaymentAttempt)
            .filter(CommercePaymentAttempt.invoice_id == invoice_id)
            .count()
        )
    finally:
        db.close()


def test_digipay_pay_conflicts_when_bitpay_attempt_in_flight(
    client, auth_headers, fake_bitpay, fake_digipay
):
    """A live BitPay attempt is not a DigiPay resume - it is a conflict."""
    invoice_id, token = make_approved(client, auth_headers)
    started = bitpay_pay(client, token)
    assert started.status_code == 200, started.text
    bitpay_redirect = started.json()["redirect_url"]

    r = digipay_pay(client, token)
    assert r.status_code == 409, r.text
    # the BitPay portal URL must never leak out of the DigiPay endpoint
    assert bitpay_redirect not in r.text
    assert "redirect_url" not in r.json()
    # DigiPay was never asked to mint a ticket, and no second attempt exists
    assert fake_digipay.tickets == {}
    assert _attempt_count(invoice_id) == 1

    attempt = latest_attempt(invoice_id)
    assert attempt.provider == "bitpay"
    assert attempt.redirect_url == bitpay_redirect
    assert attempt.state == "pending"

    # same-provider idempotency is untouched: the BitPay click still resumes
    again = bitpay_pay(client, token)
    assert again.status_code == 200
    assert again.json()["redirect_url"] == bitpay_redirect


def test_bitpay_pay_conflicts_when_digipay_attempt_in_flight(
    client, auth_headers, fake_bitpay, fake_digipay
):
    """A live DigiPay attempt blocks BitPay with a controlled conflict."""
    invoice_id, token = make_approved(client, auth_headers)
    started = digipay_pay(client, token)
    assert started.status_code == 200, started.text
    digipay_redirect = started.json()["redirect_url"]

    r = bitpay_pay(client, token)
    assert r.status_code == 409, r.text
    assert digipay_redirect not in r.text
    assert "redirect_url" not in r.json()
    assert fake_bitpay.sessions == {}
    assert _attempt_count(invoice_id) == 1

    attempt = latest_attempt(invoice_id)
    assert attempt.provider == "digipay"
    assert attempt.redirect_url == digipay_redirect
    assert attempt.state == "pending"

    # same-provider idempotency preserved on the DigiPay side too
    again = digipay_pay(client, token)
    assert again.status_code == 200
    assert again.json()["redirect_url"] == digipay_redirect
