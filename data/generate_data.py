"""
Generate the six-site synthetic dataset (data/sites.csv).

All values are invented for demonstration purposes. They are hand-tuned so the
portfolio tells a realistic story: one site is already over its rack-space threshold,
one is close to its power limit, one is limited by cooling, and three have comfortable headroom.

Run:  python data/generate_data.py
"""

from pathlib import Path

import pandas as pd

# Units
#   Power:   MW of IT/electrical capacity and demand
#   Cooling: kW of heat-rejection capacity and load
#   Racks:   number of rack positions
#   Growth:  % per year (compound)
#   Expansion month: months after the baseline date when added capacity goes live
SITES = [
    dict(site_id="DC1", site_name="Northwind Campus", region="US-East",
         power_capacity_mw=24.0, power_demand_mw=17.5,
         cooling_capacity_kw=30000, cooling_load_kw=22000,
         rack_capacity=2400, racks_occupied=1850,
         annual_growth_pct=12.0,
         expansion_power_mw=6.0, expansion_cooling_kw=7000, expansion_racks=600,
         expansion_month=18),
    dict(site_id="DC2", site_name="Silver Lake", region="US-Central",
         power_capacity_mw=18.0, power_demand_mw=14.9,
         cooling_capacity_kw=22000, cooling_load_kw=18000,
         rack_capacity=1800, racks_occupied=1420,
         annual_growth_pct=15.0,
         expansion_power_mw=4.0, expansion_cooling_kw=5000, expansion_racks=400,
         expansion_month=12),
    dict(site_id="DC3", site_name="Red Mesa", region="US-West",
         power_capacity_mw=12.0, power_demand_mw=8.1,
         cooling_capacity_kw=14000, cooling_load_kw=11400,
         rack_capacity=1200, racks_occupied=780,
         annual_growth_pct=10.0,
         expansion_power_mw=0.0, expansion_cooling_kw=3000, expansion_racks=0,
         expansion_month=9),
    dict(site_id="DC4", site_name="Harbor Point", region="US-East",
         power_capacity_mw=30.0, power_demand_mw=16.2,
         cooling_capacity_kw=36000, cooling_load_kw=19500,
         rack_capacity=3000, racks_occupied=1500,
         annual_growth_pct=8.0,
         expansion_power_mw=0.0, expansion_cooling_kw=0, expansion_racks=0,
         expansion_month=0),
    dict(site_id="DC5", site_name="Granite Falls", region="US-Central",
         power_capacity_mw=10.0, power_demand_mw=7.6,
         cooling_capacity_kw=12500, cooling_load_kw=9300,
         rack_capacity=1000, racks_occupied=880,
         annual_growth_pct=18.0,
         expansion_power_mw=2.0, expansion_cooling_kw=2500, expansion_racks=300,
         expansion_month=15),
    dict(site_id="DC6", site_name="Pine Valley", region="US-West",
         power_capacity_mw=20.0, power_demand_mw=11.0,
         cooling_capacity_kw=25000, cooling_load_kw=13600,
         rack_capacity=2000, racks_occupied=1100,
         annual_growth_pct=9.0,
         expansion_power_mw=0.0, expansion_cooling_kw=0, expansion_racks=0,
         expansion_month=0),
]


def build_dataframe() -> pd.DataFrame:
    return pd.DataFrame(SITES)


if __name__ == "__main__":
    out = Path(__file__).parent / "sites.csv"
    build_dataframe().to_csv(out, index=False)
    print(f"Wrote {out}")
