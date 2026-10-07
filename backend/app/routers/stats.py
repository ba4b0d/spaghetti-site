"""
Stats endpoint — optimized to avoid N+1 queries.

Loads settings, materials, and machines ONCE per request, then iterates
products using the pure-calculation function (no DB calls per product).

Also returns KISS shop-ops monthly order totals (not accounting).

Results are cached in-memory for 60 seconds.
"""
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Material, Machine, Order, SiteView
from app.cache import get_settings_dict
from app.calculator import calculate_product_costs_from_values

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

# ── In-memory stats cache ──────────────────────────────────────────
_STATS_TTL = 60  # seconds
_stats_cache: dict = {}

_OPEN_STATUSES = frozenset({"new", "quoted", "printing", "ready"})
TEHRAN = ZoneInfo("Asia/Tehran")


def _invalidate_stats_cache():
    _stats_cache.clear()


def _month_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime, int, int]:
    """Inclusive start / exclusive end of current calendar month (UTC)."""
    now = now or datetime.now(timezone.utc)
    y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    # exclusive end = first day of next month
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end, y, m


from sqlalchemy import func, case


def _order_ops_stats(db: Session) -> dict:
    """Monthly order volume + cash in using SQL aggregation queries."""
    start, end, year, month = _month_bounds_utc()
    start_naive = start.replace(tzinfo=None)
    end_naive = end.replace(tzinfo=None)

    # 1. Total open active orders
    open_count = (
        db.query(func.count(Order.id))
        .filter(Order.is_active == True, Order.status.in_(_OPEN_STATUSES))
        .scalar()
        or 0
    )

    # 2. Monthly active non-cancelled orders aggregation
    month_stats = (
        db.query(
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.paid_amount), 0.0).label("paid"),
            func.coalesce(func.sum(Order.quoted_price), 0.0).label("quoted"),
            func.coalesce(
                func.sum(
                    case(
                        (Order.quoted_price > Order.paid_amount, Order.quoted_price - Order.paid_amount),
                        else_=0.0,
                    )
                ),
                0.0,
            ).label("remaining"),
        )
        .filter(
            Order.is_active == True,
            Order.status != "cancelled",
            Order.created_at >= start_naive,
            Order.created_at < end_naive,
        )
        .first()
    )

    return {
        "orders_this_month": month_stats.count if month_stats else 0,
        "orders_paid_this_month": round(float(month_stats.paid), 2) if month_stats else 0.0,
        "orders_quoted_this_month": round(float(month_stats.quoted), 2) if month_stats else 0.0,
        "orders_remaining_this_month": round(float(month_stats.remaining), 2) if month_stats else 0.0,
        "orders_open": open_count,
        "orders_month": month,
        "orders_year": year,
    }


def _site_view_stats(db: Session, now: datetime | None = None) -> dict:
    """Privacy-safe public-site analytics, grouped by Asia/Tehran calendar."""
    current = (now or datetime.now(timezone.utc)).astimezone(TEHRAN)
    events = db.query(SiteView).all()

    def local_date(event: SiteView):
        value = event.created_at
        if value.tzinfo is None:  # SQLite returns naive UTC datetimes.
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(TEHRAN).date()

    today = current.date()
    week_start = today - timedelta(days=today.weekday())
    daily_dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    weekly_starts = [week_start - timedelta(weeks=offset) for offset in range(7, -1, -1)]
    daily_counts = Counter(local_date(event) for event in events)
    weekly_counts = Counter(
        local_date(event) - timedelta(days=local_date(event).weekday()) for event in events
    )
    top_content = Counter((event.path, event.content_type, event.content_slug) for event in events)

    return {
        "site_views_today": daily_counts[today],
        "site_views_week": sum(1 for event in events if local_date(event) >= week_start),
        "site_views_total": len(events),
        "site_views_daily": [{"date": day.isoformat(), "views": daily_counts[day]} for day in daily_dates],
        "site_views_weekly": [{"week_start": day.isoformat(), "views": weekly_counts[day]} for day in weekly_starts],
        "site_top_content": [
            {"path": path, "content_type": content_type, "content_slug": content_slug, "views": views}
            for (path, content_type, content_slug), views in top_content.most_common(5)
        ],
    }


def _insights(db: Session) -> dict:
    """Top-selling products, most-viewed products, orders-by-status, revenue-by-month."""
    # Orders by status
    status_rows = (
        db.query(Order.status, func.count(Order.id))
        .filter(Order.is_active == True)  # noqa: E712
        .group_by(Order.status)
        .all()
    )
    orders_by_status = {s: c for s, c in status_rows}

    # Top selling products (from orders that reference a product_id)
    top_selling = (
        db.query(Order.product_id, func.count(Order.id).label("cnt"), func.coalesce(func.sum(Order.quoted_price * Order.qty), 0.0).label("total"))
        .filter(Order.is_active == True, Order.product_id.isnot(None))  # noqa: E712
        .group_by(Order.product_id)
        .order_by(func.count(Order.id).desc())
        .limit(8)
        .all()
    )
    top_products = []
    for pid, cnt, total in top_selling:
        p = db.query(Product).filter(Product.id == pid).first()
        top_products.append({
            "product_id": p.product_id if p else str(pid),
            "name": p.name if p else "—",
            "orders": int(cnt),
            "total": round(float(total), 2),
        })

    # Most viewed products
    from app.models import ProductView
    view_rows = (
        db.query(ProductView.product_id, ProductView.views)
        .order_by(ProductView.views.desc())
        .limit(8)
        .all()
    )
    top_views = []
    for pid, views in view_rows:
        p = db.query(Product).filter(Product.id == pid).first()
        top_views.append({
            "product_id": p.product_id if p else str(pid),
            "name": p.name if p else "—",
            "views": int(views),
        })

    # Revenue by month (last 6 months, quoted not cancelled)
    from sqlalchemy import extract
    month_rows = (
        db.query(
            extract("year", Order.created_at).label("y"),
            extract("month", Order.created_at).label("m"),
            func.coalesce(func.sum(Order.quoted_price * Order.qty), 0.0).label("total"),
        )
        .filter(Order.is_active == True, Order.status != "cancelled")  # noqa: E712
        .group_by(extract("year", Order.created_at), extract("month", Order.created_at))
        .order_by(extract("year", Order.created_at).desc(), extract("month", Order.created_at).desc())
        .limit(6)
        .all()
    )
    revenue_by_month = [
        {"year": int(y), "month": int(m), "total": round(float(total), 2)}
        for y, m, total in month_rows
    ]
    revenue_by_month.reverse()

    return {
        "orders_by_status": orders_by_status,
        "top_selling_products": top_products,
        "most_viewed_products": top_views,
        "revenue_by_month": revenue_by_month,
    }


@router.get("")
def get_stats(db: Session = Depends(get_db)):
    """Aggregate stats across products — O(1) DB reads for settings."""
    now = time.time()
    cached = _stats_cache.get("stats")
    if cached and (now - cached["ts"]) < _STATS_TTL:
        return cached["data"]

    # ── Batch-load everything ONCE ────────────────────────────────────
    settings = get_settings_dict(db)

    all_materials = {m.id: m for m in db.query(Material).all()}
    all_machines = {m.id: m for m in db.query(Machine).all()}

    total_products = db.query(Product).count()
    all_products = db.query(Product).filter(Product.is_active == True).all()
    active_products = all_products  # already filtered
    total_materials = sum(1 for m in all_materials.values() if m.is_active)
    total_machines = sum(1 for m in all_machines.values() if m.is_active)

    # ── Compute margins for active products ────────────────────────────
    margins = []
    prices = []
    categories: dict[str, int] = {}

    for p in active_products:
        mat = all_materials.get(p.material_id) if p.material_id else None
        mach = all_machines.get(p.machine_id) if p.machine_id else None

        costs = calculate_product_costs_from_values(
            settings,
            weight_g=p.weight_g,
            support_g=p.support_g,
            flushed_g=p.flushed_g,
            print_time_hours=p.print_time_hours,
            post_pro_hours=p.post_pro_hours,
            extras_cost=p.extras_cost,
            material_price_per_kg=mat.price_per_kg if mat else 0.0,
            material_waste_pct=mat.waste_pct if mat else 0.05,
            machine_power_watts=mach.power_watts if mach else 120.0,
            machine_purchase_price=mach.purchase_price if mach else 0.0,
            machine_life_hours=mach.life_hours if mach else 5000.0,
            machine_maintenance_pct=mach.maintenance_pct if mach else 0.05,
        )
        margins.append(costs["margin_pct"])
        prices.append(costs["suggested_price"])
        cat = p.category or "uncategorized"
        categories[cat] = categories.get(cat, 0) + 1

    avg_margin = round(sum(margins) / len(margins), 2) if margins else 0
    price_min = round(min(prices), 2) if prices else None
    price_max = round(max(prices), 2) if prices else None

    order_ops = _order_ops_stats(db)
    insights = _insights(db)
    site_views = _site_view_stats(db)

    result = {
        "total_products": total_products,
        "active_products": len(active_products),
        "total_materials": total_materials,
        "total_machines": total_machines,
        "avg_margin_pct": avg_margin,
        "price_min": price_min,
        "price_max": price_max,
        "products_per_category": categories,
        **order_ops,
        **insights,
        **site_views,
    }

    _stats_cache["stats"] = {"data": result, "ts": now}
    return result


# Expose invalidation for other routers to call after writes
def invalidate_stats():
    """Call from product/material/machine/settings/order routers after mutations."""
    _stats_cache.clear()
