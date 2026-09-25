"""
Pure-function calculator tests — no DB or API calls.
"""
import sys
import os
import math
import pytest

# Ensure backend is on path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.calculator import (
    calculate_product_costs_from_values,
    get_tier_margin_pct,
    round_up_to_nearest,
)


# ── Settings dict used for all tests ─────────────────────────────────
SETTINGS = {
    "electricity_rate_per_kwh": 812,
    "default_markup_pct": 3.0,
    "overhead_fixed_per_job": 0.3,
    "coloring_cost_per_hour": 150000,
}


def test_material_cost_calculation():
    """material_cost = (weight + support + flushed) * (1 + waste%) * price / 1000"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=100, support_g=20, flushed_g=10,
        print_time_hours=2, post_pro_hours=0, extras_cost=0,
        material_price_per_kg=2600000, material_waste_pct=0.05,
    )
    # (100 + 20 + 10) * 1.05 * 2600000 / 1000 = 130 * 1.05 * 2600 = 354900
    assert result["material_cost"] == 354900.0


def test_power_cost_calculation():
    """power_cost = (watts/1000) * hours * rate"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=50, support_g=0, flushed_g=0,
        print_time_hours=5, post_pro_hours=0, extras_cost=0,
        machine_power_watts=120,
    )
    # (120/1000) * 5 * 812 = 0.12 * 5 * 812 = 487.2
    assert result["power_cost"] == 487.2


def test_downtime_cost_calculation():
    """downtime_cost = hours * (purchase_price / life_hours)"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=50, support_g=0, flushed_g=0,
        print_time_hours=10, post_pro_hours=0, extras_cost=0,
        machine_purchase_price=94000000, machine_life_hours=5000,
    )
    # 10 * (94000000 / 5000) = 10 * 18800 = 188000
    assert result["downtime_cost"] == 188000.0


def test_maintenance_cost_calculation():
    """maintenance_cost = downtime_cost * maintenance_pct"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=50, support_g=0, flushed_g=0,
        print_time_hours=10, post_pro_hours=0, extras_cost=0,
        machine_purchase_price=94000000, machine_life_hours=5000,
        machine_maintenance_pct=0.05,
    )
    # downtime = 188000, maintenance = 188000 * 0.05 = 9400
    assert result["maintenance_cost"] == 9400.0


def test_coloring_cost_calculation():
    """coloring_cost = post_pro_hours * cost_per_hour"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=50, support_g=0, flushed_g=0,
        print_time_hours=2, post_pro_hours=3, extras_cost=0,
    )
    # 3 * 150000 = 450000
    assert result["coloring_cost"] == 450000.0


def test_overhead_calculation():
    """overhead = (sum of other costs) * overhead_ratio"""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=100, support_g=0, flushed_g=0,
        print_time_hours=5, post_pro_hours=1, extras_cost=0,
        material_price_per_kg=2600000,
        machine_power_watts=120,
    )
    subtotal = (
        result["material_cost"]
        + result["power_cost"]
        + result["downtime_cost"]
        + result["maintenance_cost"]
        + result["coloring_cost"]
    )
    expected_overhead = round(subtotal * 0.3, 2)
    assert result["overhead_cost"] == expected_overhead


def test_tier_margin_percentages():
    """Verify tier profit percentages based on base cost (base_price)."""
    assert get_tier_margin_pct(0) == 200.0
    assert get_tier_margin_pct(49999) == 200.0
    assert get_tier_margin_pct(50000) == 160.0
    assert get_tier_margin_pct(99999) == 160.0
    assert get_tier_margin_pct(100000) == 140.0
    assert get_tier_margin_pct(149999) == 140.0
    assert get_tier_margin_pct(150000) == 130.0
    assert get_tier_margin_pct(199999) == 130.0
    assert get_tier_margin_pct(200000) == 120.0
    assert get_tier_margin_pct(249999) == 120.0
    assert get_tier_margin_pct(250000) == 110.0
    assert get_tier_margin_pct(299999) == 110.0
    assert get_tier_margin_pct(300000) == 100.0
    assert get_tier_margin_pct(349999) == 100.0
    assert get_tier_margin_pct(350000) == 90.0
    assert get_tier_margin_pct(399999) == 90.0
    assert get_tier_margin_pct(400000) == 80.0
    assert get_tier_margin_pct(449999) == 80.0
    assert get_tier_margin_pct(450000) == 70.0
    assert get_tier_margin_pct(499999) == 70.0
    assert get_tier_margin_pct(500000) == 60.0
    assert get_tier_margin_pct(549999) == 60.0
    assert get_tier_margin_pct(550000) == 50.0
    assert get_tier_margin_pct(1000000) == 50.0


def test_round_up_to_nearest():
    """Verify ceiling rounding to nearest 5,000 Tomans."""
    assert round_up_to_nearest(0) == 0.0
    assert round_up_to_nearest(42000, 5000) == 45000.0
    assert round_up_to_nearest(45000, 5000) == 45000.0
    assert round_up_to_nearest(45001, 5000) == 50000.0
    assert round_up_to_nearest(96000, 5000) == 100000.0


def test_suggested_price_tiered_and_rounded():
    """suggested_price applies tiered profit % and rounds up to nearest 5000."""
    # Under 50k base price: e.g. 10g @ 2600/g = 27300 material + overhead (30%) = ~35490
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=10, support_g=0, flushed_g=0,
        print_time_hours=0, post_pro_hours=0, extras_cost=0,
        material_price_per_kg=2600000, material_waste_pct=0.05,
    )
    # base = 27300 * 1.3 = 35490 (< 50k -> 200% margin -> 3x -> 106470 -> round up to 5k -> 110000)
    assert result["base_price"] == 35490.0
    assert result["margin_pct"] == 200.0
    assert result["suggested_price"] == 110000.0
    assert result["gross_margin"] == 110000.0 - 35490.0


def test_calculate_product_costs_from_values():
    """Full integration: all fields populated, verify full chain."""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=150, support_g=10, flushed_g=5,
        print_time_hours=8, post_pro_hours=1, extras_cost=50000,
        material_price_per_kg=3200000, material_waste_pct=0.07,
        machine_power_watts=120,
        machine_purchase_price=94000000, machine_life_hours=5000,
        machine_maintenance_pct=0.05,
    )
    # Verify all keys exist
    expected_keys = [
        "material_cost", "power_cost", "downtime_cost",
        "maintenance_cost", "coloring_cost", "overhead_cost",
        "base_price", "suggested_price", "gross_margin", "margin_pct",
    ]
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"

    # material_cost = (150+10+5)*1.07*3200000/1000 = 165*1.07*3200 = 564960
    assert result["material_cost"] == 564960.0
    # power_cost = 0.12 * 8 * 812 = 779.52
    assert result["power_cost"] == 779.52
    # downtime_cost = 8 * (94000000/5000) = 8 * 18800 = 150400
    assert result["downtime_cost"] == 150400.0
    # maintenance = 150400 * 0.05 = 7520
    assert result["maintenance_cost"] == 7520.0
    # coloring = 1 * 150000 = 150000
    assert result["coloring_cost"] == 150000.0

    # base_price includes overhead + extras
    expected_base = round(
        564960 + 779.52 + 150400 + 7520 + 150000
        + round((564960 + 779.52 + 150400 + 7520 + 150000) * 0.3, 2)
        + 50000, 2
    )
    assert result["base_price"] == expected_base
    # Base price is > 550,000 -> 50% margin -> 1.5x -> raw = 1776131.37 -> ceil to 5k = 1780000
    assert result["margin_pct"] == 50.0
    expected_suggested = math.ceil((expected_base * 1.5) / 5000.0) * 5000.0
    assert result["suggested_price"] == expected_suggested


def test_edge_case_zero_material():
    """Zero material weight should give zero material cost."""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=0, support_g=0, flushed_g=0,
        print_time_hours=1, post_pro_hours=0, extras_cost=0,
        material_price_per_kg=2600000,
    )
    assert result["material_cost"] == 0.0
    assert result["base_price"] >= 0
    assert result["suggested_price"] >= 0


def test_edge_case_zero_print_time():
    """Zero print time should give zero power, downtime, and maintenance costs."""
    result = calculate_product_costs_from_values(
        SETTINGS,
        weight_g=50, support_g=0, flushed_g=0,
        print_time_hours=0, post_pro_hours=0, extras_cost=0,
        material_price_per_kg=2600000,
        machine_purchase_price=94000000,
        machine_life_hours=5000,
    )
    assert result["power_cost"] == 0.0
    assert result["downtime_cost"] == 0.0
    assert result["maintenance_cost"] == 0.0
    assert result["material_cost"] > 0
