"""Task 2 — verified customer order-history API: ownership, redaction, pagination.

Public routes under ``/api/v1/commerce/history``:

* ``POST /otp``      — issue a history one-time code (no existence disclosure)
* ``POST /verify``   — exchange the code for a short-lived bearer session
* ``GET  /``         — exact-mobile, redacted, bounded history (Bearer only)
* ``POST /sign-out`` — revoke the bearer session

What is proven here: a history session is the ONLY credential (never a staff
cookie), an invalid / malformed / expired / revoked bearer is always 401, a
session only ever sees its own canonical mobile, staff-created invoices appear,
draft/revoked money is never presented as final, raw payment links and
staff-only fields never leak, pagination is stable and non-repeating, an empty
number is indistinguishable from a rich one before verification, and every
response — including validation 422 and throttle 429 — is ``no-store`` /
``no-referrer``.

No real SMS or gateway: ``commerce_notifications.send_customer_otp`` is faked in
every test.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

BASE = "/api/v1/commerce/history"
MOBILE = "09123456789"
OTHER = "09120000000"

# Fields an entry is allowed to carry. A history entry must never grow an
# internal-note / address / handle / token / provider-id field.
_REQUEST_KEYS = {"kind", "id", "request_id", "state", "created_at", "items"}
_INVOICE_KEYS = _REQUEST_KEYS | {"shipping_toman", "total_toman"}

_SMS = {}


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
    """Reset the shared slowapi counters so the 3/min OTP budget is per test."""
    from app.main import app

    try:
        app.state.limiter._limiter.storage.reset()
    except Exception:  # pragma: no cover - limiter always present in app.main
        pass
    yield


# ── Helpers ──────────────────────────────────────────────────────────

def _db():
    from tests.conftest import TestSessionLocal

    return TestSessionLocal()


def _sent_code():
    call = _SMS["sender"].call_args_list[-1]
    return call.args[1] if len(call.args) > 1 else call.kwargs["code"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _now():
    return datetime.now(timezone.utc)


def _verify_code(client, mobile, challenge_id):
    return client.post(
        f"{BASE}/verify",
        json={"mobile": mobile, "challenge_id": challenge_id, "code": _sent_code()},
    )


def _get_token(client, mobile=MOBILE):
    """Full public issue + verify round-trip; returns the raw bearer."""
    r = client.post(f"{BASE}/otp", json={"mobile": mobile})
    assert r.status_code == 200, r.text
    v = _verify_code(client, mobile, r.json()["challenge_id"])
    assert v.status_code == 200, v.text
    return v.json()["token"]


def _insert_request(mobile=MOBILE, *, state="pending_review", created_at=None, items=None):
    from app.models import CommerceRequest, CommerceRequestItem
    from app.services.commerce import generate_receipt_id

    db = _db()
    try:
        req = CommerceRequest(
            receipt_id=generate_receipt_id(),
            customer_name="مشتری",
            mobile=mobile,
            messenger="telegram",
            messenger_handle="@handle",
            address="آدرس کامل محرمانه",
            note="یادداشت",
            state=state,
            created_at=created_at or _now(),
        )
        db.add(req)
        db.flush()
        for it in (
            items
            if items is not None
            else [{"display_name": "قطعه تستی", "qty": 2, "indicative_unit_price_toman": 5000}]
        ):
            db.add(CommerceRequestItem(request_id=req.id, **it))
        db.commit()
        db.refresh(req)
        return req.id
    finally:
        db.close()


def _insert_invoice(
    mobile=MOBILE,
    *,
    state="draft",
    created_at=None,
    request_id=None,
    items=None,
    shipping=0,
    total=0,
    internal_note="یادداشت داخلی محرمانه",
    address="آدرس کامل محرمانه",
    handle="@staff_handle",
    token_hash=None,
):
    from app.models import CommerceInvoice, CommerceInvoiceItem

    db = _db()
    try:
        inv = CommerceInvoice(
            request_id=request_id,
            customer_name="مشتری",
            mobile=mobile,
            messenger="bale",
            messenger_handle=handle,
            address=address,
            specification="مشخصات نهایی",
            internal_note=internal_note,
            shipping_toman=shipping,
            total_toman=total,
            state=state,
            token_hash=token_hash,
            created_at=created_at or _now(),
        )
        db.add(inv)
        db.flush()
        for it in (
            items
            if items is not None
            else [
                {
                    "description": "قطعه فاکتور",
                    "qty": 2,
                    "unit_toman": 150000,
                    "line_total_toman": 300000,
                }
            ]
        ):
            db.add(CommerceInvoiceItem(invoice_id=inv.id, **it))
        db.commit()
        db.refresh(inv)
        return inv.id
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Issue / verify round-trip
# ══════════════════════════════════════════════════════════════════════

def test_issue_verify_then_read(client):
    _insert_request()
    r = client.post(f"{BASE}/otp", json={"mobile": MOBILE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"challenge_id", "expires_in", "resend_after", "delivery", "masked_mobile"}
    assert body["delivery"] == "sms"
    # The full number is never echoed back.
    assert MOBILE not in r.text
    from app.services.commerce_notifications import mask_mobile

    assert body["masked_mobile"] == mask_mobile(MOBILE)

    verified = client.post(
        f"{BASE}/verify",
        json={"mobile": MOBILE, "challenge_id": body["challenge_id"], "code": _sent_code()},
    )
    assert verified.status_code == 200, verified.text
    token = verified.json()["token"]
    assert token and " " not in token

    listing = client.get(BASE, headers=_auth(token))
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert set(payload) == {"items", "has_more"}
    assert [e["kind"] for e in payload["items"]] == ["request"]


def test_invalid_mobile_is_rejected_and_no_sms(client):
    for bad in ("0912345678", "08123456789", "091234567890", "۰۹۱۲۳۴۵۶۷۸۹", "09a23456789"):
        r = client.post(f"{BASE}/otp", json={"mobile": bad})
        assert r.status_code == 422, (bad, r.status_code)
    assert _SMS["sender"].call_count == 0


def test_verify_rejects_wrong_and_unknown_code(client):
    r = client.post(f"{BASE}/otp", json={"mobile": MOBILE})
    challenge_id = r.json()["challenge_id"]
    wrong = "00000" if _sent_code() != "00000" else "11111"

    bad = client.post(
        f"{BASE}/verify",
        json={"mobile": MOBILE, "challenge_id": challenge_id, "code": wrong},
    )
    assert bad.status_code == 400, bad.text

    unknown = client.post(
        f"{BASE}/verify",
        json={"mobile": MOBILE, "challenge_id": 999999, "code": wrong},
    )
    assert unknown.status_code == 400, unknown.text


def test_checkout_challenge_cannot_authorize_history(client):
    """A checkout (cart) challenge id must never verify through the history route.

    The two challenge tables have independent PKs (so the ids collide — the very
    first cart challenge and the first history challenge are both id ``1``); the
    history verifier must therefore read only the history table. A cart
    challenge's id/code is rejected even though a history row shares that id.
    """
    from tests.otp_helpers import issue_test_otp
    from app.models import CommerceHistorySession

    # A genuine history session for this mobile works first…
    token = _get_token(client, MOBILE)
    assert client.get(BASE, headers=_auth(token)).status_code == 200

    # …and a cart challenge for the SAME mobile (same numeric id) cannot.
    cart = issue_test_otp(mobile=MOBILE, code="77777")
    r = client.post(
        f"{BASE}/verify",
        json={"mobile": MOBILE, "challenge_id": cart["otp_challenge_id"], "code": "77777"},
    )
    assert r.status_code == 400, r.text

    # Only the genuine session exists — no session was minted from the cart row.
    db = _db()
    try:
        assert db.query(CommerceHistorySession).count() == 1
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Authentication boundary
# ══════════════════════════════════════════════════════════════════════

def test_history_requires_authorization_header(client):
    _insert_request()
    for headers in (None, {"Authorization": "Token abc"}, {"Authorization": "Bearer"},
                    {"Authorization": "Bearer "}, {"Authorization": ""}):
        r = client.get(BASE, headers=headers) if headers is not None else client.get(BASE)
        assert r.status_code == 401, (headers, r.status_code)
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        # No order data leaks in the rejection.
        assert "items" not in r.json()


def test_staff_cookie_and_jwt_are_not_history_credentials(client):
    _insert_request()
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "3djat2024"}
    )
    assert login.status_code == 200, login.text
    # Cookie present but no Authorization header → unauthenticated.
    assert client.get(BASE).status_code == 401

    from tests.conftest import _make_token

    staff = _make_token("admin", "3djat2024")
    assert client.get(BASE, headers=_auth(staff)).status_code == 401


def test_expired_and_revoked_session_are_401(client):
    _insert_request()
    token = _get_token(client)
    assert client.get(BASE, headers=_auth(token)).status_code == 200

    from app.models import CommerceHistorySession

    db = _db()
    try:
        db.query(CommerceHistorySession).update(
            {CommerceHistorySession.expires_at: datetime.now(timezone.utc) - timedelta(seconds=5)},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()
    assert client.get(BASE, headers=_auth(token)).status_code == 401


def test_sign_out_revokes_and_requires_session(client):
    _insert_request()
    assert client.post(f"{BASE}/sign-out").status_code == 401
    assert client.post(f"{BASE}/sign-out", headers=_auth("nope")).status_code == 401

    token = _get_token(client)
    out = client.post(f"{BASE}/sign-out", headers=_auth(token))
    assert out.status_code == 200 and out.json() == {"ok": True}
    assert client.get(BASE, headers=_auth(token)).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Exact-mobile ownership
# ══════════════════════════════════════════════════════════════════════

def test_other_number_rows_are_not_returned(client):
    mine = _insert_request(MOBILE)
    _insert_invoice(OTHER)
    _insert_request(OTHER)

    token = _get_token(client, MOBILE)
    items = client.get(BASE, headers=_auth(token)).json()["items"]
    assert [e["id"] for e in items if e["kind"] == "request"] == [mine]
    assert all(e["kind"] != "invoice" for e in items)


def test_staff_created_messenger_invoice_is_visible(client):
    inv = _insert_invoice(MOBILE, state="draft", handle="@telegram_staff")
    token = _get_token(client, MOBILE)
    items = client.get(BASE, headers=_auth(token)).json()["items"]
    assert [(e["kind"], e["id"]) for e in items] == [("invoice", inv)]


def test_linked_request_and_invoice_are_related_not_duplicated(client):
    req = _insert_request(MOBILE)
    inv = _insert_invoice(MOBILE, state="approved", request_id=req)

    token = _get_token(client, MOBILE)
    items = client.get(BASE, headers=_auth(token)).json()["items"]

    by_kind = {e["kind"]: e for e in items}
    assert set(by_kind) == {"request", "invoice"}
    assert by_kind["request"]["request_id"] == req
    assert by_kind["invoice"]["request_id"] == req
    # Exactly one invoice entry — the linked request never duplicates it.
    assert sum(1 for e in items if e["kind"] == "invoice") == 1


# ══════════════════════════════════════════════════════════════════════
# Redaction / finalized-money rules
# ══════════════════════════════════════════════════════════════════════

def test_draft_and_revoked_have_no_final_money(client):
    draft = _insert_invoice(MOBILE, state="draft", shipping=9000, total=999999)
    revoked = _insert_invoice(MOBILE, state="revoked", shipping=9000, total=999999)

    token = _get_token(client, MOBILE)
    items = client.get(BASE, headers=_auth(token)).json()["items"]
    entries = {e["id"]: e for e in items}

    for inv_id in (draft, revoked):
        entry = entries[inv_id]
        assert "total_toman" not in entry
        assert "shipping_toman" not in entry
        assert "unit_toman" not in entry["items"][0]
        assert "line_total_toman" not in entry["items"][0]
        # quantities / names are still shown.
        assert entry["items"][0]["qty"] == 2


def test_approved_and_paid_carry_frozen_money(client):
    approved = _insert_invoice(
        MOBILE, state="approved", shipping=12000, total=312000,
        items=[{"description": "قطعه الف", "qty": 2, "unit_toman": 150000, "line_total_toman": 300000}],
    )
    paid = _insert_invoice(
        MOBILE, state="paid", shipping=0, total=50000,
        items=[{"description": "قطعه ب", "qty": 1, "unit_toman": 50000, "line_total_toman": 50000}],
    )

    token = _get_token(client, MOBILE)
    entries = {e["id"]: e for e in client.get(BASE, headers=_auth(token)).json()["items"]}

    assert entries[approved]["total_toman"] == 312000
    assert entries[approved]["shipping_toman"] == 12000
    assert entries[approved]["items"][0]["unit_toman"] == 150000
    assert entries[paid]["state"] == "paid"
    assert entries[paid]["total_toman"] == 50000


def test_forbidden_staff_fields_are_absent(client):
    req = _insert_request(MOBILE)
    _insert_invoice(
        MOBILE, state="approved", request_id=req, token_hash="deadbeef" * 8,
        internal_note="یادداشت داخلی محرمانه", address="آدرس کامل محرمانه", handle="@staff_handle",
    )

    token = _get_token(client, MOBILE)
    resp = client.get(BASE, headers=_auth(token))
    items = resp.json()["items"]

    for entry in items:
        allowed = _REQUEST_KEYS if entry["kind"] == "request" else _INVOICE_KEYS
        assert set(entry) <= allowed, entry
        assert "mobile" not in entry

    text = resp.text
    for leaked in (
        "internal_note", "یادداشت داخلی محرمانه", "آدرس کامل محرمانه",
        "messenger_handle", "@staff_handle", "token_hash", "deadbeef",
        "provider_id", "providerid", "specification",
    ):
        assert leaked not in text, leaked


def test_no_raw_payment_link_or_token_leaks(client, auth_headers):
    created = client.post(
        f"{BASE.rsplit('/history', 1)[0]}/staff/invoices",
        headers=auth_headers,
        json={
            "customer_name": "رضا", "mobile": MOBILE, "messenger": "telegram",
            "shipping_toman": 0,
            "items": [{"description": "قطعه", "qty": 1, "unit_toman": 100000}],
        },
    )
    assert created.status_code == 201, created.text
    inv_id = created.json()["id"]
    approved = client.post(
        f"{BASE.rsplit('/history', 1)[0]}/staff/invoices/{inv_id}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    raw_token = approved.json()["share_url"].rsplit("/", 1)[-1]
    assert raw_token

    token = _get_token(client, MOBILE)
    resp = client.get(BASE, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert raw_token not in resp.text
    assert "share_url" not in resp.text and "/pay/" not in resp.text
    for entry in resp.json()["items"]:
        assert "token" not in entry and "payment_url" not in entry


# ══════════════════════════════════════════════════════════════════════
# Pagination / ordering
# ══════════════════════════════════════════════════════════════════════

def test_pagination_is_stable_without_repeats(client):
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ids = [_insert_request(MOBILE, created_at=base + timedelta(minutes=i)) for i in range(5)]

    token = _get_token(client, MOBILE)
    first = client.get(f"{BASE}?limit=2&offset=0", headers=_auth(token)).json()
    assert first["has_more"] is True
    assert [e["id"] for e in first["items"]] == [ids[4], ids[3]]

    second = client.get(f"{BASE}?limit=2&offset=2", headers=_auth(token)).json()
    assert second["has_more"] is True
    assert [e["id"] for e in second["items"]] == [ids[2], ids[1]]

    third = client.get(f"{BASE}?limit=2&offset=4", headers=_auth(token)).json()
    assert third["has_more"] is False
    assert [e["id"] for e in third["items"]] == [ids[0]]

    seen = [e["id"] for e in first["items"] + second["items"] + third["items"]]
    assert len(seen) == len(set(seen)) == 5


def test_has_more_false_when_exactly_limit_rows(client):
    base = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(2):
        _insert_request(MOBILE, created_at=base + timedelta(minutes=i))
    token = _get_token(client, MOBILE)
    page = client.get(f"{BASE}?limit=2", headers=_auth(token)).json()
    assert page["has_more"] is False and len(page["items"]) == 2


def test_tie_ordering_is_deterministic(client):
    """Equal ``created_at`` → order by kind, then id DESC."""
    stamp = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
    req_a = _insert_request(MOBILE, created_at=stamp)
    req_b = _insert_request(MOBILE, created_at=stamp)
    inv = _insert_invoice(MOBILE, state="draft", created_at=stamp)

    token = _get_token(client, MOBILE)
    items = client.get(f"{BASE}?limit=10", headers=_auth(token)).json()["items"]
    # "invoice" < "request"; within a kind the higher id sorts first.
    assert [(e["kind"], e["id"]) for e in items] == [
        ("invoice", inv), ("request", req_b), ("request", req_a),
    ]


def test_limit_and_offset_bounds(client):
    token = _get_token(client, MOBILE)
    for query in ("limit=0", "limit=51", "offset=-1"):
        r = client.get(f"{BASE}?{query}", headers=_auth(token))
        assert r.status_code == 422, (query, r.status_code)
        assert r.headers["Cache-Control"] == "no-store"


# ══════════════════════════════════════════════════════════════════════
# No disclosure / fail closed / no-store
# ══════════════════════════════════════════════════════════════════════

def test_empty_number_is_not_disclosed_before_or_after_otp(client):
    # Before verification: no header → 401, never a 404 or an empty list.
    pre = client.get(BASE)
    assert pre.status_code == 401
    assert "items" not in pre.json()

    # OTP issue for an empty number looks identical to a rich one.
    issue = client.post(f"{BASE}/otp", json={"mobile": MOBILE})
    assert issue.status_code == 200
    assert set(issue.json()) == {"challenge_id", "expires_in", "resend_after", "delivery", "masked_mobile"}

    verified = _verify_code(client, MOBILE, issue.json()["challenge_id"])
    assert verified.status_code == 200, verified.text
    listing = client.get(BASE, headers=_auth(verified.json()["token"]))
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "has_more": False}


def test_transport_failure_fails_closed(client):
    _SMS["sender"].return_value = False
    r = client.post(f"{BASE}/otp", json={"mobile": MOBILE})
    assert r.status_code == 503, r.text
    assert r.headers["Cache-Control"] == "no-store"

    # No challenge and no session can exist after an undelivered code.
    from app.models import CommerceHistoryOtpChallenge, CommerceHistorySession

    db = _db()
    try:
        assert db.query(CommerceHistoryOtpChallenge).count() == 0
        assert db.query(CommerceHistorySession).count() == 0
    finally:
        db.close()


def test_validation_and_throttle_errors_are_no_store(client):
    # Surplus field → 422.
    extra = client.post(f"{BASE}/otp", json={"mobile": MOBILE, "x": 1})
    assert extra.status_code == 422, extra.text
    assert extra.headers["Cache-Control"] == "no-store"
    assert extra.headers["Referrer-Policy"] == "no-referrer"

    # Resend cooldown → 429 (same mobile twice).
    assert client.post(f"{BASE}/otp", json={"mobile": MOBILE}).status_code == 200
    throttled = client.post(f"{BASE}/otp", json={"mobile": MOBILE})
    assert throttled.status_code == 429, throttled.text
    assert throttled.headers["Cache-Control"] == "no-store"
    assert throttled.headers["Referrer-Policy"] == "no-referrer"
    # The 429 body never reveals orders or the full number.
    assert MOBILE not in throttled.text


def test_slowapi_rate_limit_429_is_no_store(client):
    # Distinct mobiles avoid the per-mobile cooldown, so the 3/minute limiter is
    # what refuses the fourth call.
    for suffix in ("1", "2", "3", "4"):
        r = client.post(f"{BASE}/otp", json={"mobile": f"0912000000{suffix}"})
        if suffix == "4":
            assert r.status_code == 429, r.text
            assert r.headers["Cache-Control"] == "no-store"
            assert r.headers["Referrer-Policy"] == "no-referrer"
        else:
            assert r.status_code == 200, r.text


# ══════════════════════════════════════════════════════════════════════
# Service-level ordering (thin unit check)
# ══════════════════════════════════════════════════════════════════════

def test_list_history_reads_only_the_requested_mobile(client):
    from app.services import commerce_history

    stamp = datetime(2026, 4, 1, 8, 0, 0, tzinfo=timezone.utc)
    _insert_request(MOBILE, created_at=stamp)
    _insert_request(OTHER, created_at=stamp)

    db = _db()
    try:
        rows = commerce_history.list_history(db, MOBILE, limit=10, offset=0)
    finally:
        db.close()
    assert len(rows) == 1 and rows[0]["kind"] == "request"
