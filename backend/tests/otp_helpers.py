"""Test-only helper: mint a live cart-OTP challenge without touching SMS.

The public ``POST /api/v1/commerce/requests`` gate now requires a real, verified
OTP challenge (see ``app.services.commerce_otp``). Tests that are *not* about the
OTP itself (intake validation, staff listing, notifications, invoices, the e2e
smoke path) still have to pass that gate, so they mint a challenge directly into
the shared test database with a known code.

Nothing here ever calls the SMS transport: the real issuance path
(``commerce_otp.issue_challenge``) is the only thing that sends an SMS, and we
deliberately bypass it — the test process must never reach SMS.ir.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# The same file ``conftest.py`` hands to the app under test.
_TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.db")
_engine = create_engine(
    f"sqlite:///{_TEST_DB}", connect_args={"check_same_thread": False}
)
_Session = sessionmaker(bind=_engine)

DEFAULT_TEST_MOBILE = "09123456789"
DEFAULT_TEST_CODE = "12345"


def issue_test_otp(
    mobile: str = DEFAULT_TEST_MOBILE, code: str = DEFAULT_TEST_CODE
) -> dict:
    """Insert a fresh, live challenge and return ``{otp_challenge_id, otp_code}``.

    A new challenge is minted on every call so a multi-POST test never reuses a
    single-use challenge.
    """
    from app.models import CommerceOtpChallenge
    from app.services.commerce_otp import OTP_TTL_SECONDS, _hash_code

    now = datetime.now(timezone.utc)
    salt = secrets.token_hex(16)
    db = _Session()
    try:
        challenge = CommerceOtpChallenge(
            mobile=mobile,
            code_salt=salt,
            code_hash=_hash_code(salt, code),
            expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
            consumed_at=None,
            attempts=0,
            created_at=now,
            client_ip_hash=None,
        )
        db.add(challenge)
        db.commit()
        db.refresh(challenge)
        return {"otp_challenge_id": challenge.id, "otp_code": code}
    finally:
        db.close()
