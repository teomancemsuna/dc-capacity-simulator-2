"""
Capacity forecasting and risk engine.

This module has NO Streamlit code in it. It takes a sites DataFrame plus a set of
scenario assumptions and returns plain DataFrames. Keeping the math separate from
the UI makes it easy to test (see tests/) and guarantees every page of the app
uses the exact same numbers.

Core formulas (from the SOW):
    Utilization     = Demand / Capacity
    Headroom        = Capacity - Demand
    Forecast demand = Baseline demand x (1 + annual growth) ^ (months / 12)
    Exhaustion      = first month where demand > capacity
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

# The model always forecasts the full 36 months so that risk ratings do not
# change when the user only looks at a shorter horizon.
MAX_HORIZON = 36
HORIZON_OPTIONS = [6, 12, 18, 24, 30, 36]
BASELINE_DATE = pd.Timestamp("2026-11-01")

# resource key -> (capacity column, demand column, expansion column, unit, label)
RESOURCES = {
    "power": ("power_capacity_mw", "power_demand_mw", "expansion_power_mw", "MW", "Power"),
    "cooling": ("cooling_capacity_kw", "cooling_load_kw", "expansion_cooling_kw", "kW", "Cooling"),
    "racks": ("rack_capacity", "racks_occupied", "expansion_racks", "racks", "Rack space"),
}

# Efficiency improvements reduce energy-related demand only. Rack count is a
# physical footprint and is not affected by efficiency.
EFFICIENCY_APPLIES_TO = {"power", "cooling"}

RISK_ORDER = ["Low", "Medium", "High", "Critical"]


@dataclass(frozen=True)
class Assumptions:
    """Everything a scenario can change. Defaults = the Baseline scenario."""
    horizon_months: int = 24
    growth_override_pct: float | None = None   # None = use each site's own growth
    efficiency_pct: float = 0.0                # % reduction of projected power/cooling demand
    threshold_pct: float = 85.0                # utilization that counts as "constrained"
    include_expansions: bool = True
    growth_uncertainty_pp: float = 3.0         # +/- percentage points for the forecast range
    growth_shift_pp: float = 0.0               # internal: applied when building the low/high range


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def month_label(month: int | None) -> str:
    """Convert a month offset (0 = baseline) into 'Mon YYYY'."""
    if month is None:
        return "Beyond 36 mo"
    return (BASELINE_DATE + pd.DateOffset(months=int(month))).strftime("%b %Y")


def validate_sites(sites: pd.DataFrame) -> list[str]:
    """Return a list of human-readable problems. Empty list = data is valid."""
    errors = []
    numeric_cols = [c for c in sites.columns if c not in ("site_id", "site_name", "region")]
    for col in numeric_cols:
        bad = sites.loc[sites[col] < 0, "site_id"].tolist()
        if bad:
            errors.append(f"Negative values in '{col}' for {', '.join(bad)}.")
    for key, (cap, dem, _, unit, label) in RESOURCES.items():
        zero = sites.loc[sites[cap] <= 0, "site_id"].tolist()
        if zero:
            errors.append(f"{label} capacity must be greater than zero ({', '.join(zero)}).")
        over = sites.loc[sites[dem] > sites[cap], "site_id"].tolist()
        if over:
            errors.append(f"Current {label.lower()} demand exceeds capacity at {', '.join(over)}.")
    return errors


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
def forecast(sites: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """
    Monthly forecast for every site x resource, months 0..36.

    Returns a long table with one row per (site, resource, month):
        site_id, site_name, resource, month, demand, capacity, utilization, is_projection
    Month 0 is the actual (synthetic) baseline; months 1+ are projections.
    """
    months = np.arange(0, MAX_HORIZON + 1)
    rows = []
    for _, s in sites.iterrows():
        growth = ((a.growth_override_pct if a.growth_override_pct is not None
                   else s["annual_growth_pct"]) + a.growth_shift_pp) / 100.0
        growth_factor = (1 + growth) ** (months / 12)

        for key, (cap_col, dem_col, exp_col, _, _) in RESOURCES.items():
            demand = s[dem_col] * growth_factor
            if key in EFFICIENCY_APPLIES_TO and a.efficiency_pct:
                # Only projections are reduced; the baseline stays the actual value.
                demand[1:] = demand[1:] * (1 - a.efficiency_pct / 100.0)

            capacity = np.full(months.shape, float(s[cap_col]))
            if a.include_expansions and s[exp_col] > 0:
                capacity[months >= s["expansion_month"]] += s[exp_col]

            rows.append(pd.DataFrame({
                "site_id": s["site_id"],
                "site_name": s["site_name"],
                "resource": key,
                "month": months,
                "demand": demand,
                "capacity": capacity,
            }))

    fc = pd.concat(rows, ignore_index=True)
    fc["utilization"] = fc["demand"] / fc["capacity"]
    fc["headroom"] = fc["capacity"] - fc["demand"]
    fc["is_projection"] = fc["month"] > 0
    return fc


def _first_month(mask: pd.Series, months: pd.Series) -> int | None:
    hits = months[mask]
    return int(hits.iloc[0]) if len(hits) else None


def site_summary(fc: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """
    One row per site x resource with the numbers the dashboard needs:
    current/horizon utilization, first threshold month, exhaustion month.
    """
    thr = a.threshold_pct / 100.0
    out = []
    for (site_id, resource), g in fc.groupby(["site_id", "resource"], sort=False):
        g = g.sort_values("month")
        now = g.iloc[0]
        at_h = g[g["month"] == a.horizon_months].iloc[0]
        out.append({
            "site_id": site_id,
            "site_name": now["site_name"],
            "resource": resource,
            "util_now": now["utilization"],
            "util_horizon": at_h["utilization"],
            "headroom_now": now["headroom"],
            "headroom_horizon": at_h["headroom"],
            "threshold_month": _first_month(g["utilization"] >= thr, g["month"]),
            "exhaustion_month": _first_month(g["demand"] > g["capacity"], g["month"]),
        })
    df = pd.DataFrame(out)
    return df.astype({"threshold_month": "Int64", "exhaustion_month": "Int64"})


def _risk(threshold_month, exhaustion_month) -> str:
    """
    Deterministic risk rules (always judged on the full 36-month forecast):
        Critical - a resource runs out (demand > capacity) within 12 months
        High     - a resource crosses the utilization threshold within 12 months
        Medium   - a resource crosses the threshold within 36 months
        Low      - no threshold crossing in the next 36 months
    """
    if exhaustion_month is not None and exhaustion_month <= 12:
        return "Critical"
    if threshold_month is not None and threshold_month <= 12:
        return "High"
    if threshold_month is not None:
        return "Medium"
    return "Low"


def site_risk_table(summary: pd.DataFrame) -> pd.DataFrame:
    """One row per site: worst resource, its timing, and the overall risk level."""
    rows = []
    for site_id, g in summary.groupby("site_id", sort=False):
        # The limiting resource is the one that hits the threshold first.
        # If none does, it is the one with the highest utilization today.
        g = g.assign(_sort=g["threshold_month"].astype("float").fillna(np.inf))
        lim = g.sort_values(["_sort", "util_now"], ascending=[True, False]).iloc[0]

        thr_months = g["threshold_month"].dropna()
        exh_months = g["exhaustion_month"].dropna()
        first_thr = int(thr_months.min()) if len(thr_months) else None
        first_exh = int(exh_months.min()) if len(exh_months) else None

        rows.append({
            "site_id": site_id,
            "site_name": lim["site_name"],
            "limiting_resource": lim["resource"],
            "threshold_month": first_thr,
            "exhaustion_month": first_exh,
            "risk": _risk(first_thr, first_exh),
            **{f"util_now_{r}": g.loc[g["resource"] == r, "util_now"].iloc[0] for r in RESOURCES},
            **{f"util_horizon_{r}": g.loc[g["resource"] == r, "util_horizon"].iloc[0] for r in RESOURCES},
        })
    df = pd.DataFrame(rows)
    return df.astype({"threshold_month": "Int64", "exhaustion_month": "Int64"})


def portfolio_series(fc: pd.DataFrame) -> pd.DataFrame:
    """Portfolio totals per month and resource. Portfolio utilization = sum(demand) / sum(capacity)."""
    p = fc.groupby(["resource", "month"], as_index=False)[["demand", "capacity"]].sum()
    p["utilization"] = p["demand"] / p["capacity"]
    return p


def earliest_constraint(summary: pd.DataFrame) -> dict | None:
    """
    The single earliest site-level threshold crossing across the whole portfolio.
    This is shown prominently so a healthy portfolio average cannot hide it.
    """
    hits = summary.dropna(subset=["threshold_month"])
    if hits.empty:
        return None
    row = hits.sort_values(["threshold_month", "util_now"], ascending=[True, False]).iloc[0]
    return {
        "site_id": row["site_id"],
        "site_name": row["site_name"],
        "resource": row["resource"],
        "month": int(row["threshold_month"]),
        "date": month_label(row["threshold_month"]),
        "util_now": float(row["util_now"]),
    }


# --------------------------------------------------------------------------- #
# Executive insights (rules-based, every line cites the metric behind it)
# --------------------------------------------------------------------------- #
def insights(sites: pd.DataFrame, risk: pd.DataFrame, portfolio: pd.DataFrame,
             earliest: dict | None, a: Assumptions,
             stranded: pd.DataFrame | None = None) -> list[tuple[str, str]]:
    """Return a list of (severity, message) pairs, most urgent first."""
    msgs: list[tuple[str, str]] = []
    label = {k: v[4] for k, v in RESOURCES.items()}

    if earliest:
        p_now = portfolio[(portfolio["resource"] == earliest["resource"]) &
                          (portfolio["month"] == 0)]["utilization"].iloc[0]
        when = "is already above" if earliest["month"] == 0 else f"crosses in {earliest['date']} (month {earliest['month']})"
        msgs.append(("critical" if earliest["month"] <= 6 else "warning",
                     f"**{earliest['site_id']} {earliest['site_name']}** {label[earliest['resource']].lower()} "
                     f"{when} the {a.threshold_pct:.0f}% threshold, while portfolio "
                     f"{label[earliest['resource']].lower()} utilization is {p_now:.0%}. "
                     f"The portfolio average hides this site-level constraint."))

    by_id = sites.set_index("site_id")
    for _, r in risk.iterrows():
        s = by_id.loc[r["site_id"]]
        exp_col = RESOURCES[r["limiting_resource"]][2]
        has_exp = a.include_expansions and s[exp_col] > 0
        if pd.notna(r["exhaustion_month"]) and has_exp and s["expansion_month"] > r["exhaustion_month"]:
            gap = int(s["expansion_month"] - r["exhaustion_month"])
            msgs.append(("critical",
                         f"**{r['site_id']}** runs out of {label[r['limiting_resource']].lower()} in "
                         f"{month_label(r['exhaustion_month'])}, but its planned expansion goes live in "
                         f"{month_label(s['expansion_month'])} ({gap} month{'s' if gap != 1 else ''} later). "
                         f"Pull the expansion forward."))
        elif r["risk"] in ("Critical", "High") and not has_exp:
            msgs.append(("warning",
                         f"**{r['site_id']}** is {r['risk']} risk ({label[r['limiting_resource']].lower()} "
                         f"limited) and has no planned {label[r['limiting_resource']].lower()} expansion."))

    if stranded is not None and stranded["stranded_power_mw"].sum() >= 0.5:
        top = stranded[stranded["stranded_power_mw"] >= 0.1].sort_values("stranded_power_mw", ascending=False)
        parts = ", ".join(f"{r.site_id} {r.stranded_power_mw:.1f} MW" for r in top.itertuples())
        fixes = []
        if top["unlock_racks"].sum() > 0:
            fixes.append(f"~{top['unlock_racks'].sum():,.0f} racks")
        if top["unlock_cooling_kw"].sum() > 0:
            fixes.append(f"~{top['unlock_cooling_kw'].sum():,.0f} kW of cooling")
        msgs.append(("warning",
                     f"**{stranded['stranded_power_mw'].sum():.1f} MW of installed power is stranded** "
                     f"because cooling or rack space runs out first ({parts}). Adding "
                     f"{' and '.join(fixes)} unlocks it without buying new electrical capacity."))

    low = risk[risk["risk"] == "Low"].sort_values("util_horizon_power")
    if not low.empty:
        best = low.iloc[0]
        msgs.append(("info",
                     f"**{best['site_id']} {best['site_name']}** stays below the threshold for 36 months "
                     f"({best['util_horizon_power']:.0%} power utilization at month {a.horizon_months}). "
                     f"It is the best candidate to absorb workloads from constrained sites."))
    return msgs


# --------------------------------------------------------------------------- #
# Forecast range (growth uncertainty)
# --------------------------------------------------------------------------- #
def exhaustion_ranges(sites: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """
    Re-run the forecast with growth -/+ the uncertainty band and report, per site,
    the earliest and latest threshold / exhaustion month. Executives plan against
    a window ("between Jun and Dec 2027"), not a single date.
    """
    u = a.growth_uncertainty_pp
    out = {}
    for tag, shift in (("early", +u), ("late", -u)):
        b = replace(a, growth_shift_pp=shift)
        r = site_risk_table(site_summary(forecast(sites, b), b)).set_index("site_id")
        out[f"thr_{tag}"] = r["threshold_month"]
        out[f"exh_{tag}"] = r["exhaustion_month"]
    return pd.DataFrame(out).reset_index()


def portfolio_band(sites: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """Portfolio demand per month and resource under low and high growth."""
    u = a.growth_uncertainty_pp
    lo = portfolio_series(forecast(sites, replace(a, growth_shift_pp=-u)))
    hi = portfolio_series(forecast(sites, replace(a, growth_shift_pp=+u)))
    return lo[["resource", "month"]].assign(demand_low=lo["demand"], demand_high=hi["demand"])


# --------------------------------------------------------------------------- #
# Stranded capacity
# --------------------------------------------------------------------------- #
def stranded_capacity(sites: pd.DataFrame) -> pd.DataFrame:
    """
    Stranded capacity = installed capacity that cannot be used because a
    different resource at the same site runs out first.

    Demand for power, cooling and racks grows together, so each resource can
    support (capacity / demand) times today's load. The smallest of those
    ratios is the site's real growth limit (the binding resource). Anything
    above that limit in the other resources is stranded:

        stranded_r = capacity_r - demand_r x min_ratio

    The 'unlock' columns show how much of the binding resource(s) would need to
    be added so that all installed POWER can be used, since power is usually the
    most expensive resource to add. Calculated on today's installed capacity.
    """
    rows = []
    for _, s in sites.iterrows():
        ratio = {k: (s[cap] / s[dem] if s[dem] > 0 else np.inf)
                 for k, (cap, dem, *_rest) in RESOURCES.items()}
        binding = min(ratio, key=ratio.get)
        m = ratio[binding]
        m_power = ratio["power"]
        row = {
            "site_id": s["site_id"],
            "site_name": s["site_name"],
            "binding_resource": binding,
            "supportable_growth_pct": (m - 1) * 100,
            "power_demand_mw": s["power_demand_mw"],
            "power_capacity_mw": s["power_capacity_mw"],
            "power_usable_mw": min(s["power_capacity_mw"], s["power_demand_mw"] * m),
        }
        for k, (cap, dem, *_rest) in RESOURCES.items():
            unit_key = {"power": "stranded_power_mw", "cooling": "stranded_cooling_kw",
                        "racks": "stranded_racks"}[k]
            row[unit_key] = max(0.0, s[cap] - s[dem] * m)
        row["unlock_cooling_kw"] = max(0.0, s["cooling_load_kw"] * m_power - s["cooling_capacity_kw"])
        row["unlock_racks"] = max(0.0, np.ceil(s["racks_occupied"] * m_power - s["rack_capacity"]))
        rows.append(row)
    return pd.DataFrame(rows)
