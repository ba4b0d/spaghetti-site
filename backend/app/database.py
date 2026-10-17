import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Database path: app/data/ inside container
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, '3djat.db')
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

import logging
from sqlalchemy import event

logger = logging.getLogger(__name__)


# SQLite pragmas are PER-CONNECTION. Previously they were set on one ad-hoc
# connection (below) and pooled request sessions never enforced foreign_keys —
# a permanent delete of a referenced material/machine silently succeeded and
# SQLAlchemy nulled the FK on loaded children (all products lost material_id).
# Listen on every new pooled connection so FKs are always enforced.
def _on_connect(dbapi_conn, connection_record):  # noqa: ARG001
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    except Exception:
        pass


event.listen(engine, "connect", _on_connect)


# Enable WAL mode for better concurrent reads + writes.
# Tolerate permission errors (e.g. mounted volume owned by a different
# user) so the app still boots — WAL is an optimization, not a hard
# requirement. journal_mode persists in the DB file; pragmas that must be
# per-connection live in _on_connect above.
def _enable_wal():
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
    except Exception as exc:
        logger.warning("Could not enable SQLite WAL mode: %s", exc)

_enable_wal()


def _migrate_orders():
    """Add new columns to orders table if they don't exist (SQLite-safe)."""
    try:
        with engine.connect() as conn:
            # Check existing columns
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(orders)"))}
            if "qty" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN qty INTEGER NOT NULL DEFAULT 1"))
                logger.info("Added orders.qty column")
            if "unit_cost" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN unit_cost FLOAT"))
                logger.info("Added orders.unit_cost column")
            if "delivered_at" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivered_at DATETIME"))
                logger.info("Added orders.delivered_at column")
            # Add index on customer_name if missing
            indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(orders)"))}
            if "ix_orders_customer_name" not in indexes:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_customer_name ON orders (customer_name)"))
                logger.info("Added ix_orders_customer_name index")
    except Exception as exc:
        logger.warning("Order migration skipped: %s", exc)

_migrate_orders()


def _migrate_commerce_payment_attempts():
    """Add Task 2 columns to ``commerce_payment_attempts`` (SQLite-safe).

    ``create_all`` never alters an existing table, so a deployed database that
    already holds DigiPay attempts needs the new ``provider_trans_id`` column
    added in place. Guarded by a ``PRAGMA table_info`` check so it is a no-op on
    a fresh database (the model already defines the column there).
    """
    try:
        with engine.connect() as conn:
            cols = {
                row[1]
                for row in conn.execute(
                    text("PRAGMA table_info(commerce_payment_attempts)")
                )
            }
            if cols and "provider_trans_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE commerce_payment_attempts "
                        "ADD COLUMN provider_trans_id INTEGER"
                    )
                )
                logger.info("Added commerce_payment_attempts.provider_trans_id column")
    except Exception as exc:
        logger.warning("Payment-attempt migration skipped: %s", exc)


_migrate_commerce_payment_attempts()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
