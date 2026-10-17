"""History OTP + tab session — purpose isolation, throttling, single-use.

Task 1 tests (service level; the public routes arrive in a later task).

What is being proven here:

* the history flow keeps its **own** challenge table, so a checkout OTP can
  never verify (or be consumed by) a history challenge, and a history challenge
  can never authorize ``POST /commerce/requests``;
* the **SMS budget is shared**: alternating between checkout and history must
  not multiply a number's or a client IP's hourly allowance;
* codes and bearers are stored only as hashes, single-use is atomic, wrong
  attempts are durable, an expired/revoked session resolves to nothing, and a
  failed SMS send leaves no usable challenge behind.

No real SMS: ``commerce_notifications.send_customer_otp`` (the name the service
resolves at call time) is always patched with a fake. The shared ``client``
fixture drops every table after each test.
"""
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services import commerce_history_auth, commerce_otp
from app.services.commerce_history_auth import (
    HISTORY_OTP_MAX_ATTEMPTS,
    HISTORY_OTP_TTL_SECONDS,
    HISTORY_SESSION_TTL_SECONDS,
)

BASE = "/api/v1/commerce"
MOBILE = "09123456789"
OTHER_MOBILE = "09120000000"
IP = "203.0.113.7"


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fake_sms(monkeypatch):
    """Replace the SMS transport so no code is ever really sent."""
    from app.services import commerce_notifications

    sender = MagicMock(return_value=True)
    monkeypatch.setattr(commerce_notifications, "send_customer_otp", sender)
    return sender


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset slowapi counters (shared with the checkout endpoints)."""
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


def _issue(mobile=MOBILE, *, client_ip=None):
    """Issue a history challenge; returns a plain snapshot (session closed)."""
    db = _db()
    try:
        challenge = commerce_history_auth.issue_history_challenge(
            db, mobile, client_ip=client_ip
        )
        return {
            "id": challenge.id,
            "mobile": challenge.mobile,
            "expires_at": challenge.expires_at,
        }
    finally:
        db.close()


def _verify(challenge_id, code, mobile=MOBILE):
    db = _db()
    try:
        return commerce_history_auth.verify_history_challenge(
            db, challenge_id, code, mobile
        )
    finally:
        db.close()


def _resolve(bearer):
    db = _db()
    try:
        return commerce_history_auth.resolve_history_session(db, bearer)
    finally:
        db.close()


def _revoke(bearer):
    db = _db()
    try:
        commerce_history_auth.revoke_history_session(db, bearer)
    finally:
        db.close()


def _sent_code(sender):
    """The code handed to the (faked) SMS transport on the last send."""
    call = sender.call_args_list[-1]
    if len(call.args) > 1:
        return call.args[1]
    return call.kwargs["code"]


def _wrong_code(code):
    return "00000" if code != "00000" else "11111"


def _challenge_rows(mobile=MOBILE):
    from app.models import CommerceHistoryOtpChallenge

    db = _db()
    try:
        rows = (
            db.query(CommerceHistoryOtpChallenge)
            .filter(CommerceHistoryOtpChallenge.mobile == mobile)
            .order_by(CommerceHistoryOtpChallenge.id.asc())
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


def _session_rows(mobile=None):
    from app.models import CommerceHistorySession

    db = _db()
    try:
        query = db.query(CommerceHistorySession)
        if mobile is not None:
            query = query.filter(CommerceHistorySession.mobile == mobile)
        return [
            {
                "id": r.id,
                "token_hash": r.token_hash,
                "mobile": r.mobile,
                "expires_at": r.expires_at,
                "revoked_at": r.revoked_at,
                "created_at": r.created_at,
            }
            for r in query.order_by(CommerceHistorySession.id.asc()).all()
        ]
    finally:
        db.close()


def _expire_challenge(challenge_id):
    from app.models import CommerceHistoryOtpChallenge

    db = _db()
    try:
        db.query(CommerceHistoryOtpChallenge).filter(
            CommerceHistoryOtpChallenge.id == challenge_id
        ).update(
            {CommerceHistoryOtpChallenge.expires_at: datetime.now(timezone.utc) - timedelta(seconds=5)},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()


def _expire_sessions():
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


def _create_product(client, auth_headers, *, name="محصول تستی", price=50000):
    resp = client.post(
        "/api/v1/products",
        json={"name": name, "weight_g": 40, "print_time_hours": 1, "final_price": price},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _request_count():
    from app.models import CommerceRequest

    db = _db()
    try:
        return db.query(CommerceRequest).count()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Issuing
# ══════════════════════════════════════════════════════════════════════

def test_history_tunables_match_the_design():
    assert HISTORY_OTP_TTL_SECONDS == 300
    assert HISTORY_OTP_MAX_ATTEMPTS == 5
    assert HISTORY_SESSION_TTL_SECONDS == 30 * 60
    # The SMS budget numbers are the shared (checkout) ones.
    assert commerce_otp.OTP_RESEND_COOLDOWN_SECONDS == 60
    assert commerce_otp.OTP_MAX_SENDS_PER_HOUR == 5
    assert commerce_otp.OTP_MAX_SENDS_PER_HOUR_IP == 20


def test_issue_rejects_a_non_canonical_mobile_without_sending(fake_sms):
    for bad in ("123", "0812345678", "0912345678a", "۰۹۱۲۳۴۵۶۷۸۹", "0912345678", ""):
        db = _db()
        try:
            with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
                commerce_history_auth.issue_history_challenge(db, bad)
        finally:
            db.close()

    assert fake_sms.call_count == 0
    assert _challenge_rows() == []

    # A canonically-valid value is accepted and stored exactly.
    assert commerce_history_auth.canonical_mobile(f" {MOBILE} ") == MOBILE


def test_issue_sends_one_sms_and_persists_only_a_salted_hash(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)

    assert fake_sms.call_count == 1
    assert fake_sms.call_args.args[0] == MOBILE
    # Server-generated five-digit numeric code.
    assert len(code) == 5 and code.isdigit()
    # The challenge snapshot carries no plaintext code.
    assert "code" not in issued and code not in str(issued)

    rows = _challenge_rows()
    assert len(rows) == 1
    row = rows[0]
    assert len(row["code_hash"]) == 64 and len(row["code_salt"]) == 32
    expected = hashlib.sha256(f"{row['code_salt']}{code}".encode("utf-8")).hexdigest()
    assert row["code_hash"] == expected
    assert code not in (row["code_hash"], row["code_salt"])
    assert row["mobile"] == MOBILE
    assert row["consumed_at"] is None and row["attempts"] == 0


def test_client_ip_is_stored_only_as_a_hash(fake_sms):
    _issue(client_ip=IP)

    row = _challenge_rows()[0]
    assert row["client_ip_hash"] == hashlib.sha256(IP.encode("utf-8")).hexdigest()
    assert row["client_ip_hash"] != IP


def test_delivery_failure_leaves_no_usable_challenge_and_no_session(fake_sms):
    fake_sms.return_value = False

    with pytest.raises(commerce_history_auth.HistoryOtpDeliveryError):
        _issue()

    # The unusable challenge is deleted — nothing live (or dangling) remains.
    assert [c for c in _challenge_rows() if c["consumed_at"] is None] == []
    assert _session_rows() == []


# ══════════════════════════════════════════════════════════════════════
# Verifying
# ══════════════════════════════════════════════════════════════════════

def test_valid_verify_returns_a_hashed_bearer_bound_to_the_exact_mobile(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)

    bearer, expires_at = _verify(issued["id"], code)

    assert isinstance(bearer, str) and len(bearer) >= 40
    sessions = _session_rows()
    assert len(sessions) == 1
    row = sessions[0]
    # Only the SHA-256 hash of the bearer is persisted.
    assert row["token_hash"] == hashlib.sha256(bearer.encode("utf-8")).hexdigest()
    assert bearer not in (row["token_hash"], row["mobile"])
    assert row["mobile"] == MOBILE
    assert row["revoked_at"] is None
    # The absolute TTL ceiling is 30 minutes, server-side.
    skew = abs(
        (expires_at - (datetime.now(timezone.utc) + timedelta(seconds=HISTORY_SESSION_TTL_SECONDS)))
        .total_seconds()
    )
    assert skew < 60, expires_at

    assert _resolve(bearer) == MOBILE
    assert _resolve(bearer) != OTHER_MOBILE
    # The challenge that authorized the session is consumed.
    assert _challenge_rows()[0]["consumed_at"] is not None
    assert _challenge_rows()[0]["attempts"] == 0


def test_the_claim_and_the_session_land_together(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)
    wrong = _wrong_code(code)

    # A wrong code consumes nothing and creates no session.
    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], wrong, MOBILE)
    finally:
        db.close()
    assert _challenge_rows()[0]["consumed_at"] is None
    assert _session_rows() == []

    assert _verify(issued["id"], code)
    assert _challenge_rows()[0]["consumed_at"] is not None
    assert len(_session_rows()) == 1


def test_a_challenge_is_single_use(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)

    bearer, _ = _verify(issued["id"], code)
    assert bearer

    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], code, MOBILE)
    finally:
        db.close()

    assert len(_session_rows(MOBILE)) == 1


def test_wrong_code_increments_attempts_and_reports_remainder(fake_sms):
    issued = _issue()
    wrong = _wrong_code(_sent_code(fake_sms))

    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid) as excinfo:
            commerce_history_auth.verify_history_challenge(db, issued["id"], wrong, MOBILE)
        assert excinfo.value.remaining_attempts == HISTORY_OTP_MAX_ATTEMPTS - 1
    finally:
        db.close()

    rows = _challenge_rows()
    assert rows[0]["attempts"] == 1 and rows[0]["consumed_at"] is None
    assert _session_rows() == []


def test_wrong_attempt_bookkeeping_survives_a_caller_rollback(fake_sms):
    issued = _issue()
    wrong = _wrong_code(_sent_code(fake_sms))

    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], wrong, MOBILE)
        db.rollback()  # caller abandons its request
    finally:
        db.close()

    assert _challenge_rows()[0]["attempts"] == 1


def test_exhausted_attempts_kill_the_challenge(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)
    wrong = _wrong_code(code)

    db = _db()
    try:
        for _ in range(HISTORY_OTP_MAX_ATTEMPTS):
            with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
                commerce_history_auth.verify_history_challenge(db, issued["id"], wrong, MOBILE)
        # Exhausted: even the correct code is refused.
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], code, MOBILE)
    finally:
        db.close()

    rows = _challenge_rows()
    assert rows[0]["attempts"] == HISTORY_OTP_MAX_ATTEMPTS
    assert rows[0]["consumed_at"] is not None
    assert _session_rows() == []


def test_expired_challenge_is_rejected(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)
    _expire_challenge(issued["id"])

    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], code, MOBILE)
    finally:
        db.close()

    assert _session_rows() == []


def test_unknown_challenge_and_wrong_mobile_are_rejected(fake_sms):
    issued = _issue()
    code = _sent_code(fake_sms)

    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, 999999, "00000", MOBILE)
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, issued["id"], code, OTHER_MOBILE)
    finally:
        db.close()

    assert _session_rows() == []
    # The wrong-mobile probe must not have consumed the challenge.
    assert _challenge_rows()[0]["consumed_at"] is None


# ══════════════════════════════════════════════════════════════════════
# Purpose isolation (checkout ⇄ history)
# ══════════════════════════════════════════════════════════════════════

def test_otp_purposes_are_isolated(fake_sms, monkeypatch):
    """A code — or a challenge id — from one flow never works in the other."""
    # Issued together in one test, so the shared cooldown is patched away.
    monkeypatch.setattr(commerce_otp, "OTP_RESEND_COOLDOWN_SECONDS", 0)

    db = _db()
    try:
        checkout = commerce_otp.issue_challenge(db, MOBILE)
        checkout_id = checkout.id
    finally:
        db.close()
    checkout_code = _sent_code(fake_sms)

    history = _issue()
    history_code = _sent_code(fake_sms)
    assert history_code != checkout_code  # independent random codes

    # 1. A checkout challenge cannot authenticate a history session — neither by
    #    its own id (unknown to the history table) nor when the other table
    #    happens to hold a row with the same numeric id.
    db = _db()
    try:
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, checkout_id, checkout_code, MOBILE)
        with pytest.raises(commerce_history_auth.HistoryOtpInvalid):
            commerce_history_auth.verify_history_challenge(db, history["id"], checkout_code, MOBILE)
    finally:
        db.close()
    assert _session_rows() == []

    # 2. The history challenge still verifies with its own code.
    bearer, _ = _verify(history["id"], history_code)
    assert _resolve(bearer) == MOBILE

    # 3. A history id/code cannot consume a checkout challenge.
    db = _db()
    try:
        with pytest.raises(commerce_otp.OtpInvalid):
            commerce_otp.verify_challenge(db, history["id"], history_code, MOBILE)
        # The checkout challenge is intact and verifies with its own code.
        claimed = commerce_otp.verify_challenge(db, checkout_id, checkout_code, MOBILE)
        assert claimed.consumed_at is not None
    finally:
        db.close()


def test_a_history_challenge_cannot_authorize_a_checkout_request(
    client, auth_headers, fake_sms
):
    """The history proof is not payment/cart authority: /requests needs its own."""
    product = _create_product(client, auth_headers)
    issued = _issue()
    code = _sent_code(fake_sms)

    resp = client.post(
        f"{BASE}/requests",
        json={
            "customer_name": "رضا",
            "mobile": MOBILE,
            "messenger": "telegram",
            "items": [{"product_id": product["id"], "qty": 1}],
            "otp_challenge_id": issued["id"],
            "otp_code": code,
        },
    )
    assert resp.status_code == 400, resp.text
    assert _request_count() == 0


# ══════════════════════════════════════════════════════════════════════
# Sessions: resolve / revoke / expiry
# ══════════════════════════════════════════════════════════════════════

def test_revoke_invalidates_the_session_and_is_idempotent(fake_sms):
    issued = _issue()
    bearer, _ = _verify(issued["id"], _sent_code(fake_sms))
    assert _resolve(bearer) == MOBILE

    _revoke(bearer)
    assert _resolve(bearer) is None
    assert _session_rows()[0]["revoked_at"] is not None

    revoked_at = _session_rows()[0]["revoked_at"]
    _revoke(bearer)                # idempotent
    _revoke("not-a-real-bearer")   # unknown bearer is a no-op
    assert _session_rows()[0]["revoked_at"] == revoked_at


def test_expired_session_is_rejected(fake_sms):
    issued = _issue()
    bearer, _ = _verify(issued["id"], _sent_code(fake_sms))
    assert _resolve(bearer) == MOBILE

    _expire_sessions()
    assert _resolve(bearer) is None


def test_unknown_or_empty_bearer_resolves_to_nothing():
    assert _resolve("definitely-not-a-token") is None
    assert _resolve("") is None
    assert _resolve(None) is None


def test_simultaneous_claims_yield_exactly_one_session(fake_sms):
    """Two concurrent verifies of one code: one session, one consumed challenge."""
    issued = _issue()
    code = _sent_code(fake_sms)
    barrier = threading.Barrier(2)

    def _run():
        db = _db()
        try:
            barrier.wait(timeout=5)
            try:
                bearer, _ = commerce_history_auth.verify_history_challenge(
                    db, issued["id"], code, MOBILE
                )
                return ("ok", bearer)
            except commerce_history_auth.HistoryOtpInvalid:
                return ("invalid", None)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = [fut.result(timeout=20) for fut in [ex.submit(_run) for _ in range(2)]]

    winners = [bearer for status, bearer in results if status == "ok"]
    assert len(winners) == 1, results
    assert [status for status, _ in results].count("invalid") == 1

    sessions = _session_rows()
    assert len(sessions) == 1
    assert sessions[0]["token_hash"] == hashlib.sha256(winners[0].encode("utf-8")).hexdigest()
    assert _resolve(winners[0]) == MOBILE


def test_the_auth_service_logs_nothing(fake_sms, caplog):
    """Codes, bearers and mobiles are never written to a log."""
    with caplog.at_level(logging.DEBUG):
        issued = _issue(client_ip=IP)
        code = _sent_code(fake_sms)
        bearer, _ = _verify(issued["id"], code)
        _resolve(bearer)
        _revoke(bearer)

    own_records = [r for r in caplog.records if "commerce_history_auth" in r.name]
    assert own_records == []


# ══════════════════════════════════════════════════════════════════════
# Shared cross-purpose SMS budget
# ══════════════════════════════════════════════════════════════════════

def test_the_hourly_sms_cap_is_shared_across_purposes(fake_sms, monkeypatch):
    monkeypatch.setattr(commerce_otp, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(commerce_otp, "OTP_MAX_SENDS_PER_HOUR", 2)

    db = _db()
    try:
        commerce_otp.issue_challenge(db, MOBILE)  # 1st send: checkout
    finally:
        db.close()
    _issue()                                      # 2nd send: history

    # The shared budget is exhausted for BOTH purposes.
    with pytest.raises(commerce_history_auth.HistoryOtpThrottled):
        _issue()
    db = _db()
    try:
        with pytest.raises(commerce_otp.OtpThrottled):
            commerce_otp.issue_challenge(db, MOBILE)
    finally:
        db.close()

    assert fake_sms.call_count == 2


def test_the_resend_cooldown_is_shared_across_purposes(fake_sms):
    _issue()  # history send

    db = _db()
    try:
        with pytest.raises(commerce_otp.OtpThrottled):
            commerce_otp.issue_challenge(db, MOBILE)  # within 60s of a history send
    finally:
        db.close()

    db = _db()
    try:
        commerce_otp.issue_challenge(db, OTHER_MOBILE)  # checkout send, other number
    finally:
        db.close()
    with pytest.raises(commerce_history_auth.HistoryOtpThrottled):
        _issue(OTHER_MOBILE)

    assert fake_sms.call_count == 2


def test_the_per_ip_sms_cap_is_shared_across_purposes(fake_sms, monkeypatch):
    monkeypatch.setattr(commerce_otp, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(commerce_otp, "OTP_MAX_SENDS_PER_HOUR", 50)
    monkeypatch.setattr(commerce_otp, "OTP_MAX_SENDS_PER_HOUR_IP", 2)

    _issue("09120000001", client_ip=IP)  # history send from IP
    db = _db()
    try:
        commerce_otp.issue_challenge(db, "09120000002", client_ip=IP)  # checkout send
    finally:
        db.close()

    with pytest.raises(commerce_history_auth.HistoryOtpThrottled):
        _issue("09120000003", client_ip=IP)  # 3rd send from the same IP

    # A different client IP is unaffected.
    _issue("09120000004", client_ip="198.51.100.9")
    assert fake_sms.call_count == 3


# ══════════════════════════════════════════════════════════════════════
# Error contract consumed by the (later) router
# ══════════════════════════════════════════════════════════════════════

def test_error_hierarchy_exposes_wait_and_remaining_attempts():
    assert issubclass(commerce_history_auth.HistoryOtpInvalid, commerce_history_auth.HistoryOtpError)
    assert issubclass(commerce_history_auth.HistoryOtpThrottled, commerce_history_auth.HistoryOtpError)
    assert issubclass(commerce_history_auth.HistoryOtpDeliveryError, commerce_history_auth.HistoryOtpError)
    assert commerce_history_auth.HistoryOtpThrottled().wait_seconds == 0
    assert commerce_history_auth.HistoryOtpInvalid().remaining_attempts == 0
