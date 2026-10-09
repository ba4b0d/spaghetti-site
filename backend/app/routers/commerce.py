"""Commerce router — website cart request intake (Task 1 slice).

Public:
    POST /api/v1/commerce/requests        submit a cart request (pending review)

Staff:
    GET  /api/v1/commerce/staff/requests  review queue with item snapshots

Later tasks add invoice draft/approval/revoke and payment endpoints to this
router. Handlers stay thin; validation and persistence live in
``app.services.commerce``.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import limiter, require_staff_role
from app.services import commerce as commerce_service
from app.services.commerce import (
    MAX_DISTINCT_PRODUCTS,
    MAX_QTY,
    MIN_QTY,
    CommerceValidationError,
)

router = APIRouter(prefix="/api/v1/commerce", tags=["commerce"])

VALID_MESSENGERS = ("telegram", "bale")


class CommerceRequestItemIn(BaseModel):
    product_id: int = Field(..., ge=1)
    qty: int = Field(..., ge=MIN_QTY, le=MAX_QTY)


class CommerceRequestCreate(BaseModel):
    # Extra fields (including any client-supplied price) are ignored — the
    # server snapshots catalogue data and never trusts a client amount.
    customer_name: str = Field(..., min_length=1, max_length=120)
    mobile: str
    messenger: str
    messenger_handle: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=2000)
    items: list[CommerceRequestItemIn] = Field(..., min_length=1, max_length=MAX_DISTINCT_PRODUCTS)

    @field_validator("customer_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("نام مشتری الزامی است")
        return value

    @field_validator("mobile")
    @classmethod
    def _valid_iranian_mobile(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) != 11 or not value.startswith("09") or not value.isdigit():
            raise ValueError("شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود")
        return value

    @field_validator("messenger")
    @classmethod
    def _valid_messenger(cls, value: str) -> str:
        if value not in VALID_MESSENGERS:
            raise ValueError("پیامرسان نامعتبر است")
        return value

    @model_validator(mode="after")
    def _distinct_products(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("محصول تکراری در سبد خرید مجاز نیست")
        return self


@router.post("/requests")
@limiter.limit("5/minute")
def create_request(
    request: Request,
    body: CommerceRequestCreate,
    db: Session = Depends(get_db),
):
    """Public — record a pending-review website cart request.

    Returns an opaque receipt identifier only; no invoice or payment link is
    produced before staff review.
    """
    try:
        created = commerce_service.create_website_request(
            db,
            customer_name=body.customer_name,
            mobile=body.mobile,
            messenger=body.messenger,
            messenger_handle=body.messenger_handle,
            address=body.address,
            note=body.note,
            items=[{"product_id": i.product_id, "qty": i.qty} for i in body.items],
        )
    except CommerceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return commerce_service.serialize_public_receipt(created)


@router.get("/staff/requests")
def list_staff_requests(
    request: Request,
    user=Depends(require_staff_role),
    db: Session = Depends(get_db),
):
    """Staff — newest-first request queue with product snapshots."""
    rows = commerce_service.list_staff_requests(db)
    return [commerce_service.serialize_staff_request(r) for r in rows]
