"""
3DJAT 3D Printing Product Pricing API
FastAPI application with CORS, SQLite, and seed data.
"""
import os, logging, mimetypes
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Ensure proper MIME types for static uploads
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/jpeg", ".jpeg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("model/stl", ".stl")
mimetypes.add_type("model/3mf", ".3mf")

load_dotenv()  # Load .env file if present

# Configure logging framework
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
from fastapi import FastAPI, Depends, APIRouter, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import engine, SessionLocal, Base
from app.models import Settings, Machine, Material, Product, Category, ProductImage, Order, ProductCategory, BlogPost, SiteView
from app.seed import seed_all
from fastapi import HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.routers.auth import require_staff_role, limiter, _ensure_default_admin

from app.routers.settings import router as settings_router, get_public_settings, get_contact_info
from app.routers.materials import router as materials_router
from app.routers.machines import router as machines_router
from app.routers.products import router as products_router
from app.routers.stats import router as stats_router
from app.routers.auth import router as auth_router
from app.routers.categories import router as categories_router
from app.routers.collections import router as collections_router
from app.routers.catalog import router as catalog_router
from app.routers.orders import router as orders_router
from app.routers.blog import router as blog_router
from app.routers.backup import router as backup_router
from app.routers.custom_orders import router as custom_orders_router
from app.routers.customers import router as customers_router
from app.routers.audit_logs import router as audit_router
from app.routers.commerce import router as commerce_router
from app.telegram_bot import start_telegram_bot_thread, send_telegram_notification

from sqlalchemy import inspect, text

# ── Uploads directory ────────────────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and seed data on first run."""
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Seed if settings table is empty or missing enable_blog
        if db.query(Settings).count() == 0:
            seed_all(db)
            logger.info("Database seeded with initial data.")
        else:
            enable_blog_setting = db.query(Settings).filter(Settings.key == "enable_blog").first()
            if not enable_blog_setting:
                db.add(Settings(key="enable_blog", value=0.0, string_value="", description="Enable public blog feature (1.0 = enabled, 0.0 = disabled)"))
                db.commit()
                logger.info("Seeded default enable_blog setting.")
            logger.info("Database already contains data, skipping full seed.")

        # Ensure default admin exists (one-time, at startup)
        _ensure_default_admin(db)

        inspector = inspect(engine)
        product_cols = {c["name"] for c in inspector.get_columns("products")} if "products" in inspector.get_table_names() else set()
        if "products" in inspector.get_table_names() and "package_info" not in product_cols:
            print("Adding products.package_info column...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN package_info VARCHAR DEFAULT ''"))
            print("Added products.package_info column.")

        # Migration: create product_images table if not exists
        inspector = inspect(engine)
        if "product_images" not in inspector.get_table_names():
            print("Creating product_images table...")
            ProductImage.__table__.create(bind=engine)
            # Migrate existing image_url data
            products_with_images = db.query(Product).filter(Product.image_url != None, Product.image_url != "").all()
            migrated = 0
            for p in products_with_images:
                img = ProductImage(
                    product_id=p.id,
                    image_url=p.image_url,
                    sort_order=0,
                    is_primary=True,
                )
                db.add(img)
                migrated += 1
            if migrated:
                db.commit()
                print(f"Migrated {migrated} existing product images to product_images table.")

        # Migration: add dimension columns if not exists
        product_cols = {c["name"] for c in inspector.get_columns("products")}
        if "dimension_x" not in product_cols:
            print("Adding dimension columns to products table...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN dimension_x FLOAT"))
                conn.execute(text("ALTER TABLE products ADD COLUMN dimension_y FLOAT"))
                conn.execute(text("ALTER TABLE products ADD COLUMN dimension_z FLOAT"))

        # Migration: add is_default column to machines and materials tables
        machine_cols = {c["name"] for c in inspector.get_columns("machines")}
        if "is_default" not in machine_cols:
            print("Adding is_default column to machines table...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE machines ADD COLUMN is_default BOOLEAN DEFAULT 0"))

        material_cols = {c["name"] for c in inspector.get_columns("materials")}
        if "is_default" not in material_cols:
            print("Adding is_default column to materials table...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE materials ADD COLUMN is_default BOOLEAN DEFAULT 0"))

        # Migration: add parent_id to categories table
        cat_cols = {c["name"] for c in inspector.get_columns("categories")}
        if "parent_id" not in cat_cols:
            print("Adding parent_id column to categories table...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE categories ADD COLUMN parent_id INTEGER REFERENCES categories(id)"))

        # Sync: import existing product category strings into categories table
        existing_cat_names = {c.name for c in db.query(Category.name).all()}
        product_cats = (
            db.query(Product.category)
            .filter(Product.category != None, Product.category != "")
            .distinct()
            .all()
        )
        imported = 0
        for (cat_name,) in product_cats:
            if cat_name not in existing_cat_names:
                db.add(Category(name=cat_name))
                existing_cat_names.add(cat_name)
                imported += 1
        if imported:
            db.commit()
            print(f"Imported {imported} product categories into categories table.")

        # Migration: create collections and product_collections tables if not exists
        if "collections" not in inspector.get_table_names():
            print("Creating collections table...")
            from app.models import Collection, ProductCollection
            Collection.__table__.create(bind=engine)
            ProductCollection.__table__.create(bind=engine)

        # Migration: create custom_order_requests, product_views, audit_logs tables
        if "custom_order_requests" not in inspector.get_table_names():
            print("Creating custom_order_requests table...")
            from app.models import CustomOrderRequest
            CustomOrderRequest.__table__.create(bind=engine)
        if "product_views" not in inspector.get_table_names():
            print("Creating product_views table...")
            from app.models import ProductView
            ProductView.__table__.create(bind=engine)
        if "audit_logs" not in inspector.get_table_names():
            print("Creating audit_logs table...")
            from app.models import AuditLog
            AuditLog.__table__.create(bind=engine)
        if "site_views" not in inspector.get_table_names():
            print("Creating site_views table...")
            from app.models import SiteView
            SiteView.__table__.create(bind=engine)

        # Always sync: move any products with old category string but no m2m association
        from app.models import ProductCategory
        products_needing_sync = (
            db.query(Product)
            .filter(Product.category != None, Product.category != "")
            .all()
        )
        migrated = 0
        for p in products_needing_sync:
            # Check if product already has m2m associations
            existing = db.query(ProductCategory).filter(ProductCategory.product_id == p.id).first()
            if not existing:
                cat = db.query(Category).filter(Category.name == p.category).first()
                if cat:
                    db.add(ProductCategory(product_id=p.id, category_id=cat.id))
                    migrated += 1
        if migrated:
            db.commit()
            print(f"Migrated {migrated} product-category associations to junction table.")

        # Migration: order schedule dates (start + ready-to-send)
        if "orders" in inspector.get_table_names():
            order_cols = {c["name"] for c in inspector.get_columns("orders")}
            if "started_at" not in order_cols:
                db.execute(text("ALTER TABLE orders ADD COLUMN started_at DATE"))
                print("Added orders.started_at column.")
            if "ready_by" not in order_cols:
                db.execute(text("ALTER TABLE orders ADD COLUMN ready_by DATE"))
                print("Added orders.ready_by column.")
            db.commit()

        # Migration: products.created_at
        product_cols = {c["name"] for c in inspector.get_columns("products")}
        if "created_at" not in product_cols:
            print("Adding products.created_at column...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN created_at DATETIME"))
            print("Added products.created_at column.")

        # Migration: products.slug + products.tags (SEO URLs / catalog tags)
        product_cols = {c["name"] for c in inspector.get_columns("products")}
        if "slug" not in product_cols:
            print("Adding products.slug column...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN slug VARCHAR"))
                # unique index — SQLite allows multiple NULLs
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug ON products (slug)"
                ))
            print("Added products.slug column.")
        if "tags" not in product_cols:
            print("Adding products.tags column...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN tags VARCHAR DEFAULT ''"))
            print("Added products.tags column.")

        # Backfill empty slugs from product names (Persian names → "product", "product-1", …)
        try:
            missing = (
                db.query(Product)
                .filter((Product.slug == None) | (Product.slug == ""))  # noqa: E711
                .all()
            )
            if missing:
                used = {
                    s for (s,) in db.query(Product.slug).filter(
                        Product.slug != None, Product.slug != ""  # noqa: E711
                    ).all()
                }
                filled = 0
                for p in missing:
                    base = Product.generate_slug(p.name) or "product"
                    candidate = base
                    n = 1
                    while candidate in used:
                        candidate = f"{base}-{n}"
                        n += 1
                    p.slug = candidate
                    used.add(candidate)
                    filled += 1
                db.commit()
                print(f"Backfilled slug for {filled} product(s).")

            # Migration: transfer simple quantity notes (e.g. "1 عدد", "6 عدد به همراه نگهدارنده") from notes to package_info
            products_with_notes = (
                db.query(Product)
                .filter(Product.notes != None, Product.notes != "")  # noqa: E711
                .all()
            )
            transferred = 0
            for p in products_with_notes:
                val = (p.notes or "").strip()
                if val and not (p.package_info or "").strip():
                    import re
                    if re.match(r"^\d+\s*عدد(\s*به\s*همراه\s*.+)?$", val, flags=re.IGNORECASE):
                        p.package_info = val
                        p.notes = ""
                        transferred += 1
            if transferred:
                db.commit()
                print(f"Transferred quantity notes to package_info for {transferred} product(s).")

            # Migration: populate SEO descriptions for products without notes
            from app.seo_descriptions import populate_seo_descriptions
            populate_seo_descriptions(db)
        except Exception as e:
            db.rollback()
            print(f"Migration / backfill skipped: {e}")

    finally:
        db.close()

    # Start Telegram Admin Bot background thread
    start_telegram_bot_thread()

    yield


app = FastAPI(
    title="Spaghetti Print API",
    description="3D printing product cost calculation and pricing",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (configurable via env) ────────────────────────────────────
# Only use explicitly configured origins in production; localhost:5173 is for dev.
allow_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
if not allow_origins:
    allow_origins = ['http://localhost:5173']

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Custom CMS Branding Headers (identifies platform as Spaghetti CMS) ──
@app.middleware("http")
async def add_cms_branding_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Powered-By"] = "Spaghetti CMS"
    response.headers["X-CMS"] = "Spaghetti-CMS/1.0"
    return response

# ── Include routers ──────────────────────────────────────────────────
app.include_router(settings_router, dependencies=[Depends(require_staff_role)])
# Public branding endpoint (favicon/logo) — no auth required, different path to avoid auth collision
public_settings_router = APIRouter(prefix="/api/v1", tags=["public-settings"])
public_settings_router.add_api_route("/brand", get_public_settings, methods=["GET"])
public_settings_router.add_api_route("/contact", get_contact_info, methods=["GET"])
app.include_router(public_settings_router)
app.include_router(materials_router, dependencies=[Depends(require_staff_role)])
app.include_router(machines_router, dependencies=[Depends(require_staff_role)])
app.include_router(products_router, dependencies=[Depends(require_staff_role)])
app.include_router(stats_router, dependencies=[Depends(require_staff_role)])
app.include_router(auth_router)
app.include_router(categories_router)
app.include_router(collections_router)
app.include_router(orders_router)  # Shop ops board B — auth via route Depends
app.include_router(blog_router)
app.include_router(backup_router)
app.include_router(custom_orders_router)
app.include_router(customers_router)
app.include_router(audit_router)
app.include_router(catalog_router)  # No auth — public catalog
app.include_router(commerce_router)  # Public request intake + staff request listing (auth per route)

# ── Static files for uploads with immutable caching ─────────────────
class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.mount("/uploads", CachedStaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/api/v1/uploads", CachedStaticFiles(directory=UPLOAD_DIR), name="api_v1_uploads")
app.mount("/api/uploads", CachedStaticFiles(directory=UPLOAD_DIR), name="api_uploads")


@app.get("/")
def root():
    return {
        "name": "Spaghetti Print API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
