import math
from sqlalchemy.orm import Session
from app.models import Settings, Machine, Material
from app.cache import get_settings_dict

# Default values used when a setting is missing from the DB
_DEFAULTS = {
    "electricity_rate_per_kwh": 812,
    "default_markup_pct": 3.0,
    "overhead_fixed_per_job": 0.3,
    "coloring_cost_per_hour": 150000,
}


def get_tier_margin_pct(base_price: float) -> float:
    """
    Return profit percentage based on finished cost (base_price in Tomans):
      - Under 50,000 Tomans        -> 200%
      - Between 50,000 and 100,000 -> 160%
      - Between 100,000 and 150,000 -> 140%
      - Between 150,000 and 200,000 -> 130%
      - Between 200,000 and 250,000 -> 120%
      - Between 250,000 and 300,000 -> 110%
      - Between 300,000 and 350,000 -> 100%
      - Between 350,000 and 400,000 -> 90%
      - Between 400,000 and 450,000 -> 80%
      - Between 450,000 and 500,000 -> 70%
      - Between 500,000 and 550,000 -> 60%
      - Above 550,000 Tomans       -> 50%
    """
    if base_price < 50000:
        return 200.0
    elif base_price < 100000:
        return 160.0
    elif base_price < 150000:
        return 140.0
    elif base_price < 200000:
        return 130.0
    elif base_price < 250000:
        return 120.0
    elif base_price < 300000:
        return 110.0
    elif base_price < 350000:
        return 100.0
    elif base_price < 400000:
        return 90.0
    elif base_price < 450000:
        return 80.0
    elif base_price < 500000:
        return 70.0
    elif base_price < 550000:
        return 60.0
    else:
        return 50.0


def round_up_to_nearest(value: float, step: float = 5000.0) -> float:
    """Round up value to the nearest step (e.g. 5,000 Tomans)."""
    if value <= 0:
        return 0.0
    return float(math.ceil(value / step) * step)


def _get_setting(db: Session, key: str, default: float = 0.0) -> float:
    """Retrieve a single setting value from DB (legacy helper)."""
    setting = db.query(Settings).filter(Settings.key == key).first()
    return setting.value if setting else default


# ── Core calculation (no DB access) ────────────────────────────────

def calculate_product_costs_from_values(
    settings_dict: dict,
    weight_g: float,
    support_g: float,
    flushed_g: float,
    print_time_hours: float,
    post_pro_hours: float,
    extras_cost: float,
    material_price_per_kg: float = 0.0,
    material_waste_pct: float = 0.05,
    machine_power_watts: float = 120.0,
    machine_purchase_price: float = 0.0,
    machine_life_hours: float = 5000.0,
    machine_maintenance_pct: float = 0.05,
) -> dict:
    """
    Pure calculation — no DB queries. All values are passed in.

    Parameters
    ----------
    settings_dict : dict
        { "electricity_rate_per_kwh": ..., "default_markup_pct": ..., ... }
    material_price_per_kg, material_waste_pct : float
        From the Material object (or defaults if no material assigned).
    machine_* : float
        From the Machine object (or defaults if no machine assigned).
    """
    electricity_rate = settings_dict.get(
        "electricity_rate_per_kwh", _DEFAULTS["electricity_rate_per_kwh"]
    )
    overhead_fixed = settings_dict.get(
        "overhead_fixed_per_job", _DEFAULTS["overhead_fixed_per_job"]
    )
    coloring_cost_per_hour = settings_dict.get(
        "coloring_cost_per_hour", _DEFAULTS["coloring_cost_per_hour"]
    )

    # ── Cost formulas ─────────────────────────────────────────────────
    material_cost = (weight_g + support_g + flushed_g) * (1 + material_waste_pct) * material_price_per_kg / 1000

    power_cost = (machine_power_watts / 1000) * print_time_hours * electricity_rate

    downtime_cost = print_time_hours * (machine_purchase_price / machine_life_hours) if machine_life_hours > 0 else 0

    maintenance_cost = downtime_cost * machine_maintenance_pct

    coloring_cost = post_pro_hours * coloring_cost_per_hour

    overhead_cost = (material_cost + power_cost + downtime_cost + maintenance_cost + coloring_cost) * overhead_fixed

    base_price = material_cost + power_cost + downtime_cost + maintenance_cost + coloring_cost + overhead_cost + extras_cost

    margin_pct = get_tier_margin_pct(base_price)
    raw_suggested_price = base_price * (1.0 + margin_pct / 100.0) if base_price > 0 else 0.0
    suggested_price = round_up_to_nearest(raw_suggested_price, 5000.0)

    gross_margin = suggested_price - base_price

    return {
        "material_cost": round(material_cost, 2),
        "power_cost": round(power_cost, 2),
        "downtime_cost": round(downtime_cost, 2),
        "maintenance_cost": round(maintenance_cost, 2),
        "coloring_cost": round(coloring_cost, 2),
        "overhead_cost": round(overhead_cost, 2),
        "base_price": round(base_price, 2),
        "suggested_price": round(suggested_price, 2),
        "gross_margin": round(gross_margin, 2),
        "margin_pct": round(margin_pct, 2),
    }


# ── Dict-preloaded wrapper (avoids per-product DB queries) ─────────

def calculate_product_costs_from_dicts(
    product,
    material,
    machine,
    settings: dict,
) -> dict:
    """
    Calculate costs using pre-fetched material/machine ORM objects and a
    cached settings dict.  No DB queries — safe for batch loops.
    """
    material_price_per_kg = material.price_per_kg if material else 0.0
    material_waste_pct = material.waste_pct if material else 0.05
    machine_power_watts = machine.power_watts if machine else 120.0
    machine_purchase_price = machine.purchase_price if machine else 0.0
    machine_life_hours = machine.life_hours if machine else 5000.0
    machine_maintenance_pct = machine.maintenance_pct if machine else 0.05

    return calculate_product_costs_from_values(
        settings,
        weight_g=product.weight_g,
        support_g=product.support_g,
        flushed_g=product.flushed_g,
        print_time_hours=product.print_time_hours,
        post_pro_hours=product.post_pro_hours,
        extras_cost=product.extras_cost,
        material_price_per_kg=material_price_per_kg,
        material_waste_pct=material_waste_pct,
        machine_power_watts=machine_power_watts,
        machine_purchase_price=machine_purchase_price,
        machine_life_hours=machine_life_hours,
        machine_maintenance_pct=machine_maintenance_pct,
    )


# ── DB-aware wrapper (backward compatible) ─────────────────────────

def calculate_product_costs(
    db: Session,
    weight_g: float,
    support_g: float,
    flushed_g: float,
    print_time_hours: float,
    post_pro_hours: float,
    extras_cost: float,
    machine_id: int | None = None,
    material_id: int | None = None,
) -> dict:
    """
    Calculate full cost breakdown for a product.
    Uses cached settings; queries DB only for material/machine rows.
    """
    settings = get_settings_dict(db)

    material_price_per_kg = 0.0
    material_waste_pct = 0.05
    machine_power_watts = 120.0
    machine_purchase_price = 0.0
    machine_life_hours = 5000.0
    machine_maintenance_pct = 0.05

    if material_id:
        mat = db.query(Material).filter(Material.id == material_id).first()
        if mat:
            material_price_per_kg = mat.price_per_kg
            material_waste_pct = mat.waste_pct

    if machine_id:
        mach = db.query(Machine).filter(Machine.id == machine_id).first()
        if mach:
            machine_power_watts = mach.power_watts
            machine_purchase_price = mach.purchase_price
            machine_life_hours = mach.life_hours
            machine_maintenance_pct = mach.maintenance_pct

    return calculate_product_costs_from_values(
        settings,
        weight_g=weight_g,
        support_g=support_g,
        flushed_g=flushed_g,
        print_time_hours=print_time_hours,
        post_pro_hours=post_pro_hours,
        extras_cost=extras_cost,
        material_price_per_kg=material_price_per_kg,
        material_waste_pct=material_waste_pct,
        machine_power_watts=machine_power_watts,
        machine_purchase_price=machine_purchase_price,
        machine_life_hours=machine_life_hours,
        machine_maintenance_pct=machine_maintenance_pct,
    )
