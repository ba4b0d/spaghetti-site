from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


# ── Settings ──────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    key: str
    value: float
    description: Optional[str] = None
    string_value: Optional[str] = None


class SettingsBulkUpdate(BaseModel):
    settings: list[SettingsUpdate]


class SettingsResponse(BaseModel):
    id: int
    key: str
    value: float
    description: Optional[str] = ""

    model_config = ConfigDict(from_attributes=True)


# ── Machine ───────────────────────────────────────────────────────────────

class MachineCreate(BaseModel):
    name: str
    power_watts: float = Field(default=100, gt=0)
    purchase_price: float = Field(default=0, ge=0)
    life_hours: float = Field(default=5000, ge=0)
    maintenance_pct: float = Field(default=0.05, ge=0, le=1)
    is_active: bool = True
    is_default: bool = False

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('نام ماشین نمی‌تواند خالی باشد')
        return v.strip()


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    power_watts: Optional[float] = None
    purchase_price: Optional[float] = None
    life_hours: Optional[float] = None
    maintenance_pct: Optional[float] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class MachineResponse(BaseModel):
    id: int
    name: str
    power_watts: float
    purchase_price: float
    life_hours: float
    maintenance_pct: float
    is_active: bool
    is_default: bool = False

    model_config = ConfigDict(from_attributes=True)


# ── Material ──────────────────────────────────────────────────────────────

class MaterialCreate(BaseModel):
    name: str
    price_per_kg: float = 0
    waste_pct: float = 0.05
    color: str = ""
    notes: str = ""
    is_active: bool = True
    is_default: bool = False
    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('نام ماده نمی‌تواند خالی باشد')
        return v.strip()

    @field_validator('price_per_kg')
    @classmethod
    def price_not_negative(cls, v):
        if v < 0:
            raise ValueError('قیمت نمی‌تواند منفی باشد')
        return v


class MaterialUpdate(BaseModel):
    name: Optional[str] = None
    price_per_kg: Optional[float] = None
    waste_pct: Optional[float] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class MaterialResponse(BaseModel):
    id: int
    name: str
    price_per_kg: float
    waste_pct: float
    color: Optional[str] = ""
    notes: Optional[str] = ""
    is_active: bool
    is_default: bool = False

    model_config = ConfigDict(from_attributes=True)


# ── Product ───────────────────────────────────────────────────────────────

class ProductImageResponse(BaseModel):
    id: int
    image_url: str
    sort_order: int
    is_primary: bool

    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    name: str
    product_id: Optional[str] = ""
    qty: int = 1
    machine_id: Optional[int] = None
    material_id: Optional[int] = None
    weight_g: float = 0
    support_g: float = 0
    flushed_g: float = 0
    dimension_x: Optional[float] = None
    dimension_y: Optional[float] = None
    dimension_z: Optional[float] = None
    print_time_hours: float = 0
    post_pro_hours: float = 0
    extras_cost: float = 0
    final_price: Optional[float] = None
    category: str = ""
    notes: str = ""
    package_info: Optional[str] = ""
    image_url: Optional[str] = None
    is_active: bool = True
    slug: Optional[str] = None
    tags: Optional[str] = None
    category_ids: Optional[list[int]] = None
    collection_ids: Optional[list[int]] = None

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('نام محصول نمی‌تواند خالی باشد')
        return v.strip()

    @field_validator('weight_g')
    @classmethod
    def weight_non_negative(cls, v):
        if v < 0:
            raise ValueError('وزن نمی‌تواند منفی باشد')
        return v

    @field_validator('print_time_hours')
    @classmethod
    def print_time_non_negative(cls, v):
        if v < 0:
            raise ValueError('زمان چاپ نمی‌تواند منفی باشد')
        return v


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    product_id: Optional[str] = None
    qty: Optional[int] = None
    machine_id: Optional[int] = None
    material_id: Optional[int] = None
    weight_g: Optional[float] = None
    support_g: Optional[float] = None
    flushed_g: Optional[float] = None
    dimension_x: Optional[float] = None
    dimension_y: Optional[float] = None
    dimension_z: Optional[float] = None
    print_time_hours: Optional[float] = None
    post_pro_hours: Optional[float] = None
    extras_cost: Optional[float] = None
    final_price: Optional[float] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    package_info: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None
    slug: Optional[str] = None
    tags: Optional[str] = None
    category_ids: Optional[list[int]] = None
    collection_ids: Optional[list[int]] = None



class ProductResponse(BaseModel):
    id: int
    product_id: str
    name: str
    qty: int
    machine_id: Optional[int] = None
    machine_name: Optional[str] = None
    material_id: Optional[int] = None
    material_name: Optional[str] = None
    material_color: Optional[str] = None
    weight_g: float
    support_g: float
    flushed_g: float
    dimension_x: Optional[float] = None
    dimension_y: Optional[float] = None
    dimension_z: Optional[float] = None
    print_time_hours: float
    post_pro_hours: float
    extras_cost: float
    image_url: Optional[str] = None
    images: list[ProductImageResponse] = []
    final_price: Optional[float] = None
    category: Optional[str] = ""
    categories: list[dict] = []
    collections: list[dict] = []
    notes: Optional[str] = ""
    package_info: Optional[str] = ""
    is_active: bool
    slug: Optional[str] = None
    tags: Optional[str] = None
    # Computed cost fields
    material_cost: float = 0
    power_cost: float = 0
    downtime_cost: float = 0
    maintenance_cost: float = 0
    coloring_cost: float = 0
    overhead: float = 0
    base_price: float = 0
    suggested_price: float = 0
    margin_pct: float = 0

    model_config = ConfigDict(from_attributes=True)


# ── Calculator (stateless) ───────────────────────────────────────────────

class CalculateRequest(BaseModel):
    weight_g: float = 0
    support_g: float = 0
    flushed_g: float = 0
    print_time_hours: float = 0
    post_pro_hours: float = 0
    extras_cost: float = 0
    machine_id: Optional[int] = None
    material_id: Optional[int] = None


class CalculateResponse(BaseModel):
    material_cost: float
    power_cost: float
    downtime_cost: float
    maintenance_cost: float
    coloring_cost: float
    overhead_cost: float
    base_price: float
    suggested_price: float
    gross_margin: float
    margin_pct: float

    model_config = ConfigDict(from_attributes=True)


# ── Category ──────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('نام دسته‌بندی الزامی است')
        return v.strip()


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    parent_id: Optional[int] = None


# ── Collection ─────────────────────────────────────────────────────────────

class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    slug: Optional[str] = None
    sort_order: Optional[int] = 0
    product_ids: Optional[list[int]] = []

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('نام کالکشن الزامی است')
        return v.strip()


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    product_ids: Optional[list[int]] = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str = ""
    is_active: bool = True
    sort_order: int = 0
    product_count: int = 0
    product_ids: list[int] = []

    model_config = ConfigDict(from_attributes=True)


# ── Order (shop ops board B) ──────────────────────────────────────────────

ORDER_STATUS_VALUES = ("new", "quoted", "printing", "ready", "delivered", "cancelled")


def _empty_date(v):
    """Treat '', whitespace, and missing as None for optional date fields."""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v

# ── Order Items (must be before OrderCreate/OrderUpdate) ──────────────────

class OrderItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_label: str = ""
    qty: int = Field(default=1, ge=1)
    unit_price: float = Field(default=0, ge=0)


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    product_id: Optional[int] = None
    product_label: str
    qty: int
    unit_price: float
    unit_cost: Optional[float] = None
    line_total: float = 0  # qty × unit_price

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    customer_name: str
    contact: str = ""
    product_label: str = ""
    product_id: Optional[int] = None
    qty: int = Field(default=1, ge=1)
    quoted_price: float = Field(default=0, ge=0)
    paid_amount: float = Field(default=0, ge=0)
    status: str = "new"
    notes: str = ""
    started_at: Optional[date] = None
    ready_by: Optional[date] = None
    items: list["OrderItemCreate"] = []

    @field_validator("customer_name")
    @classmethod
    def customer_name_not_empty(cls, v):
        if not v or not str(v).strip():
            raise ValueError("نام مشتری الزامی است")
        return str(v).strip()

    @field_validator("status")
    @classmethod
    def status_allowed(cls, v):
        if v not in ORDER_STATUS_VALUES:
            raise ValueError("وضعیت نامعتبر است")
        return v

    @field_validator("started_at", "ready_by", mode="before")
    @classmethod
    def optional_dates(cls, v):
        return _empty_date(v)


class OrderUpdate(BaseModel):
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    product_label: Optional[str] = None
    product_id: Optional[int] = None
    qty: Optional[int] = Field(default=None, ge=1)
    quoted_price: Optional[float] = Field(default=None, ge=0)
    paid_amount: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None
    notes: Optional[str] = None
    started_at: Optional[date] = None
    ready_by: Optional[date] = None
    is_active: Optional[bool] = None
    items: Optional[list["OrderItemCreate"]] = None

    @field_validator("customer_name")
    @classmethod
    def customer_name_not_empty(cls, v):
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("نام مشتری الزامی است")
        return str(v).strip()

    @field_validator("status", mode="before")
    @classmethod
    def status_allowed(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if v not in ORDER_STATUS_VALUES:
            raise ValueError("وضعیت نامعتبر است")
        return v

    @field_validator("started_at", "ready_by", mode="before")
    @classmethod
    def optional_dates(cls, v):
        return _empty_date(v)


# ── Image Reorder ────────────────────────────────────────────────────────

class ImageReorderRequest(BaseModel):
    order: list[int]


# ── Stats ─────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    total_products: int
    active_products: int
    total_materials: int
    total_machines: int
    avg_margin_pct: float
    price_min: Optional[float]
    price_max: Optional[float]
    products_per_category: dict[str, int]

    model_config = ConfigDict(from_attributes=True)


# ── Blog ──────────────────────────────────────────────────────────────────

class BlogPostCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    summary: Optional[str] = ""
    content: Optional[str] = ""
    cover_image: Optional[str] = None
    is_published: bool = True

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("عنوان مقاله نمی‌تواند خالی باشد")
        return v.strip()


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    cover_image: Optional[str] = None
    is_published: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("عنوان مقاله نمی‌تواند خالی باشد")
            return v.strip()
        return v


class BlogPostResponse(BaseModel):
    id: int
    title: str
    slug: str
    summary: Optional[str] = ""
    content: Optional[str] = ""
    cover_image: Optional[str] = None
    is_published: bool
    views: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

