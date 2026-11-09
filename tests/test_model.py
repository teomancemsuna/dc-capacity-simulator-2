"""
Tests for the calculation engine. Run with:  pytest

Each test builds a tiny one-site dataset with round numbers so the expected
answer can be checked by hand.
"""

import math

import pandas as pd
import pytest

from core.model import (
    Assumptions, earliest_constraint, forecast, portfolio_series,
    site_risk_table, site_summary, validate_sites,
)


def make_site(**overrides) -> pd.DataFrame:
    base = dict(site_id="T1", site_name="Test", region="X",
                power_capacity_mw=10.0, power_demand_mw=5.0,
                cooling_capacity_kw=10000, cooling_load_kw=5000,
                rack_capacity=100, racks_occupied=50,
                annual_growth_pct=0.0,
                expansion_power_mw=0.0, expansion_cooling_kw=0, expansion_racks=0,
                expansion_month=0)
    base.update(overrides)
    return pd.DataFrame([base])


def power(fc, month):
    return fc[(fc.resource == "power") & (fc.month == month)].iloc[0]


def test_compound_growth_formula():
    fc = forecast(make_site(annual_growth_pct=10.0), Assumptions())
    assert power(fc, 12).demand == pytest.approx(5.5)          # 5 x 1.10
    assert power(fc, 24).demand == pytest.approx(6.05)         # 5 x 1.10^2
    assert power(fc, 6).demand == pytest.approx(5 * math.sqrt(1.1))


def test_utilization_and_headroom():
    fc = forecast(make_site(), Assumptions())
    row = power(fc, 0)
    assert row.utilization == pytest.approx(0.5)
    assert row.headroom == pytest.approx(5.0)


def test_baseline_is_actual_and_rest_is_projection():
    fc = forecast(make_site(), Assumptions())
    assert not power(fc, 0).is_projection
    assert power(fc, 1).is_projection


def test_growth_override_replaces_site_growth():
    fc = forecast(make_site(annual_growth_pct=5.0), Assumptions(growth_override_pct=25.0))
    assert power(fc, 12).demand == pytest.approx(6.25)


def test_efficiency_reduces_projection_but_not_baseline_or_racks():
    fc = forecast(make_site(), Assumptions(efficiency_pct=10.0))
    assert power(fc, 0).demand == pytest.approx(5.0)
    assert power(fc, 12).demand == pytest.approx(4.5)
    racks = fc[(fc.resource == "racks") & (fc.month == 12)].iloc[0]
    assert racks.demand == pytest.approx(50)


def test_expansion_activates_on_its_month():
    site = make_site(expansion_power_mw=5.0, expansion_month=6)
    fc = forecast(site, Assumptions())
    assert power(fc, 5).capacity == pytest.approx(10.0)
    assert power(fc, 6).capacity == pytest.approx(15.0)
    fc_off = forecast(site, Assumptions(include_expansions=False))
    assert power(fc_off, 6).capacity == pytest.approx(10.0)


def test_exhaustion_month_is_first_month_demand_exceeds_capacity():
    # 8 MW growing 25%/yr passes 10 MW when 1.25^(m/12) > 1.25  ->  month 13
    site = make_site(power_demand_mw=8.0, annual_growth_pct=25.0)
    a = Assumptions()
    summ = site_summary(forecast(site, a), a)
    p = summ[summ.resource == "power"].iloc[0]
    assert p.exhaustion_month == 13
    assert p.threshold_month < p.exhaustion_month


def test_risk_levels():
    a = Assumptions()
    def risk_of(**kw):
        return site_risk_table(site_summary(forecast(make_site(**kw), a), a)).risk.iloc[0]
    assert risk_of() == "Low"
    assert risk_of(power_demand_mw=9.0, annual_growth_pct=20.0) == "Critical"   # runs out in < 12 months
    assert risk_of(power_demand_mw=8.0, annual_growth_pct=8.0) == "High"        # crosses 85% within 12 months
    assert risk_of(power_demand_mw=6.0, annual_growth_pct=15.0) == "Medium"     # crosses 85% after 12 months


def test_first_limiting_resource_is_the_earliest_one():
    # Cooling is already at 90%, power only 50% -> cooling is the limit
    site = make_site(cooling_load_kw=9000)
    a = Assumptions()
    r = site_risk_table(site_summary(forecast(site, a), a)).iloc[0]
    assert r.limiting_resource == "cooling"


def test_portfolio_average_does_not_hide_site_constraint():
    # One site at 95% power, one at 20%: portfolio is only ~58% but the
    # earliest constraint must still point at the full site.
    sites = pd.concat([
        make_site(site_id="A", power_demand_mw=9.5),
        make_site(site_id="B", power_demand_mw=2.0),
    ], ignore_index=True)
    a = Assumptions()
    fc = forecast(sites, a)
    p = portfolio_series(fc)
    assert p[(p.resource == "power") & (p.month == 0)].utilization.iloc[0] == pytest.approx(0.575)
    e = earliest_constraint(site_summary(fc, a))
    assert e["site_id"] == "A" and e["resource"] == "power" and e["month"] == 0


def test_validation_rejects_negative_and_inconsistent_inputs():
    assert validate_sites(make_site()) == []
    assert any("Negative" in e for e in validate_sites(make_site(power_demand_mw=-1)))
    assert any("exceeds capacity" in e for e in validate_sites(make_site(racks_occupied=150)))
    assert any("greater than zero" in e for e in validate_sites(make_site(rack_capacity=0, racks_occupied=0)))


# --------------------------------------------------------------------------- #
# Stranded capacity and forecast range
# --------------------------------------------------------------------------- #
from core.model import exhaustion_ranges, portfolio_band, stranded_capacity  # noqa: E402


def test_stranded_power_when_racks_run_out_first():
    # Power can grow 2.0x (10/5) but racks only 1.25x (100/80): racks bind.
    site = make_site(racks_occupied=80)
    r = stranded_capacity(site).iloc[0]
    assert r.binding_resource == "racks"
    assert r.stranded_power_mw == pytest.approx(10 - 5 * 1.25)      # 3.75 MW stranded
    assert r.unlock_racks == 60                                      # 80 x 2.0 - 100
    assert r.stranded_racks == pytest.approx(0)


def test_no_stranded_power_when_power_is_binding():
    site = make_site(power_demand_mw=8.0)
    r = stranded_capacity(site).iloc[0]
    assert r.binding_resource == "power"
    assert r.stranded_power_mw == pytest.approx(0)
    assert r.unlock_racks == 0 and r.unlock_cooling_kw == 0


def test_forecast_range_brackets_the_base_case():
    site = make_site(power_demand_mw=8.0, annual_growth_pct=15.0)
    a = Assumptions(growth_uncertainty_pp=5.0)
    base = site_risk_table(site_summary(forecast(site, a), a)).iloc[0]
    rng = exhaustion_ranges(site, a).iloc[0]
    assert rng.exh_early <= base.exhaustion_month <= rng.exh_late
    band = portfolio_band(site, a)
    p36 = band[(band.resource == "power") & (band.month == 36)].iloc[0]
    assert p36.demand_low < power(forecast(site, a), 36).demand < p36.demand_high
