"""Reviewed invoice lifecycle contract (no external payment requests)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from app.models import AuditLog, CommerceInvoice
from tests.conftest import TestSessionLocal

BASE = "/api/v1/commerce"


@pytest.fixture(autouse=True)
def reset_limits(client):
    from app.main import app
    app.state.limiter._limiter.storage.reset()


def draft(**changes):
    data = {
        "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
        "specification": "رنگ آبی", "internal_note": "private-note", "shipping_toman": 12000,
        "items": [{"description": "قطعه سفارشی", "qty": 2, "unit_toman": 150000}],
    }
    data.update(changes)
    return data


def create(client, auth_headers, **changes):
    r = client.post(f"{BASE}/staff/invoices", json=draft(**changes), headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_manual_invoice_totals_and_private_link(client, auth_headers):
    inv = create(client, auth_headers)
    assert (inv["state"], inv["total_toman"], inv["items"][0]["line_total_toman"]) == ("draft", 312000, 300000)
    approved = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    url = approved.json()["share_url"]
    assert url.startswith("https://spaghettiprints.ir/pay/")
    token = urlsplit(url).path.rsplit("/", 1)[-1]
    public = client.get(f"{BASE}/invoices/{token}")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["total_toman"] == 312000 and body["specification"] == "رنگ آبی"
    for field in ("customer_name", "mobile", "address", "internal_note", "token", "token_hash"):
        assert field not in body
    assert client.get(f"{BASE}/invoices/not-a-token").status_code == 404
    db = TestSessionLocal()
    try:
        persisted = db.get(CommerceInvoice, inv["id"])
        assert persisted.token_hash != token
        assert token not in repr(persisted.__dict__)
    finally:
        db.close()


def test_edit_rotates_link_and_paid_edit_denied(client, auth_headers):
    inv = create(client, auth_headers)
    old = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers).json()["share_url"].rsplit("/", 1)[-1]
    changed = client.put(f"{BASE}/staff/invoices/{inv['id']}", headers=auth_headers, json=draft(specification="رنگ قرمز"))
    assert changed.status_code == 200, changed.text
    assert changed.json()["state"] == "draft" and changed.json()["revision"] == 2
    assert client.get(f"{BASE}/invoices/{old}").status_code in (404, 410)
    new = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers).json()["share_url"].rsplit("/", 1)[-1]
    assert new != old
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, inv["id"]).state = "paid"
        db.commit()
    finally:
        db.close()
    assert client.put(f"{BASE}/staff/invoices/{inv['id']}", headers=auth_headers, json=draft()).status_code == 409


def test_revoke_and_expiry(client, auth_headers):
    inv = create(client, auth_headers)
    token = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers).json()["share_url"].rsplit("/", 1)[-1]
    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, inv["id"]).token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert client.get(f"{BASE}/invoices/{token}").status_code == 410
    assert client.post(f"{BASE}/staff/invoices/{inv['id']}/revoke", headers=auth_headers).status_code == 200
    assert client.get(f"{BASE}/invoices/{token}").status_code == 404


def test_website_conversion_and_role_guard(client, auth_headers):
    assert client.post(f"{BASE}/staff/invoices", json=draft()).status_code == 401
    product = client.post("/api/v1/products", json={"name": "فیگور", "weight_g": 40, "print_time_hours": 1, "final_price": 150000}, headers=auth_headers)
    assert product.status_code == 201, product.text
    req = client.post(f"{BASE}/requests", json={"customer_name":"رضا", "mobile":"09123456789", "messenger":"telegram", "items":[{"product_id":product.json()["id"],"qty":1}]})
    assert req.status_code == 200, req.text
    requests = client.get(f"{BASE}/staff/requests", headers=auth_headers).json()
    inv = create(client, auth_headers, request_id=requests[0]["id"])
    assert inv["request_id"] == requests[0]["id"]
    assert client.get(f"{BASE}/staff/requests", headers=auth_headers).json()[0]["state"] == "converted"
    duplicate = client.post(f"{BASE}/staff/invoices", json=draft(request_id=requests[0]["id"]), headers=auth_headers)
    assert duplicate.status_code == 409


@pytest.mark.parametrize("bad", [0, -1, 1.5, "100", 50000001])
def test_invalid_unit_toman_rejected(client, auth_headers, bad):
    payload = draft(items=[{"description":"x","qty":1,"unit_toman":bad}])
    assert client.post(f"{BASE}/staff/invoices", headers=auth_headers, json=payload).status_code in (400, 422)


def test_bad_origin_must_not_approve(client, auth_headers, monkeypatch):
    inv = create(client, auth_headers)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "https://evil.example/path?leak=1")
    r = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers)
    assert r.status_code >= 400
    listing = client.get(f"{BASE}/staff/invoices", headers=auth_headers).json()
    assert listing[0]["state"] == "draft"


@pytest.mark.parametrize(
    "bad_origin",
    [
        "https://evil.example/path",
        "https://evil.example?leak=1",
        "https://evil.example/پ/ay#frag",
        "https://user:pass@evil.example",
        "ftp://evil.example",
        "not-a-url",
    ],
)
def test_non_bare_or_invalid_origin_rejected(client, auth_headers, monkeypatch, bad_origin):
    """A share link must only ever be built from a bare http(s) origin."""
    inv = create(client, auth_headers)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", bad_origin)
    r = client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers)
    assert r.status_code >= 400, r.text
    # Approval must not have been committed with a broken/foreign origin.
    listing = client.get(f"{BASE}/staff/invoices", headers=auth_headers).json()
    assert listing[0]["state"] == "draft"


def test_revoke_and_approve_blocked_while_payment_in_flight(
    client, auth_headers, monkeypatch
):
    """In-flight settlement freezes revoke and re-approve until reconciled."""
    from app.services import commerce as commerce_service

    inv = create(client, auth_headers)
    client.post(f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers)
    monkeypatch.setattr(
        commerce_service, "has_inflight_payment_attempt", lambda db, invoice: True
    )
    assert (
        client.post(
            f"{BASE}/staff/invoices/{inv['id']}/revoke", headers=auth_headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers
        ).status_code
        == 409
    )
    # The original approval is untouched (still approved with a live link).
    listing = client.get(f"{BASE}/staff/invoices", headers=auth_headers).json()
    assert listing[0]["state"] == "approved"


def test_public_invoice_sends_no_store_and_no_referrer_headers(client, auth_headers):
    """The private pay response must never be cached or leak via a referrer."""
    inv = create(client, auth_headers)
    token = client.post(
        f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers
    ).json()["share_url"].rsplit("/", 1)[-1]

    ok = client.get(f"{BASE}/invoices/{token}")
    assert ok.status_code == 200, ok.text
    assert ok.headers["Cache-Control"] == "no-store"
    assert ok.headers["Referrer-Policy"] == "no-referrer"

    # Error responses for the same private endpoint must not be cacheable either.
    missing = client.get(f"{BASE}/invoices/not-a-real-token")
    assert missing.status_code == 404
    assert missing.headers["Cache-Control"] == "no-store"
    assert missing.headers["Referrer-Policy"] == "no-referrer"


def test_plain_http_origin_allowed_only_for_localhost_dev(
    client, auth_headers, monkeypatch
):
    """HTTP is refused for any real host even with APP_ENV unset (the deploy
    case); only an explicit localhost dev origin may use plain HTTP."""
    inv = create(client, auth_headers)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "http://spaghettiprints.ir")
    refused = client.post(
        f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers
    )
    assert refused.status_code >= 400, refused.text
    listing = client.get(f"{BASE}/staff/invoices", headers=auth_headers).json()
    assert listing[0]["state"] == "draft"

    # An explicit local dev host is the sole accepted plain-HTTP origin.
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", "http://localhost:5173")
    approved = client.post(
        f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["share_url"].startswith("http://localhost:5173/pay/")


def test_staff_invoice_mutations_are_audited_without_token(client, auth_headers):
    """create/edit/approve/revoke each append an audit row; never the token."""
    inv = create(client, auth_headers)
    approved = client.post(
        f"{BASE}/staff/invoices/{inv['id']}/approve", headers=auth_headers
    ).json()
    raw_token = approved["share_url"].rsplit("/", 1)[-1]
    client.put(
        f"{BASE}/staff/invoices/{inv['id']}",
        headers=auth_headers,
        json=draft(specification="رنگ سبز"),
    )
    client.post(f"{BASE}/staff/invoices/{inv['id']}/revoke", headers=auth_headers)

    db = TestSessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.entity == "commerce_invoice").all()
        actions = {r.action for r in rows}
        assert {"create", "approve", "update", "revoke"} <= actions
        assert all(r.entity_id == inv["id"] for r in rows)
        assert all(r.user == "admin" for r in rows)
        summaries = " ".join(r.summary or "" for r in rows)
        assert raw_token not in summaries
        assert raw_token not in repr([r.summary for r in rows])
    finally:
        db.close()
