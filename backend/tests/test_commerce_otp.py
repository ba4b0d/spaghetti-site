"""Cart OTP — storefront one-time-code issue/verify and the request gate.

Covers the public ``POST /api/v1/commerce/requests/otp`` endpoint, the OTP
service (``app.services.commerce_otp``) and the requirement that
``POST /api/v1/commerce/requests`` only persists a request after the code is
verified.

No real SMS is ever sent: every test patches ``send_customer_otp`` (the name the
service imports and calls) with a fake, so the live SMS.ir API is never
touched regardless of the environment. Nothing is left in the DB — the shared
``client`` fixture drops all tables after each test.
"""
import hashlib

import pytest
from unittest.mock import MagicMock

from app.services import commerce_otp
from app.services.commerce_otp import (
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN_SECONDS,
    OTP_TTL_SECONDS,
)

BASE = "/api/v1/commerce"
MOBILE = "09123456789"


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter(client):
    """Reset slowapi counters so the shared 3/minute / 5/minute budget is fresh."""
    from app.main import app

    app.state.limiter._limiter.storage.reset()
    yield


@pytest.fixture(autouse=True)
def fake_sms(monkeypatch):
    """Replace the SMS transport so no code is ever really sent.

    Patched on the ``commerce_notifications`` module object because that is the
    name ``commerce_otp`` looks up at call time (``commerce_notifications.
    send_customer_otp``).
    """
    from app.services import commerce_notifications

    sender = MagicMock(return_value=True)
    monkeypatch.setattr(commerce_notifications, "send_customer_otp", sender)
    return sender


# ── Helpers ──────────────────────────────────────────────────────────

def _create_product(client, auth_headers, *, name="محصول تستی", price=50000):
    resp = client.post(
        "/api/v1/products",
        json={"name": name, "weight_g": 40, "print_time_hours": 1, "final_price": price},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _issue(client, mobile=MOBILE):
    return client.post(f"{BASE}/requests/otp", json={"mobile": mobile})


def _sent_code(sender):
    """The code handed to the (faked) SMS transport on the last send."""
    call = sender.call_args_list[-1]
    if len(call.args) > 1:
        return call.args[1]
    return call.kwargs["code"]


def _wrong_code(code):
    """A code guaranteed not to equal the real one."""
    return "00000" if code != "00000" else "11111"


def _request_payload(product_id, challenge_id, code, *, mobile=MOBILE, qty=1):
    return {
        "customer_name": "رضا",
        "mobile": mobile,
        "messenger": "telegram",
        "items": [{"product_id": product_id, "qty": qty}],
        "otp_challenge_id": challenge_id,
        "otp_code": code,
    }


def _challenge_rows(mobile):
    """Plain-dict snapshots of the challenge rows for ``mobile``."""
    from app.models import CommerceOtpChallenge
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        rows = (
            db.query(CommerceOtpChallenge)
            .filter(CommerceOtpChallenge.mobile == mobile)
            .order_by(CommerceOtpChallenge.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "mobile": r.mobile,
                "code_salt": r.code_salt,
                "code_hash": r.code_hash,
                "expires_at": r.expires_at,
                "consumed_at": r.consumed_at,
                "attempts": r.attempts,
                "client_ip_hash": r.client_ip_hash,
            }
            for r in rows
        ]
    finally:
        db.close()


def _request_count():
    from app.models import CommerceRequest
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return db.query(CommerceRequest).count()
    finally:
        db.close()


def _expire_challenge(challenge_id):
    from datetime import datetime, timedelta, timezone

    from app.models import CommerceOtpChallenge
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        row = (
            db.query(CommerceOtpChallenge)
            .filter(CommerceOtpChallenge.id == challenge_id)
            .first()
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Issuing
# ══════════════════════════════════════════════════════════════════════

def test_issue_sends_one_sms_and_returns_hints(client, fake_sms):
    r = _issue(client)
    assert r.status_code == 200, r.text
    body = r.json()

    assert isinstance(body["challenge_id"], int)
    assert body["delivery"] == "sms"
    assert body["expires_in"] == OTP_TTL_SECONDS
    assert body["resend_after"] == OTP_RESEND_COOLDOWN_SECONDS
    assert body["masked_mobile"]  # masked, never the full number echoed raw

    assert fake_sms.call_count == 1
    assert fake_sms.call_args.args[0] == MOBILE


def test_cart_otp_ttl_is_five_minutes(client, fake_sms):
    """The cart code stays valid for five minutes (requirement: 300s).

    The SMS template's ``#TIME#`` placeholder is derived from ``OTP_TTL_SECONDS``
    (``commerce_notifications._otp_ttl_minutes`` rounds up to whole minutes), so
    a 300s TTL must render as ``5`` for the customer, and the issue response must
    advertise the same 300s window.
    """
    from app.services import commerce_notifications

    assert OTP_TTL_SECONDS == 300
    assert commerce_notifications._otp_ttl_minutes() == "5"

    r = _issue(client)
    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] == 300


def test_issued_code_is_never_echoed_nor_stored_in_plaintext(client, fake_sms):
    r = _issue(client)
    code = _sent_code(fake_sms)

    # Server-generated: a 5-digit numeric code.
    assert len(code) == 5 and code.isdigit()
    # Never in the response body...
    assert code not in r.text

    # ...and only a salted hash is persisted.
    rows = _challenge_rows(MOBILE)
    assert len(rows) == 1
    row = rows[0]
    assert len(row["code_hash"]) == 64 and len(row["code_salt"]) == 32
    assert row["code_hash"] != code and row["code_salt"] != code
    expected = hashlib.sha256(f"{row['code_salt']}{code}".encode("utf-8")).hexdigest()
    assert row["code_hash"] == expected


def test_invalid_mobile_is_rejected_with_400(client, fake_sms):
    from app.main import app

    for bad in ("123", "0812345678", "0912345678a", "۰۹۱۲۳۴۵۶۷۸۹"):
        # Each probe is a fresh limiter budget (the endpoint allows 3/minute).
        app.state.limiter._limiter.storage.reset()
        r = _issue(client, mobile=bad)
        assert r.status_code == 400, (bad, r.text)
    assert fake_sms.call_count == 0


def test_otp_endpoint_is_rate_limited(client, fake_sms):
    # Distinct mobiles avoid the resend cooldown so only the limiter can fire.
    mobiles = [f"0912345{i:04d}" for i in range(4)]
    statuses = [_issue(client, mobile=m).status_code for m in mobiles]
    assert statuses[:3] == [200, 200, 200], statuses
    assert statuses[3] == 429


# ══════════════════════════════════════════════════════════════════════
# Throttling
# ══════════════════════════════════════════════════════════════════════

def test_resend_cooldown_enforced(client, fake_sms):
    assert _issue(client).status_code == 200
    second = _issue(client)
    assert second.status_code == 429, second.text
    # The cooldown blocks the second SMS, not just the response.
    assert fake_sms.call_count == 1


def test_hourly_per_mobile_cap_enforced(client, fake_sms, monkeypatch):
    monkeypatch.setattr(commerce_otp, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(commerce_otp, "OTP_MAX_SENDS_PER_HOUR", 2)

    assert _issue(client).status_code == 200
    assert _issue(client).status_code == 200
    third = _issue(client)
    assert third.status_code == 429, third.text
    assert fake_sms.call_count == 2


# ══════════════════════════════════════════════════════════════════════
# Delivery failure
# ══════════════════════════════════════════════════════════════════════

def test_sms_failure_leaves_no_live_challenge(client, fake_sms):
    fake_sms.return_value = False

    r = _issue(client)
    assert r.status_code == 503, r.text

    # The unusable challenge is deleted — nothing live is left behind.
    assert [c for c in _challenge_rows(MOBILE) if c["consumed_at"] is None] == []


# ══════════════════════════════════════════════════════════════════════
# Verifying (service level)
# ══════════════════════════════════════════════════════════════════════

def test_successful_verify_consumes_challenge(client, fake_sms):
    issued = _issue(client).json()
    code = _sent_code(fake_sms)

    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        challenge = commerce_otp.verify_challenge(
            db, issued["challenge_id"], code, MOBILE
        )
        assert challenge.consumed_at is not None
    finally:
        db.close()

    rows = _challenge_rows(MOBILE)
    assert rows[0]["consumed_at"] is not None
    assert rows[0]["attempts"] == 0


def test_successful_verify_then_second_verify_fails(client, fake_sms):
    issued = _issue(client).json()
    code = _sent_code(fake_sms)

    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        commerce_otp.verify_challenge(db, issued["challenge_id"], code, MOBILE)
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(db, issued["challenge_id"], code, MOBILE)
    finally:
        db.close()


def test_wrong_code_increments_attempts_and_reports_remainder(client, fake_sms):
    issued = _issue(client).json()
    wrong = _wrong_code(_sent_code(fake_sms))

    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        with pytest.raises(commerce_otp.OtpInvalid) as excinfo:
            commerce_otp.verify_challenge(db, issued["challenge_id"], wrong, MOBILE)
        assert excinfo.value.remaining_attempts == OTP_MAX_ATTEMPTS - 1
    finally:
        db.close()

    rows = _challenge_rows(MOBILE)
    assert rows[0]["attempts"] == 1
    assert rows[0]["consumed_at"] is None


def test_exhausted_attempts_kill_the_challenge(client, fake_sms):
    issued = _issue(client).json()
    code = _sent_code(fake_sms)
    wrong = _wrong_code(code)

    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        for _ in range(OTP_MAX_ATTEMPTS):
            with pytest.raises(commerce_otp.OtpInvalid):
                commerce_otp.verify_challenge(db, issued["challenge_id"], wrong, MOBILE)
        # Exhausted: even the correct code is now refused.
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(db, issued["challenge_id"], code, MOBILE)
    finally:
        db.close()

    rows = _challenge_rows(MOBILE)
    assert rows[0]["attempts"] == OTP_MAX_ATTEMPTS
    assert rows[0]["consumed_at"] is not None


def test_expired_challenge_is_rejected(client, fake_sms):
    issued = _issue(client).json()
    code = _sent_code(fake_sms)
    _expire_challenge(issued["challenge_id"])

    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        with pytest.raises(commerce_otp.OtpExpired):
            commerce_otp.verify_challenge(db, issued["challenge_id"], code, MOBILE)
    finally:
        db.close()


def test_unknown_challenge_is_rejected(client, fake_sms):
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(db, 999999, "00000", MOBILE)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# The request gate
# ══════════════════════════════════════════════════════════════════════

def test_request_without_otp_fields_is_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    payload = {
        "customer_name": "رضا",
        "mobile": MOBILE,
        "messenger": "telegram",
        "items": [{"product_id": product["id"], "qty": 1}],
    }
    r = client.post(f"{BASE}/requests", json=payload)
    assert r.status_code == 422, r.text
    assert _request_count() == 0


def test_request_with_bad_code_is_400_and_creates_no_request(client, auth_headers, fake_sms):
    product = _create_product(client, auth_headers)
    issued = _issue(client).json()
    wrong = _wrong_code(_sent_code(fake_sms))

    r = client.post(
        f"{BASE}/requests",
        json=_request_payload(product["id"], issued["challenge_id"], wrong),
    )
    assert r.status_code == 400, r.text
    assert _request_count() == 0


def test_request_with_mobile_mismatch_is_rejected(client, auth_headers, fake_sms):
    product = _create_product(client, auth_headers)
    issued = _issue(client).json()
    code = _sent_code(fake_sms)

    r = client.post(
        f"{BASE}/requests",
        json=_request_payload(
            product["id"], issued["challenge_id"], code, mobile="09120000000"
        ),
    )
    assert r.status_code == 400, r.text
    assert _request_count() == 0


def test_happy_path_creates_the_request(client, auth_headers, fake_sms):
    product = _create_product(client, auth_headers, name="فیگور تستی", price=120000)
    issued = _issue(client).json()
    code = _sent_code(fake_sms)

    r = client.post(
        f"{BASE}/requests",
        json=_request_payload(product["id"], issued["challenge_id"], code, qty=2),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "pending_review"
    assert body["receipt_id"]
    # The code never leaks into the acknowledgement.
    assert code not in r.text
    assert _request_count() == 1

    listing = client.get(f"{BASE}/staff/requests", headers=auth_headers).json()
    assert len(listing) == 1
    assert listing[0]["mobile"] == MOBILE

    # The challenge is consumed by the successful request.
    assert _challenge_rows(MOBILE)[0]["consumed_at"] is not None


# ══════════════════════════════════════════════════════════════════════
# Concurrency / atomicity regressions
# ══════════════════════════════════════════════════════════════════════

def test_concurrent_issue_sends_exactly_one_sms(fake_sms, monkeypatch):
    """Two simultaneous issues for one mobile must yield one SMS, one row.

    A check-then-insert without serialization lets both issuers read "no recent
    challenge" before either writes, so both send a (costly, real) SMS. The
    service takes SQLite's write lock up front (``BEGIN IMMEDIATE``), so the
    second issuer blocks until the first commits and then sees its row. The
    ``_latest_for_mobile`` delay widens the check→insert window so an
    unserialized implementation would reliably double-send here.
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from tests.conftest import TestSessionLocal

    real_latest = commerce_otp._latest_for_mobile

    def slow_latest(db, mobile):  # noqa: ANN001 - test seam
        time.sleep(0.05)
        return real_latest(db, mobile)

    monkeypatch.setattr(commerce_otp, "_latest_for_mobile", slow_latest)

    barrier = threading.Barrier(2)

    def _run():
        db = TestSessionLocal()
        try:
            barrier.wait(timeout=5)
            try:
                commerce_otp.issue_challenge(db, MOBILE, client_ip="203.0.113.7")
                return "sent"
            except commerce_otp.OtpThrottled:
                return "throttled"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = [fut.result() for fut in [ex.submit(_run) for _ in range(2)]]

    assert sorted(results) == ["sent", "throttled"], results
    assert fake_sms.call_count == 1
    # Exactly one live challenge survives (the loser wrote nothing).
    assert len([c for c in _challenge_rows(MOBILE) if c["consumed_at"] is None]) == 1


def test_stale_verifier_loses_the_single_use_race(client, fake_sms):
    """A verifier holding a stale view cannot consume an already-claimed code.

    Session A loads the challenge (``consumed_at is None``), session B then
    verifies it, and A finally submits the *correct* code against its stale
    copy. The atomic conditional claim only matches an unconsumed row, so A's
    UPDATE affects 0 rows and it is rejected — exactly one verifier wins.
    """
    from app.models import CommerceOtpChallenge
    from tests.conftest import TestSessionLocal

    issued = _issue(client).json()
    code = _sent_code(fake_sms)
    cid = issued["challenge_id"]

    db_a = TestSessionLocal()
    db_b = TestSessionLocal()
    try:
        stale = db_a.query(CommerceOtpChallenge).filter_by(id=cid).first()
        assert stale is not None and stale.consumed_at is None

        # B consumes the challenge first (real, committed claim).
        commerce_otp.verify_challenge(db_b, cid, code, MOBILE)

        # A replays the same correct code from its stale identity-map view.
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(db_a, cid, code, MOBILE)
    finally:
        db_a.close()
        db_b.close()


def test_commit_false_claim_rolls_back_with_the_caller(client, fake_sms):
    """A successful ``commit=False`` claim is undone when the caller rolls back.

    This is the seam the request endpoint relies on: a failed creation rolls
    the (uncommitted) OTP claim back, leaving the proof usable.
    """
    from tests.conftest import TestSessionLocal

    issued = _issue(client).json()
    code = _sent_code(fake_sms)
    cid = issued["challenge_id"]

    db = TestSessionLocal()
    try:
        commerce_otp.verify_challenge(db, cid, code, MOBILE, commit=False)
        # Not durable while the caller's transaction is open...
        db.rollback()
    finally:
        db.close()
    assert _challenge_rows(MOBILE)[0]["consumed_at"] is None

    # ...so the (still unexpired) proof can be used once, for real.
    db2 = TestSessionLocal()
    try:
        challenge = commerce_otp.verify_challenge(db2, cid, code, MOBILE)
        assert challenge.consumed_at is not None
    finally:
        db2.close()


def test_commit_false_claim_persists_when_the_caller_commits(client, fake_sms):
    from tests.conftest import TestSessionLocal

    issued = _issue(client).json()
    code = _sent_code(fake_sms)

    db = TestSessionLocal()
    try:
        commerce_otp.verify_challenge(
            db, issued["challenge_id"], code, MOBILE, commit=False
        )
        db.commit()
    finally:
        db.close()
    assert _challenge_rows(MOBILE)[0]["consumed_at"] is not None


def test_commit_false_failed_attempt_survives_the_caller_rollback(client, fake_sms):
    """Wrong-code bookkeeping is durable even when the caller rolls back.

    Otherwise a brute-forcer could reset the attempt budget simply by making
    the request creation fail and rolling it back.
    """
    from tests.conftest import TestSessionLocal

    issued = _issue(client).json()
    wrong = _wrong_code(_sent_code(fake_sms))

    db = TestSessionLocal()
    try:
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(
                db, issued["challenge_id"], wrong, MOBILE, commit=False
            )
        db.rollback()  # caller abandons its request
    finally:
        db.close()

    rows = _challenge_rows(MOBILE)
    assert rows[0]["attempts"] == 1
    assert rows[0]["consumed_at"] is None
