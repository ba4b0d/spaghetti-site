from sqlalchemy import Column, Integer, Float, String, Boolean, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import re
import unicodedata
from app.database import Base


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Float, nullable=False, default=0.0)
    string_value = Column(String, default="")
    description = Column(String, default="")


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    power_watts = Column(Float, nullable=False, default=0)
    purchase_price = Column(Float, nullable=False, default=0)
    life_hours = Column(Float, nullable=False, default=5000)
    maintenance_pct = Column(Float, nullable=False, default=0.05)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)

    products = relationship("Product", back_populates="machine")


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("name", "color", name="uq_material_name_color"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price_per_kg = Column(Float, nullable=False, default=0)
    waste_pct = Column(Float, nullable=False, default=0.05)
    color = Column(String, default="")
    notes = Column(String, default="")
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)

    products = relationship("Product", back_populates="material")


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String, nullable=False)
    sort_order = Column(Integer, default=0, index=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    product = relationship("Product", back_populates="images")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, default="")
    name = Column(String, nullable=False)
    qty = Column(Integer, default=1)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True, index=True)
    weight_g = Column(Float, default=0)
    support_g = Column(Float, default=0)
    flushed_g = Column(Float, default=0)
    dimension_x = Column(Float, nullable=True)  # mm
    dimension_y = Column(Float, nullable=True)  # mm
    dimension_z = Column(Float, nullable=True)  # mm
    print_time_hours = Column(Float, default=0)
    post_pro_hours = Column(Float, default=0)
    extras_cost = Column(Float, default=0)
    final_price = Column(Float, nullable=True)
    image_url = Column(String, nullable=True, default=None)  # Kept for backward compat — primary image
    model_file = Column(String, nullable=True, default=None)  # 3MF/STL model file path
    category = Column(String, default="", index=True)
    notes = Column(String, default="")
    package_info = Column(String, default="")
    is_active = Column(Boolean, default=True, index=True)
    slug = Column(String, unique=True, nullable=True, index=True)
    tags = Column(String, nullable=True, default="")  # comma-separated: 'keychain,gift,pet'
    machine = relationship("Machine", back_populates="products")
    material = relationship("Material", back_populates="products")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order")
    categories = relationship("Category", secondary="product_categories", backref="products")
    collections = relationship("Collection", secondary="product_collections", back_populates="products")

    @staticmethod
    def generate_slug(name: str) -> str:
        """Convert a product name (Persian/English) to a URL-safe slug preserving Farsi Unicode text."""
        if not name:
            return ""
        # Keep letters, numbers, spaces, and hyphens (supports Farsi/Arabic + Latin)
        slug = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug or "product"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, default="")
    role = Column(String, nullable=False, default="employee")  # admin | employee | writer
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(String, default="")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    # Self-referencing relationships
    children = relationship("Category", backref="parent", remote_side="Category.id", lazy="select")


class ProductCategory(Base):
    """Many-to-many junction: Product ↔ Category"""
    __tablename__ = "product_categories"
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True, index=True)


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    description = Column(String, default="")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    products = relationship("Product", secondary="product_collections", back_populates="collections")


class ProductCollection(Base):
    """Many-to-many junction: Product ↔ Collection"""
    __tablename__ = "product_collections"
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True, index=True)


# Fixed shop-ops statuses (B board) — keep list short for ADHD/OCD-friendly UI
ORDER_STATUSES = (
    "new",        # جدید
    "quoted",     # قیمت‌داده‌شده
    "printing",   # در حال چاپ
    "ready",      # آماده تحویل
    "delivered",  # تحویل‌شده
    "cancelled",  # لغو
)


class Order(Base):
    """Minimal shop order board — not accounting."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False, default="", index=True)
    contact = Column(String, default="")  # phone / Telegram / etc.
    product_label = Column(String, default="")  # free text what they ordered
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    qty = Column(Integer, default=1)
    quoted_price = Column(Float, default=0)  # تومان (per unit)
    paid_amount = Column(Float, default=0)   # تومان
    unit_cost = Column(Float, nullable=True)  # snapshot of product base_price at creation
    status = Column(String, nullable=False, default="new", index=True)
    notes = Column(String, default="")
    # Shop schedule (optional) — not notifications yet
    started_at = Column(Date, nullable=True)   # تاریخ شروع کار
    ready_by = Column(Date, nullable=True)     # موعد آماده ارسال / تحویل
    is_active = Column(Boolean, default=True, index=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    product = relationship("Product", lazy="joined")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id")


class OrderItem(Base):
    """Line item within an order — supports multi-product orders."""
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    product_label = Column(String, default="")  # free text fallback
    qty = Column(Integer, default=1)
    unit_price = Column(Float, default=0)  # quoted price per unit
    unit_cost = Column(Float, nullable=True)  # snapshot of base_price
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="items")
    product = relationship("Product", lazy="joined")


class BlogPost(Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    summary = Column(String, default="")
    content = Column(String, default="")  # Markdown/HTML content
    cover_image = Column(String, nullable=True, default=None)
    is_published = Column(Boolean, default=True, index=True)
    views = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @staticmethod
    def generate_slug(title: str) -> str:
        """Convert a blog title (Persian/English) to a URL-safe slug preserving Farsi Unicode text."""
        if not title:
            return ""
        slug = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug or "post"


class CustomOrderRequest(Base):
    """Lead captured from the public /custom-order form (no auth needed to submit)."""
    __tablename__ = "custom_order_requests"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="")
    contact = Column(String, default="")          # phone / Telegram handle
    channel = Column(String, default="telegram") # preferred channel
    description = Column(String, default="")      # what they want printed
    reference_product = Column(String, default="") # optional product code / slug
    image_url = Column(String, nullable=True)     # optional attached photo
    status = Column(String, default="new", index=True)  # new | contacted | closed
    notes = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ProductView(Base):
    """Increments when a public product page is viewed (for 'most viewed' dashboard)."""
    __tablename__ = "product_views"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True, index=True)
    views = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SiteView(Base):
    """Minimal public-site view event; deliberately contains no visitor identity."""
    __tablename__ = "site_views"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String(500), nullable=False, index=True)
    content_type = Column(String(32), nullable=False, default="page")
    content_slug = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class AuditLog(Base):
    """Who changed what — products, orders, settings, collections."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, default="")       # username or 'system'
    action = Column(String, default="")     # create | update | delete
    entity = Column(String, default="")     # product | order | collection | settings | customer
    entity_id = Column(Integer, nullable=True)
    summary = Column(String, default="")    # human-readable description
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


# ── Commerce: website cart requests (pending staff review) ────────────
# State machine for a website-submitted request. A request is NEVER payable
# on its own — staff must convert it into a reviewed invoice (Task 2).
COMMERCE_REQUEST_STATES = (
    "pending_review",  # submitted from the storefront, awaiting staff review
    "converted",       # staff converted it into an invoice
    "cancelled",       # staff dismissed it
)


class CommerceRequest(Base):
    """A customer-submitted cart request from the public storefront.

    Contains no authoritative prices: item prices are indicative catalogue
    snapshots only, and payment is impossible until staff review.
    """
    __tablename__ = "commerce_requests"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(String(40), unique=True, nullable=False, index=True)  # opaque public receipt
    customer_name = Column(String(120), nullable=False)
    mobile = Column(String(11), nullable=False, index=True)   # Iranian 09xxxxxxxxx
    messenger = Column(String(20), nullable=False)            # telegram | bale
    messenger_handle = Column(String(100), default="")
    address = Column(String(500), default="")
    note = Column(String(2000), default="")
    state = Column(String(20), nullable=False, default="pending_review", index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    items = relationship(
        "CommerceRequestItem",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="CommerceRequestItem.id",
    )


class CommerceRequestItem(Base):
    """Line item snapshot for a website request (product id, name, qty).

    ``indicative_unit_price_toman`` is an optional integer catalogue estimate
    captured server-side; it is never trusted from the client and never
    treated as a payable amount.
    """
    __tablename__ = "commerce_request_items"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("commerce_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Snapshot-preserving link: a permanent product delete must not erase (or
    # block on) historical review line items, so the FK is nullable and
    # detaches to NULL rather than cascading. See products.permanent_delete,
    # which also unlinks explicitly for tables created before this clause.
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    display_name = Column(String(255), nullable=False, default="")
    qty = Column(Integer, nullable=False, default=1)
    indicative_unit_price_toman = Column(Integer, nullable=True)  # integer Toman estimate

    request = relationship("CommerceRequest", back_populates="items")
    product = relationship("Product", lazy="joined")

