"""Order-history auth — purpose-isolated SMS OTP + short-lived read sessions.

A customer who wants «سفارش‌های من» proves ownership of a mobile number exactly
once, with an SMS one-time code, and receives a short, revocable, server-side
session. There is no account, password or remembered device.

**Purpose isolation.** The checkout flow (``app.services.commerce_otp``) proves
the same kind of ownership for a different purpose, so the two flows never share
challenge state: a checkout challenge can neither verify nor be consumed here,
and a history challenge cannot authorize ``POST /commerce/requests`` (the
cart gate imports only ``commerce_otp.verify_challenge``). This module
deliberately does **not** import or delegate to that verifier.

**Shared SMS budget.** What *is* shared is the SMS allowance, because both flows
spend real money on the same transport
(``commerce_notifications.send_customer_otp``). Both issue paths count and
cooldown against the same cross-purpose counters
(``commerce_otp.count_recent_sends`` / ``latest_send_at``), and the budget
constants are read from ``commerce_otp`` at call time — one definition, one
budget, so alternating flows cannot multiply a number's or an IP's allowance.

Design rules:

* only a *salted* SHA-256 hash of the code is stored — never the code;
* the session bearer is 32 random bytes (``secrets.token_urlsafe(32)``) and only
  its SHA-256 hash is persisted; the raw bearer is returned exactly once;
* verifying consumes the challenge with an atomic conditional ``UPDATE`` and
  inserts the session in the **same** transaction, so a code cannot be replayed
  and a session can never exist without its consumed challenge;
* wrong attempts are committed immediately, so a caller's rollback can never
  reset the attempt budget;
* a failed SMS send deletes the challenge — no unverifiable challenge survives;
* nothing here logs a code, a bearer or a mobile number.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CommerceHistoryOtpChallenge, CommerceHistorySession
from app.services import commerce_notifications, commerce_otp

# ── Tunables ─────────────────────────────────────────────────────────
HISTORY_OTP_LENGTH = 5
HISTORY_OTP_TTL_SECONDS = 300
HISTORY_OTP_MAX_ATTEMPTS = 5
# Absolute session lifetime: at most 30 minutes (design: "valid for at most
# 30 minutes"), regardless of activity.
HISTORY_SESSION_TTL_SECONDS = 30 * 60

# Generic, non-disclosing Persian rejections. Nothing here says whether the
# number has any orders.
_MSG_INVALID = "کد تأیید نامعتبر است"
_MSG_EXPIRED = "کد تأیید منقضی شده است؛ لطفاً کد جدید دریافت کنید"
_MSG_THROTTLED = "درخواست کد تأیید بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید"
_MSG_DELIVERY = "ارسال کد تأیید ناموفق بود؛ لطفاً دوباره تلاش کنید"
_MSG_MOBILE = "شماره موبایل نامعتبر است"


class HistoryOtpError(Exception):
    """Base class for order-history authentication failures."""


class HistoryOtpInvalid(HistoryOtpError):
    """The submitted mobile/code/challenge did not match a usable challenge."""

    def __init__(self, message: str = _MSG_INVALID, *, remaining_attempts: int = 0):
        super().__init__(message)
        self.remaining_attempts = max(0, int(remaining_attempts))


class HistoryOtpThrottled(HistoryOtpError):
    """Issuing was rejected by the (shared) resend cooldown or an hourly cap."""

    def __init__(self, message: str = _MSG_THROTTLED, *, wait_seconds: int = 0):
        super().__init__(message)
        self.wait_seconds = max(0, int(wait_seconds))


class HistoryOtpDeliveryError(HistoryOtpError):
    """The SMS transport could not deliver the code (maps to HTTP 503)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_mobile(value: str | None) -> str:
    """Return the canonical Iranian mobile, or raise ``HistoryOtpInvalid``.

    Exactly 11 ASCII digits starting with ``09`` — the same canonical form the
    checkout flow stores, so history lookups match by exact equality and a
    Persian-digit, padded or over-long variant can never address another number.
    """
    mobile = (value or "").strip()
    if (
        len(mobile) != 11
        or not mobile.startswith("09")
        or not all("0" <= c <= "9" for c in mobile)
    ):
        raise HistoryOtpInvalid(_MSG_MOBILE)
    return mobile


def _hash_code(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}{code}".encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    """SHA-256 hex of a session bearer — the only form that is ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """A cryptographically-random, zero-padded ``HISTORY_OTP_LENGTH``-digit code."""
    return f"{secrets.randbelow(10 ** HISTORY_OTP_LENGTH):0{HISTORY_OTP_LENGTH}d}"


def _claim_success(db: Session, challenge: CommerceHistoryOtpChallenge, now: datetime) -> bool:
    """Atomically consume a live challenge; True only for the single winner.

    A read-then-write would let two concurrent verifies both pass. The claim is
    one conditional ``UPDATE`` guarded on ``consumed_at IS NULL`` and remaining
    attempts, so exactly one caller sees ``rowcount == 1``.
    """
    claimed = (
        db.query(CommerceHistoryOtpChallenge)
        .filter(
            CommerceHistoryOtpChallenge.id == challenge.id,
            CommerceHistoryOtpChallenge.consumed_at.is_(None),
            CommerceHistoryOtpChallenge.attempts < HISTORY_OTP_MAX_ATTEMPTS,
        )
        .update({CommerceHistoryOtpChallenge.consumed_at: now}, synchronize_session=False)
    )
    return claimed == 1


def _consume(db: Session, challenge: CommerceHistoryOtpChallenge, now: datetime) -> None:
    """Durably mark a challenge consumed (the exhausted branch)."""
    db.query(CommerceHistoryOtpChallenge).filter(
        CommerceHistoryOtpChallenge.id == challenge.id,
        CommerceHistoryOtpChallenge.consumed_at.is_(None),
    ).update({CommerceHistoryOtpChallenge.consumed_at: now}, synchronize_session=False)
    db.commit()


def _register_failed_attempt(
    db: Session, challenge: CommerceHistoryOtpChallenge, now: datetime
) -> int:
    """Atomically bump the attempt counter; returns attempts remaining.

    Committed immediately, so a wrong guess is always counted and a caller that
    rolls back its request can never reset the attempt budget.
    """
    new_attempts = challenge.attempts + 1
    values = {CommerceHistoryOtpChallenge.attempts: new_attempts}
    if new_attempts >= HISTORY_OTP_MAX_ATTEMPTS:
        values[CommerceHistoryOtpChallenge.consumed_at] = now
    changed = (
        db.query(CommerceHistoryOtpChallenge)
        .filter(
            CommerceHistoryOtpChallenge.id == challenge.id,
            CommerceHistoryOtpChallenge.consumed_at.is_(None),
            CommerceHistoryOtpChallenge.attempts == challenge.attempts,
        )
        .update(values, synchronize_session=False)
    )
    db.commit()
    if changed == 0:
        return 0
    return max(0, HISTORY_OTP_MAX_ATTEMPTS - new_attempts)


def issue_history_challenge(
    db: Session, mobile: str, *, client_ip: str | None = None
) -> CommerceHistoryOtpChallenge:
    """Create, persist and SMS-deliver a fresh history one-time code.

    Enforces the SMS budget that is **shared with checkout**: the resend
    cooldown, the per-mobile hourly cap and the per-IP hourly cap all count
    challenges in both tables. The check-then-insert runs inside a serialized
    SQLite write transaction (``BEGIN IMMEDIATE``) so concurrent issuers cannot
    both clear the throttle and each send a real SMS.

    A failed SMS send deletes the challenge and raises ``HistoryOtpDeliveryError``
    — fail closed: no session can ever be issued from an undelivered code.
    """
    mobile = canonical_mobile(mobile)
    now = _now()

    commerce_otp._begin_immediate(db)
    try:
        latest_at = commerce_otp.latest_send_at(db, mobile)
        cooldown = commerce_otp.OTP_RESEND_COOLDOWN_SECONDS
        if latest_at is not None:
            elapsed = (now - latest_at).total_seconds()
            if elapsed < cooldown:
                wait = int(cooldown - elapsed)
                raise HistoryOtpThrottled(wait_seconds=wait or 1)

        hour_ago = now - timedelta(hours=1)
        if commerce_otp.count_recent_sends(db, mobile, since=hour_ago) >= commerce_otp.OTP_MAX_SENDS_PER_HOUR:
            raise HistoryOtpThrottled(wait_seconds=cooldown)

        ip_hash = commerce_otp.hash_client_ip(client_ip)
        if ip_hash is not None:
            ip_sends = commerce_otp.count_recent_sends_for_ip(db, ip_hash, since=hour_ago)
            if ip_sends >= commerce_otp.OTP_MAX_SENDS_PER_HOUR_IP:
                raise HistoryOtpThrottled(wait_seconds=cooldown)

        # Supersede any prior unconsumed history challenge for this mobile: only
        # the newest code may ever be verified.
        db.query(CommerceHistoryOtpChallenge).filter(
            CommerceHistoryOtpChallenge.mobile == mobile,
            CommerceHistoryOtpChallenge.consumed_at.is_(None),
        ).update(
            {CommerceHistoryOtpChallenge.consumed_at: now}, synchronize_session=False
        )

        salt = secrets.token_hex(16)  # 32 hex chars
        code = _generate_code()
        challenge = CommerceHistoryOtpChallenge(
            mobile=mobile,
            code_salt=salt,
            code_hash=_hash_code(salt, code),
            expires_at=now + timedelta(seconds=HISTORY_OTP_TTL_SECONDS),
            consumed_at=None,
            attempts=0,
            created_at=now,
            client_ip_hash=ip_hash,
        )
        db.add(challenge)
        db.commit()
        db.refresh(challenge)
    except HistoryOtpThrottled:
        # Release the write lock promptly; the row was never written.
        db.rollback()
        raise

    try:
        sent = commerce_notifications.send_customer_otp(mobile, code)
    except Exception:  # noqa: BLE001 - a transport error is a failed send
        sent = False
    if not sent:
        db.delete(challenge)
        db.commit()
        raise HistoryOtpDeliveryError(_MSG_DELIVERY)
    return challenge


def verify_history_challenge(
    db: Session, challenge_id: int, code: str, mobile: str
) -> tuple[str, datetime]:
    """Verify a history code; returns ``(raw_bearer, expires_at)``.

    Consumes the challenge and stores the session's token hash **atomically**
    (one transaction), so a code is single-use even under concurrent submits and
    a session can never outlive its unconsumed challenge. A wrong code bumps the
    attempt counter (committed immediately, so a caller's rollback cannot reset
    it) and kills the challenge once attempts are exhausted. Every rejection is
    a generic Persian message; none discloses whether the number has orders.

    A rejection releases the write lock taken for the check rather than leaving
    it for the caller: the attempt bookkeeping is already committed, so nothing
    of value is rolled back.
    """
    mobile = canonical_mobile(mobile)
    now = _now()

    # Serialize check + claim + session insert; BEGIN IMMEDIATE is a no-op when
    # the caller already opened a transaction.
    commerce_otp._begin_immediate(db)

    challenge = (
        db.query(CommerceHistoryOtpChallenge)
        .filter(CommerceHistoryOtpChallenge.id == challenge_id)
        .first()
    )
    # Unknown id, wrong mobile and already-consumed are indistinguishable to the
    # caller — never disclose which one it was.
    if challenge is None or challenge.mobile != mobile or challenge.consumed_at is not None:
        db.rollback()
        raise HistoryOtpInvalid()

    if commerce_otp._as_utc(challenge.expires_at) <= now:
        db.rollback()
        raise HistoryOtpInvalid(_MSG_EXPIRED)

    if challenge.attempts >= HISTORY_OTP_MAX_ATTEMPTS:
        _consume(db, challenge, now)  # make sure it is dead, durably
        raise HistoryOtpInvalid(remaining_attempts=0)

    expected = _hash_code(challenge.code_salt, code or "")
    if not hmac.compare_digest(expected, challenge.code_hash):
        remaining = _register_failed_attempt(db, challenge, now)
        message = (
            f"کد تأیید اشتباه است؛ {remaining} تلاش دیگر باقی مانده"
            if remaining > 0
            else _MSG_INVALID
        )
        raise HistoryOtpInvalid(message, remaining_attempts=remaining)

    if not _claim_success(db, challenge, now):
        # Lost the race — another verifier already consumed this challenge.
        db.rollback()
        raise HistoryOtpInvalid()

    bearer = secrets.token_urlsafe(32)  # 32 random bytes → 43 chars
    expires_at = now + timedelta(seconds=HISTORY_SESSION_TTL_SECONDS)
    db.add(
        CommerceHistorySession(
            token_hash=_hash_token(bearer),
            mobile=mobile,
            expires_at=expires_at,
            revoked_at=None,
            created_at=now,
        )
    )
    # The OTP claim and the session land together, or neither does.
    db.commit()
    return bearer, expires_at


def resolve_history_session(db: Session, bearer: str | None) -> str | None:
    """Return the canonical mobile a live bearer belongs to, else ``None``.

    Only the hash of the bearer is compared (it is the lookup key), and a
    session that is missing, revoked or past its TTL resolves to nothing. The
    caller must treat ``None`` as unauthenticated.
    """
    if not bearer:
        return None
    session = (
        db.query(CommerceHistorySession)
        .filter(CommerceHistorySession.token_hash == _hash_token(bearer))
        .first()
    )
    if session is None or session.revoked_at is not None:
        return None
    if commerce_otp._as_utc(session.expires_at) <= _now():
        return None
    return session.mobile


def revoke_history_session(db: Session, bearer: str | None) -> None:
    """Revoke the session for ``bearer``; idempotent and silent when unknown."""
    if not bearer:
        return
    db.query(CommerceHistorySession).filter(
        CommerceHistorySession.token_hash == _hash_token(bearer),
        CommerceHistorySession.revoked_at.is_(None),
    ).update(
        {CommerceHistorySession.revoked_at: _now()}, synchronize_session=False
    )
    db.commit()
