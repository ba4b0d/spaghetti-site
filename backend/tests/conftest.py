"""
Shared pytest fixtures for the 3DJAT backend test suite.

Uses a separate SQLite test database to avoid polluting production data.
"""
import os
import sys
import time

# ── Set JWT_SECRET before any app imports (auth.py checks at import time)
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-2024")

# ── Ensure the backend package is importable
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Now safe to import app modules (JWT_SECRET is set)
from app.database import Base, get_db
from app.models import Settings, Machine, Material, Product, User, Category
from app.seed import seed_all

from fastapi.testclient import TestClient

# ── Test database setup ──────────────────────────────────────────────
TEST_DB_DIR = os.path.join(backend_dir, "tests")
os.makedirs(TEST_DB_DIR, exist_ok=True)
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test.db")

# Remove any old test database
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

TEST_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _create_admin_user(db):
    """Ensure an admin user exists for auth tests."""
    from app.routers.auth import _hash
    existing = db.query(User).filter(User.username == "admin").first()
    if not existing:
        admin = User(
            username="admin",
            password_hash=_hash("3djat2024"),
            display_name="Test Admin",
            role="admin",
        )
        db.add(admin)
        db.commit()


def _create_employee_user(db):
    """Ensure an employee user exists for auth tests."""
    from app.routers.auth import _hash
    existing = db.query(User).filter(User.username == "employee").first()
    if not existing:
        emp = User(
            username="employee",
            password_hash=_hash("emp12345"),
            display_name="Test Employee",
            role="employee",
        )
        db.add(emp)
        db.commit()


@pytest.fixture(scope="function", autouse=True)
def setup_test_db():
    """Create fresh tables before each test, seed, and clean up after."""
    # Create all tables
    Base.metadata.create_all(bind=test_engine)

    db = TestSessionLocal()
    try:
        # Seed settings, machines, materials, products
        if db.query(Settings).count() == 0:
            seed_all(db)
        _create_admin_user(db)
        _create_employee_user(db)
    finally:
        db.close()

    yield

    # Teardown: drop all tables for a clean slate next test
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client(monkeypatch):
    """FastAPI TestClient with test DB dependency override."""
    import app.main as app_main
    from app.main import app

    # Entering TestClient runs the app lifespan, whose final step starts a
    # Telegram *receive-poll* daemon thread. That thread issues live
    # ``getUpdates`` calls as soon as a bot token is configured — and this
    # project's Settings table already carries a real token — so without this
    # guard the whole suite makes outbound Telegram requests. Replace the
    # thread starter with a no-op so no test can open that socket, whatever the
    # developer's environment or database holds.
    monkeypatch.setattr(app_main, "start_telegram_bot_thread", lambda: None)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Reset slowapi rate limiter state so tests don't trip over each other
    from limits.storage import MemoryStorage
    app.state.limiter._storage = MemoryStorage()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(scope="function", autouse=True)
def _block_outbound_notification_transports(monkeypatch):
    """Neutralise every live notification transport for every test.

    A developer ``backend/.env`` may enable real Telegram/SMS/SMTP credentials,
    and any test that posts a commerce request or approves an invoice would then
    page the owner's phone and inbox on every run. The ``client`` fixture above
    already blocks the inbound Telegram *poll* thread; this closes the outbound
    half of the same hole.

    ``app.main`` and ``app.routers.orders`` each import the Telegram sender
    directly, so patching only ``commerce_notifications`` would leave a live path
    open — every direct binding is patched too.

    Only the *leaf* senders are stubbed (never ``commerce_notifications.
    send_telegram_message``) so the per-channel config gate still runs and the
    dedicated notification tests — which monkeypatch these very attributes
    themselves, after this autouse fixture — keep asserting real behaviour.
    """
    import importlib

    from app.services import commerce_notifications as cn

    class _BlockedTransport:
        """Fails loudly instead of reaching a real provider."""

        def _blocked(self, *_args, **_kwargs):
            raise AssertionError(
                "outbound notification transport reached during a test — "
                "inject a fake session/smtp_factory or monkeypatch the sender"
            )

        post = _blocked
        SMTP = _blocked
        SMTP_SSL = _blocked

    blocked = _BlockedTransport()

    # SMS.ir — ``post_sms_ir_verify`` replaces ``client`` with this module-level
    # ``requests`` ONLY when the caller injects no ``session=``. The dedicated
    # tests always inject one, so they keep exercising the real code path.
    monkeypatch.setattr(cn, "requests", blocked)

    # Email — ``send_smtp_mail`` falls back to ``smtplib`` ONLY when the caller
    # injects no ``smtp_factory=``; the dedicated tests always inject one.
    monkeypatch.setattr(cn, "smtplib", blocked)

    # Telegram — ``send_telegram_notification`` has no injection seam (a raw
    # ``requests.post`` to api.telegram.org) and is bound separately in three
    # modules, so patch every binding; the channel wrapper treats False as a
    # failed send, which is the honest result.
    def _telegram_stub(*_args, **_kwargs):
        return False

    monkeypatch.setattr(cn, "send_telegram_notification", _telegram_stub)
    for module_path in ("app.routers.orders", "app.main"):
        try:
            imported = importlib.import_module(module_path)
        except Exception:  # pragma: no cover — module optional on some branches
            continue
        if hasattr(imported, "send_telegram_notification"):
            monkeypatch.setattr(imported, "send_telegram_notification", _telegram_stub)


def _get_token(client, username, password):
    """Login and return token string from HTTP cookie or JSON response."""
    resp = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed for {username}: {resp.json()}"
    token = resp.cookies.get("access_token")
    if not token and "token" in resp.json():
        token = resp.json()["token"]
    assert token, f"No access token returned for {username}"
    return token


def _make_token(username, password):
    """Create a token directly (bypasses rate limiter for tests)."""
    from app.routers.auth import create_token, _verify
    from app.models import User
    db = TestSessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        assert user, f"User {username} not found"
        return create_token(user.id, user.username, user.role)
    finally:
        db.close()


@pytest.fixture()
def auth_headers(client):
    """Return Authorization headers for the admin user."""
    token = _make_token("admin", "3djat2024")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def employee_headers(client):
    """Return Authorization headers for the employee user."""
    token = _make_token("employee", "emp12345")
    return {"Authorization": f"Bearer {token}"}
