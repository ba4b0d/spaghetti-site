"""SnappPay onboarding callback — a reachability stub, NOT a payment handler.

These tests pin the invariants that make the fixed callback URL safe to publish
to SnappPay *before* it issues any credentials or protocol details:

* GET and POST reach the exact registered URL, and only those methods are mounted;
* GET proves the route is active without asserting anything about payments;
* POST returns a neutral ``202`` "pending" — never a success;
* neither method mutates state;
* the request body/query is never logged by the handler (only the fixed path
  and method are) and never echoed back; and
* no notification transport is reached and no provider/settlement code runs; and
* the response discloses only the fixed, non-secret neutral fields.

SnappPay has issued no protocol, so there is deliberately no settlement
behaviour to test — only its absence.
"""
import logging

import pytest

CALLBACK = "/api/v1/commerce/snappay/callback"
# A value that would be damaging to see in a log line or an echoed response.
SENTINEL = "SNAPPAY-ONBOARDING-SECRET-SENTINEL-42"


@pytest.fixture(autouse=True)
def reset_limits(client):
    from app.main import app

    app.state.limiter._limiter.storage.reset()


# ── Routing: the fixed onboarding URL is live, GET + POST only ───────────


def test_callback_path_constant_is_the_fixed_onboarding_path():
    from app.routers.snappay_callback import CALLBACK_PATH

    assert CALLBACK_PATH == CALLBACK


def test_onboarding_url_is_https_on_the_production_origin():
    from app.routers.snappay_callback import CALLBACK_PATH
    from app.services.commerce import DEFAULT_PUBLIC_SITE_ORIGIN

    assert (
        f"{DEFAULT_PUBLIC_SITE_ORIGIN}{CALLBACK_PATH}"
        == "https://spaghettiprints.ir/api/v1/commerce/snappay/callback"
    )


def test_route_is_registered_for_get_and_post_only():
    from app.main import app

    matched = [
        route for route in app.routes if getattr(route, "path", None) == CALLBACK
    ]
    assert matched, "the SnappPay callback route is not registered"
    methods = set()
    for route in matched:
        methods |= set(route.methods)
    assert methods == {"GET", "POST"}


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
def test_unmounted_methods_are_refused(client, method):
    assert getattr(client, method)(CALLBACK).status_code == 405


# ── GET: proves the route is active, asserts nothing about payments ──────


def test_get_is_reachable_and_proves_the_route_is_active(client):
    r = client.get(CALLBACK)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "snappay"
    assert body["status"] == "reachable"
    assert body["callback_path"] == CALLBACK
    assert body["payment_enabled"] is False


def test_get_response_never_claims_a_payment_outcome(client):
    r = client.get(CALLBACK)
    lowered = r.text.lower()
    assert "success" not in lowered
    assert "paid" not in lowered


def test_get_response_is_not_cacheable(client):
    r = client.get(CALLBACK)
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["Referrer-Policy"] == "no-referrer"


# ── POST: neutral 202 acknowledgement, never success ─────────────────────


def test_post_acknowledges_as_pending_and_never_success(client):
    r = client.post(
        CALLBACK,
        json={"result": "SUCCESS", "providerId": "INV-X", "amount": "3120000", "trackingCode": "t"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["provider"] == "snappay"
    assert body["status"] == "pending"
    assert body["payment_enabled"] is False
    lowered = r.text.lower()
    assert "success" not in lowered
    assert "paid" not in lowered
    # The caller-supplied "evidence" is never echoed back.
    assert "SUCCESS" not in r.text
    assert "providerId" not in r.text
    assert "3120000" not in r.text


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"json": {"result": "SUCCESS"}},
        {"data": {"result": "SUCCESS", "providerId": "INV-X"}},
        {"content": b"raw-bytes-body"},
    ],
)
def test_post_always_returns_202_regardless_of_body_shape(client, kwargs):
    r = client.post(CALLBACK, **kwargs)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"


def test_post_ignores_a_query_string(client):
    r = client.post(f"{CALLBACK}?state=SUCCESS&amount=3120000", json={"x": "y"})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"


# ── No state mutation ────────────────────────────────────────────────────


def test_neither_method_mutates_state(client):
    from app.models import (
        CommerceInvoice,
        CommercePaymentAttempt,
        CommerceRequest,
        Order,
    )
    from tests.conftest import TestSessionLocal

    def snapshot():
        db = TestSessionLocal()
        try:
            return {
                "invoices": db.query(CommerceInvoice).count(),
                "attempts": db.query(CommercePaymentAttempt).count(),
                "orders": db.query(Order).count(),
                "requests": db.query(CommerceRequest).count(),
            }
        finally:
            db.close()

    before = snapshot()
    client.get(CALLBACK)
    client.post(
        CALLBACK,
        json={"result": "SUCCESS", "providerId": "INV-X", "amount": "3120000", "trackingCode": "t"},
    )
    client.post(CALLBACK, data={"result": "SUCCESS", "providerId": "INV-X"})
    assert snapshot() == before


# ── No body/query logging, no echo ───────────────────────────────────────

def test_request_body_is_never_logged_or_echoed(client, caplog):
    """The raw callback body must not reach any log (or the response)."""
    with caplog.at_level(logging.DEBUG):
        r = client.post(
            CALLBACK,
            json={"secret": SENTINEL, "result": "SUCCESS"},
        )
    assert r.status_code == 202
    assert SENTINEL not in r.text, "the callback body was echoed back"
    # httpx/httpcore are the TestClient's own transport, which echoes the
    # request URL it sends — that is the harness, not the application. Every
    # other logger is application/uvicorn code and must stay silent.
    harness = {"httpx", "httpcore"}
    app_records = [
        rec for rec in caplog.records
        if rec.name.split(".")[0] not in harness
    ]
    assert not any(SENTINEL in rec.getMessage() for rec in app_records), (
        "the callback body reached an application log"
    )


def test_query_string_is_not_logged_by_the_application(client, caplog):
    with caplog.at_level(logging.DEBUG):
        r = client.get(f"{CALLBACK}?token={SENTINEL}")
    assert r.status_code == 200
    harness = {"httpx", "httpcore"}
    app_records = [
        rec for rec in caplog.records
        if rec.name.split(".")[0] not in harness
    ]
    assert not any(SENTINEL in rec.getMessage() for rec in app_records), (
        "the callback query string reached an application log"
    )
    assert SENTINEL not in r.text, "the callback query was echoed back"


# ── No notifications, no DigiPay/settlement reuse, no secrets ────────────


def test_post_reaches_no_notification_leaf_sender(client, monkeypatch):
    from app.services import commerce_notifications as cn

    reached: list[str] = []

    def _spy(*_args, _name="?", **_kwargs):
        reached.append(_name)

    for name in ("send_telegram_notification", "post_sms_ir_verify", "send_smtp_mail"):
        monkeypatch.setattr(cn, name, lambda *a, _n=name, **k: reached.append(_n))

    assert client.post(CALLBACK, json={"result": "SUCCESS", "amount": "1"}).status_code == 202
    assert reached == [], f"a notification transport was reached: {reached}"


def test_post_does_not_reuse_digipay_settlement(client, monkeypatch):
    from app.services import commerce as commerce_service

    def _boom(*_args, **_kwargs):
        raise AssertionError("DigiPay settlement must not run for a SnappPay callback")

    monkeypatch.setattr(commerce_service, "handle_digipay_callback", _boom)
    assert client.post(CALLBACK, json={"result": "SUCCESS"}).status_code == 202


def test_responses_disclose_only_the_safe_neutral_fields(client):
    get_body = client.get(CALLBACK).json()
    post_body = client.post(CALLBACK, json={"secret": SENTINEL}).json()
    assert set(get_body) == {"provider", "status", "callback_path", "payment_enabled"}
    assert set(post_body) == {"provider", "status", "payment_enabled"}


# ── Safe handler logging (neither method is silently handled) ────────────
# The POST acknowledges ANY unknown body with a neutral 202 and there is no
# SnappPay contract to reject against, so the handler records exactly the
# method and the fixed callback path — never the query string, headers or body
# — so a probe/abuse is traceable without leaking anything a caller controls.

def test_post_emits_one_safe_log_line_with_no_query_or_body(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.routers.snappay_callback"):
        r = client.post(
            f"{CALLBACK}?token={SENTINEL}",
            json={"secret": SENTINEL, "result": "SUCCESS"},
        )
    assert r.status_code == 202
    lines = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "app.routers.snappay_callback"
    ]
    assert lines, "an unexpected POST must not be handled silently"
    joined = "\n".join(lines)
    assert "POST" in joined
    assert CALLBACK in joined
    assert SENTINEL not in joined, "the callback query/body leaked into the handler log"


def test_get_does_not_emit_a_log_line(client, caplog):
    """GET answers with a descriptive body, so it needs no extra trace."""
    with caplog.at_level(logging.DEBUG, logger="app.routers.snappay_callback"):
        client.get(f"{CALLBACK}?token={SENTINEL}")
    assert not [
        rec for rec in caplog.records
        if rec.name == "app.routers.snappay_callback"
    ]
