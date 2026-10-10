"""Storefront cart OTP — issue and verify SMS one-time codes.

Guests must prove ownership of the mobile they enter at checkout before their
order request is accepted. Only a *salted* SHA-256 hash of the code is stored;
the plaintext code exists only long enough to be handed to the SMS transport
and is never persisted, returned or logged.

Design rules (cart-OTP brief):

* Codes come from ``secrets`` (never ``random``) — a guessable code is no proof
  of ownership.
* A challenge is short-lived (``OTP_TTL_SECONDS``), single-use, and dies once
  it is consumed, superseded, or exhausted by wrong attempts.
* Issuing is rate-limited: a per-mobile resend cooldown plus hourly per-mobile
  and per-client-IP caps, so the endpoint cannot be used as an SMS pump. The
  check + insert is serialized (SQLite ``BEGIN IMMEDIATE``) so two concurrent
  issues cannot both clear the throttle and send two costly SMS.
* Consuming a challenge is an atomic conditional UPDATE, so two concurrent
  verifies of the same code cannot both succeed — exactly one wins.
* A failed SMS send deletes the challenge — an unverifiable challenge must
  never be left behind (it would let a customer believe a code was sent).
* Code comparison is constant-time (``hmac.compare_digest``).
* Every rejection is a generic Persian message that never discloses whether a
  mobile is already in use.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import CommerceOtpChallenge
from app.services import commerce_notifications

# ── Tunables ─────────────────────────────────────────────────────────
OTP_LENGTH = 5
OTP_TTL_SECONDS = 300
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
OTP_MAX_SENDS_PER_HOUR = 5      # per mobile
OTP_MAX_SENDS_PER_HOUR_IP = 20  # per client IP

# Generic, non-disclosing Persian rejections.
_MSG_INVALID = "کد تأیید نامعتبر است"
_MSG_EXPIRED = "کد تأیید منقضی شده است؛ لطفاً کد جدید دریافت کنید"
_MSG_THROTTLED = "درخواست کد تأیید بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید"
_MSG_DELIVERY = "ارسال کد تأیید ناموفق بود؛ لطفاً دوباره تلاش کنید"


class OtpError(Exception):
    """Base class for storefront OTP failures."""


class OtpInvalid(OtpError):
    """The submitted code/id/mobile did not match a usable challenge."""

    def __init__(self, message: str = _MSG_INVALID, *, remaining_attempts: int = 0):
        super().__init__(message)
        self.remaining_attempts = max(0, int(remaining_attempts))


class OtpExpired(OtpError):
    """The challenge is past its TTL."""


class OtpThrottled(OtpError):
    """Issuing was rejected by the resend cooldown or an hourly cap."""

    def __init__(self, message: str = _MSG_THROTTLED, *, wait_seconds: int = 0):
        super().__init__(message)
        self.wait_seconds = max(0, int(wait_seconds))


class OtpDeliveryError(OtpError):
    """The SMS transport could not deliver the code (maps to HTTP 503)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes read back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _begin_immediate(db: Session) -> None:
    """Acquire SQLite's write lock up front, serializing a critical section.

    A deferred transaction only takes the write lock at the first *write*, i.e.
    after our throttle SELECTs — so two issuers could both read "under the cap"
    and each insert + send. ``BEGIN IMMEDIATE`` takes the write lock before the
    reads, making the check and the insert one serialized unit: the second
    issuer blocks until the first commits, then its own checks see the new row.

    No-op off SQLite, or when a transaction is already open (nothing to
    serialize against, and a nested BEGIN would fail).
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))


def hash_client_ip(client_ip: str | None) -> str | None:
    """SHA-256 hex of a client IP; None when unknown. Never store the raw IP."""
    if not client_ip:
        return None
    return hashlib.sha256(client_ip.strip().encode("utf-8")).hexdigest()


def _hash_code(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}{code}".encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """A cryptographically-random, zero-padded ``OTP_LENGTH``-digit code."""
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def _latest_for_mobile(db: Session, mobile: str) -> CommerceOtpChallenge | None:
    return (
        db.query(CommerceOtpChallenge)
        .filter(CommerceOtpChallenge.mobile == mobile)
        .order_by(CommerceOtpChallenge.id.desc())
        .first()
    )


def issue_challenge(
    db: Session, mobile: str, *, client_ip: str | None = None
) -> CommerceOtpChallenge:
    """Create, persist and SMS-deliver a fresh one-time code for ``mobile``.

    Invalidates any prior unconsumed challenge for the mobile, enforces the
    resend cooldown and hourly caps, and — crucially — deletes the challenge
    and raises ``OtpDeliveryError`` if the SMS transport does not acknowledge,
    so no unverifiable challenge survives.

    The whole check-then-insert runs inside a serialized SQLite write
    transaction (``BEGIN IMMEDIATE``) so concurrent issues for one mobile
    cannot both pass the throttle and each send a real SMS.
    """
    now = _now()

    # Serialize the throttle check + insert against concurrent issuers.
    _begin_immediate(db)
    try:
        # Resend cooldown, measured from the most recent challenge for this
        # mobile (consumed or not), so a customer cannot spam a number.
        latest = _latest_for_mobile(db, mobile)
        latest_at = _as_utc(latest.created_at) if latest is not None else None
        if latest_at is not None:
            elapsed = (now - latest_at).total_seconds()
            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                wait = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed)
                raise OtpThrottled(wait_seconds=wait or 1)

        hour_ago = now - timedelta(hours=1)
        mobile_sends = (
            db.query(CommerceOtpChallenge)
            .filter(
                CommerceOtpChallenge.mobile == mobile,
                CommerceOtpChallenge.created_at >= hour_ago,
            )
            .count()
        )
        if mobile_sends >= OTP_MAX_SENDS_PER_HOUR:
            raise OtpThrottled(wait_seconds=OTP_RESEND_COOLDOWN_SECONDS)

        ip_hash = hash_client_ip(client_ip)
        if ip_hash is not None:
            ip_sends = (
                db.query(CommerceOtpChallenge)
                .filter(
                    CommerceOtpChallenge.client_ip_hash == ip_hash,
                    CommerceOtpChallenge.created_at >= hour_ago,
                )
                .count()
            )
            if ip_sends >= OTP_MAX_SENDS_PER_HOUR_IP:
                raise OtpThrottled(wait_seconds=OTP_RESEND_COOLDOWN_SECONDS)

        # Supersede any prior unconsumed challenge for this mobile: only the
        # newest code may ever be verified.
        db.query(CommerceOtpChallenge).filter(
            CommerceOtpChallenge.mobile == mobile,
            CommerceOtpChallenge.consumed_at.is_(None),
        ).update({CommerceOtpChallenge.consumed_at: now}, synchronize_session=False)

        salt = secrets.token_hex(16)  # 32 hex chars
        code = _generate_code()
        challenge = CommerceOtpChallenge(
            mobile=mobile,
            code_salt=salt,
            code_hash=_hash_code(salt, code),
            expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
            consumed_at=None,
            attempts=0,
            created_at=now,
            client_ip_hash=ip_hash,
        )
        db.add(challenge)
        db.commit()
        db.refresh(challenge)
    except OtpThrottled:
        # Release the write lock promptly; the row was never written.
        db.rollback()
        raise

    # Deliver the code. A failed send would leave an unverifiable challenge
    # behind, so delete it and surface a delivery error instead.
    try:
        sent = commerce_notifications.send_customer_otp(mobile, code)
    except Exception:  # noqa: BLE001 - a transport error is a failed send
        sent = False
    if not sent:
        db.delete(challenge)
        db.commit()
        raise OtpDeliveryError(_MSG_DELIVERY)
    return challenge


def _claim_success(db: Session, challenge: CommerceOtpChallenge, now: datetime) -> bool:
    """Atomically consume a live challenge; True only for the single winner.

    A read-then-write (check ``consumed_at`` then set it) lets two concurrent
    verifies of the same code both see it unconsumed and both pass. The claim
    is instead a single conditional ``UPDATE`` guarded on ``consumed_at IS
    NULL`` and remaining attempts; SQLite serializes the writes, so exactly one
    caller gets ``rowcount == 1`` and every loser gets ``0``.
    """
    claimed = (
        db.query(CommerceOtpChallenge)
        .filter(
            CommerceOtpChallenge.id == challenge.id,
            CommerceOtpChallenge.consumed_at.is_(None),
            CommerceOtpChallenge.attempts < OTP_MAX_ATTEMPTS,
        )
        .update({CommerceOtpChallenge.consumed_at: now}, synchronize_session=False)
    )
    return claimed == 1


def _consume(db: Session, challenge: CommerceOtpChallenge, now: datetime) -> None:
    """Durably mark a challenge consumed (used for the exhausted branch)."""
    db.query(CommerceOtpChallenge).filter(
        CommerceOtpChallenge.id == challenge.id,
        CommerceOtpChallenge.consumed_at.is_(None),
    ).update({CommerceOtpChallenge.consumed_at: now}, synchronize_session=False)
    db.commit()


def _register_failed_attempt(
    db: Session, challenge: CommerceOtpChallenge, now: datetime
) -> int:
    """Atomically bump the attempt counter; returns how many attempts remain.

    Committed immediately — never left for a caller's transaction — so a wrong
    guess is always counted and a caller that rolls back its request (see
    ``commit=False``) can never reset the attempt budget. The increment is
    guarded on the observed ``attempts`` value so two concurrent wrong guesses
    cannot both count as one; the loser reports 0 remaining (a generic
    rejection rather than a stale count).
    """
    new_attempts = challenge.attempts + 1
    values = {CommerceOtpChallenge.attempts: new_attempts}
    if new_attempts >= OTP_MAX_ATTEMPTS:
        values[CommerceOtpChallenge.consumed_at] = now
    changed = (
        db.query(CommerceOtpChallenge)
        .filter(
            CommerceOtpChallenge.id == challenge.id,
            CommerceOtpChallenge.consumed_at.is_(None),
            CommerceOtpChallenge.attempts == challenge.attempts,
        )
        .update(values, synchronize_session=False)
    )
    db.commit()
    if changed == 0:
        return 0
    return max(0, OTP_MAX_ATTEMPTS - new_attempts)


def verify_challenge(
    db: Session,
    challenge_id: int,
    code: str,
    mobile: str,
    *,
    commit: bool = True,
) -> CommerceOtpChallenge:
    """Validate ``code`` against challenge ``challenge_id`` for ``mobile``.

    On success the challenge is consumed (single-use), via an atomic
    conditional claim so only one concurrent verifier can win. A wrong code
    bumps the attempt counter — killing the challenge once attempts are
    exhausted — and the raised ``OtpInvalid`` reports how many attempts remain.
    Expiry raises ``OtpExpired``. All rejections are generic Persian messages.

    ``commit=False`` leaves a *successful* claim uncommitted so the caller can
    commit it atomically alongside the work it authorizes (or roll it back on a
    failed creation, leaving the proof usable). Failure bookkeeping (wrong
    attempts, exhaustion) is always committed immediately, so it can never be
    rolled back and reset.
    """
    now = _now()
    challenge = (
        db.query(CommerceOtpChallenge)
        .filter(CommerceOtpChallenge.id == challenge_id)
        .first()
    )
    # Unknown id, wrong mobile and already-consumed are indistinguishable to the
    # caller — never disclose which one it was.
    if challenge is None or challenge.mobile != mobile or challenge.consumed_at is not None:
        raise OtpInvalid()

    if _as_utc(challenge.expires_at) <= now:
        raise OtpExpired(_MSG_EXPIRED)

    if challenge.attempts >= OTP_MAX_ATTEMPTS:
        # Already exhausted: make sure it is dead, then reject.
        _consume(db, challenge, now)
        raise OtpInvalid(remaining_attempts=0)

    expected = _hash_code(challenge.code_salt, code or "")
    if not hmac.compare_digest(expected, challenge.code_hash):
        remaining = _register_failed_attempt(db, challenge, now)
        message = (
            f"کد تأیید اشتباه است؛ {remaining} تلاش دیگر باقی مانده"
            if remaining > 0
            else _MSG_INVALID
        )
        raise OtpInvalid(message, remaining_attempts=remaining)

    # Success: claim the challenge atomically (single-use under concurrency).
    if not _claim_success(db, challenge, now):
        # Lost the race — another request already consumed this challenge.
        db.rollback()
        raise OtpInvalid()

    if commit:
        db.commit()
    # Re-read so the returned object reflects the claim (uncommitted for
    # ``commit=False``, where it rides the caller's transaction).
    db.refresh(challenge)
    return challenge
