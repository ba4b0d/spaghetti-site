"""
Category CRUD — admin and employee can manage categories.
Supports parent_id for sub-categories (tree structure).
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Category, Product
from app.schemas import CategoryCreate, CategoryUpdate
from app.routers.auth import require_staff_role
from app.routers.stats import invalidate_stats

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


def _cat_dict(c, product_counts):
    """Build a flat category dict."""
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "product_count": product_counts.get(c.id, 0),
        "sort_order": c.sort_order,
        "parent_id": c.parent_id,
    }


def _build_tree(cats_flat, parent_id=None):
    """Recursively build a nested tree from flat list."""
    tree = []
    for c in cats_flat:
        if c["parent_id"] == parent_id:
            children = _build_tree(cats_flat, c["id"])
            node = {**c, "children": children}
            tree.append(node)
    tree.sort(key=lambda x: (x["sort_order"], x["name"]))
    return tree


@router.get("", dependencies=[Depends(require_staff_role)])
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(Category).filter(Category.is_active == True).order_by(Category.sort_order, Category.name).all()

    from app.models import ProductCategory
    count_rows = (
        db.query(ProductCategory.category_id, func.count(ProductCategory.product_id))
        .join(Product, Product.id == ProductCategory.product_id)
        .filter(Product.is_active == True)
        .group_by(ProductCategory.category_id)
        .all()
    )
    cat_counts = {cat_id: count for cat_id, count in count_rows}

    flat = [_cat_dict(c, cat_counts) for c in cats]
    return _build_tree(flat)


@router.get("/all", dependencies=[Depends(require_staff_role)])
def list_all_categories_flat(db: Session = Depends(get_db)):
    """Return flat list (for admin dropdowns)."""
    cats = db.query(Category).filter(Category.is_active == True).order_by(Category.sort_order, Category.name).all()
    from app.models import ProductCategory
    count_rows = (
        db.query(ProductCategory.category_id, func.count(ProductCategory.product_id))
        .join(Product, Product.id == ProductCategory.product_id)
        .filter(Product.is_active == True)
        .group_by(ProductCategory.category_id)
        .all()
    )
    cat_counts = {cat_id: count for cat_id, count in count_rows}
    return [_cat_dict(c, cat_counts) for c in cats]


@router.post("")
def create_category(body: CategoryCreate, user=Depends(require_staff_role), db: Session = Depends(get_db)):
    name = body.name
    if db.query(Category).filter(Category.name == name).first():
        raise HTTPException(status_code=400, detail="این دسته‌بندی قبلاً وجود دارد")

    # Validate parent_id if provided
    if body.parent_id is not None:
        parent = db.query(Category).filter(Category.id == body.parent_id, Category.is_active == True).first()
        if not parent:
            raise HTTPException(status_code=400, detail="دسته‌بندی والد یافت نشد")

    cat = Category(name=name, parent_id=body.parent_id)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "message": "دسته‌بندی ایجاد شد"}


@router.put("/{cat_id}")
def update_category(cat_id: int, body: CategoryUpdate, user=Depends(require_staff_role), db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد")

    if body.name is not None:
        new_name = body.name
        if new_name != cat.name:
            if db.query(Category).filter(Category.name == new_name).first():
                raise HTTPException(status_code=400, detail="این نام قبلاً استفاده شده")
            cat.name = new_name

    if body.description is not None:
        cat.description = body.description
    if body.sort_order is not None:
        cat.sort_order = body.sort_order

    # Handle parent_id: 0 = top-level (None), >0 = set parent
    if body.parent_id == 0:
        cat.parent_id = None
    elif body.parent_id is not None and body.parent_id > 0:
        # Prevent setting self as parent
        if body.parent_id == cat_id:
            raise HTTPException(status_code=400, detail="یک دسته‌بندی نمی‌تواند والد خودش باشد")
        parent = db.query(Category).filter(Category.id == body.parent_id, Category.is_active == True).first()
        if not parent:
            raise HTTPException(status_code=400, detail="دسته‌بندی والد یافت نشد")
        cat.parent_id = body.parent_id

    db.commit()
    return {"message": "دسته‌بندی به‌روزرسانی شد"}


@router.delete("/{cat_id}")
def delete_category(cat_id: int, user=Depends(require_staff_role), db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد")

    # Move children to parent (or top-level)
    children = db.query(Category).filter(Category.parent_id == cat_id).all()
    for child in children:
        child.parent_id = cat.parent_id

    from app.models import ProductCategory
    # Clear both the many-to-many links and the legacy category text. Startup
    # migration uses Product.category to backfill categories, so leaving this
    # value would recreate a category that an administrator deleted.
    db.query(ProductCategory).filter(ProductCategory.category_id == cat_id).delete()
    db.query(Product).filter(Product.category == cat.name).update(
        {Product.category: None}, synchronize_session=False
    )
    db.delete(cat)
    db.commit()
    invalidate_stats()
    return {"message": "دسته‌بندی حذف شد"}
