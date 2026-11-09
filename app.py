"""
Six-Site Data Center Capacity Planning Simulator — Executive Overview (prototype).

HOW STREAMLIT WORKS (the one idea to remember):
    Streamlit runs this whole file from top to bottom every time the user touches
    a widget. There are no callbacks wiring charts to sliders: the slider's new
    value is simply read on the next run, the numbers are recalculated, and the
    page is redrawn. `st.session_state` is the only thing that survives between
    runs, so scenario settings live there.

Run locally:  streamlit run app.py
"""

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.model import (
    BASELINE_DATE, HORIZON_OPTIONS, RESOURCES, Assumptions, earliest_constraint,
    exhaustion_ranges, forecast, insights, month_label, portfolio_band, portfolio_series,
    site_risk_table, site_summary, stranded_capacity, validate_sites,
)

DATA_PATH = Path(__file__).parent / "data" / "sites.csv"

# Status colors used everywhere (blue / green / amber / red, as the brief asks)
COLORS = {
    "Low": "#22C55E", "Medium": "#F59E0B", "High": "#F97316", "Critical": "#EF4444",
    "info": "#3B82F6", "warning": "#F59E0B", "critical": "#EF4444",
}
RESOURCE_COLORS = {"power": "#3B82F6", "cooling": "#22D3EE", "racks": "#A78BFA"}

# --------------------------------------------------------------------------- #
# 1. Page setup and styling
# --------------------------------------------------------------------------- #
# set_page_config must be the first Streamlit call. "wide" uses the full browser width.
st.set_page_config(page_title="DC Capacity Planner", layout="wide")

# Streamlit has no built-in "KPI card" widget, so we add a little CSS and
# render the cards as HTML with st.markdown(..., unsafe_allow_html=True).
st.markdown("""
<style>
.block-container {padding-top: 2rem; padding-bottom: 2rem;}
.kpi {background:#121F38; border:1px solid #1F3157; border-radius:12px; padding:14px 16px; height:100%;}
.kpi .label {color:#8FA3C2; font-size:0.78rem; text-transform:uppercase; letter-spacing:.06em;}
.kpi .value {color:#F3F6FB; font-size:1.65rem; font-weight:650; margin-top:4px;}
.kpi .sub {color:#8FA3C2; font-size:0.82rem; margin-top:2px;}
.badge {display:inline-block; white-space:nowrap; padding:3px 10px; border-radius:999px; font-size:0.75rem;
        font-weight:600; letter-spacing:.04em; background:#3A2A0B; color:#F59E0B; border:1px solid #6B4E12;}
.alert {background:#2A1215; border:1px solid #7F1D1D; border-left:5px solid #EF4444;
        border-radius:10px; padding:14px 18px; margin:6px 0 18px 0; color:#F3F6FB;}
.alert .t {color:#FCA5A5; font-size:0.75rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700;}
.insight {background:#121F38; border:1px solid #1F3157; border-radius:10px;
          padding:10px 14px; margin-bottom:10px; font-size:0.9rem; color:#D7DFEC;}
.section {color:#8FA3C2; font-size:0.8rem; text-transform:uppercase; letter-spacing:.08em;
          font-weight:700; margin:18px 0 8px 0;}
</style>
""", unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", accent: str | None = None) -> str:
    border = f"border-top:3px solid {accent or 'transparent'};"
    return (f'<div class="kpi" style="{border}"><div class="label">{label}</div>'
            f'<div class="value">{value}</div><div class="sub">{sub}</div></div>')


def md_bold_to_html(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def fmt_range(early, late) -> str:
    """'Aug 2027 – Oct 2027' label for the exhaustion window under low/high growth."""
    if pd.isna(early):
        return "—"
    return f"{month_label(early)} – {month_label(late) if pd.notna(late) else 'later'}"


# --------------------------------------------------------------------------- #
# 2. Data loading
# --------------------------------------------------------------------------- #
# @st.cache_data stores the result after the first run. Because the whole script
# reruns on every click, caching stops us from re-reading the CSV each time.
@st.cache_data
def load_sites() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


sites = load_sites()

# --------------------------------------------------------------------------- #
# 3. Scenario state (session_state)
# --------------------------------------------------------------------------- #
# Every sidebar widget gets a `key`. Streamlit then stores its value in
# st.session_state[key]. A preset button just overwrites those keys.
DEFAULTS = dict(horizon=24, growth_on=False, growth=12.0, efficiency=0.0,
                threshold=85, expansions=True, uncertainty=3.0)
PRESETS = {
    "Baseline": {},
    "High Growth": dict(growth_on=True, growth=25.0),
    "Efficiency": dict(efficiency=10.0),
}

for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)
st.session_state.setdefault("scenario", "Baseline")


def apply_preset(name: str) -> None:
    # Callbacks run BEFORE the script reruns, which is why changing widget
    # values here is allowed (changing them later in the script is not).
    st.session_state.update({**DEFAULTS, **PRESETS[name]})
    st.session_state.scenario = name


def mark_custom() -> None:
    st.session_state.scenario = "Custom"


# --------------------------------------------------------------------------- #
# 4. Sidebar controls
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### Scenario planning")
    st.caption(f"Active scenario: **{st.session_state.scenario}**")

    st.button("Baseline — current assumptions", on_click=apply_preset, args=("Baseline",), width="stretch")
    st.button("High growth — 25% per year", on_click=apply_preset, args=("High Growth",), width="stretch")
    st.button("Efficiency — 10% lower demand", on_click=apply_preset, args=("Efficiency",), width="stretch")

    st.divider()
    st.select_slider("Forecast horizon (months)", options=HORIZON_OPTIONS,
                     key="horizon", on_change=mark_custom)
    st.toggle("Override site-specific growth", key="growth_on", on_change=mark_custom)
    st.slider("Portfolio annual growth (%)", 0.0, 40.0, step=0.5, key="growth",
              disabled=not st.session_state.growth_on, on_change=mark_custom,
              help="Used for every site when the override is on.")
    st.slider("Efficiency improvement (%)", 0.0, 30.0, step=1.0, key="efficiency",
              on_change=mark_custom,
              help="Reduces projected power and cooling demand. Rack count is unchanged.")
    st.slider("Constraint threshold (% utilization)", 60, 100, step=1, key="threshold",
              on_change=mark_custom)
    st.toggle("Include planned expansions", key="expansions", on_change=mark_custom)
    st.slider("Growth uncertainty (± percentage points)", 0.0, 10.0, step=0.5, key="uncertainty",
              on_change=mark_custom,
              help="Shows a low/high range around the forecast and exhaustion dates.")

    st.button("Reset to baseline", on_click=apply_preset, args=("Baseline",),
              type="primary", width="stretch")
    st.divider()
    st.caption("Synthetic data — demonstration only. No real facility information.")

# Turn the widget values into one immutable Assumptions object for the model.
ss = st.session_state
a = Assumptions(
    horizon_months=ss.horizon,
    growth_override_pct=ss.growth if ss.growth_on else None,
    efficiency_pct=ss.efficiency,
    threshold_pct=float(ss.threshold),
    include_expansions=ss.expansions,
    growth_uncertainty_pp=ss.uncertainty,
)

# --------------------------------------------------------------------------- #
# 5. Run the model (pure Python, no Streamlit inside)
# --------------------------------------------------------------------------- #
errors = validate_sites(sites)
if errors:
    for e in errors:
        st.error(e)
    st.stop()   # nothing below runs if the data is invalid

fc = forecast(sites, a)
summary = site_summary(fc, a)
risk = site_risk_table(summary)
portfolio = portfolio_series(fc)
earliest = earliest_constraint(summary)
stranded = stranded_capacity(sites)
ranges = exhaustion_ranges(sites, a).set_index("site_id")
band = portfolio_band(sites, a)
notes = insights(sites, risk, portfolio, earliest, a, stranded)

h = a.horizon_months


def port(resource: str, month: int) -> pd.Series:
    return portfolio[(portfolio.resource == resource) & (portfolio.month == month)].iloc[0]


# --------------------------------------------------------------------------- #
# 6. Header + earliest constraint banner
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 1])
left.markdown("## Six-Site Capacity Planning — Executive Overview")
left.caption(f"Baseline {month_label(0)} · Forecast horizon {h} months ({month_label(h)}) · "
             f"Scenario: {ss.scenario}")
right.markdown('<div style="text-align:right;margin-top:18px">'
               '<span class="badge">SYNTHETIC DATA — DEMONSTRATION ONLY</span></div>',
               unsafe_allow_html=True)

if earliest:
    label = RESOURCES[earliest["resource"]][4].lower()
    when = ("is already above" if earliest["month"] == 0
            else f"crosses in <b>{earliest['date']}</b> (month {earliest['month']}) —")
    st.markdown(
        f'<div class="alert"><div class="t">Earliest site-level constraint</div>'
        f'<b>{earliest["site_id"]} {earliest["site_name"]}</b> — {label} {when} '
        f'the {a.threshold_pct:.0f}% threshold (today {earliest["util_now"]:.0%} utilized).</div>',
        unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# 7. KPI cards
# --------------------------------------------------------------------------- #
p_now, p_h = port("power", 0), port("power", h)
c_now, r_now = port("cooling", 0), port("racks", 0)
at_risk = risk[risk.risk.isin(["High", "Critical"])]
util_color = COLORS["Critical"] if p_now.utilization >= a.threshold_pct / 100 else COLORS["info"]

exh = risk.dropna(subset=["exhaustion_month"]).sort_values("exhaustion_month")
if len(exh):
    e = exh.iloc[0]
    exh_value = month_label(e.exhaustion_month)
    rg = ranges.loc[e.site_id]
    exh_sub = (f"{e.site_id} · {RESOURCES[e.limiting_resource][4].lower()} · "
               f"range {month_label(rg.exh_early)} – {month_label(rg.exh_late)}")
else:
    exh_value, exh_sub = "None", "within 36 months"

row1 = st.columns(6)
row1[0].markdown(kpi("Power capacity", f"{p_now.capacity:.1f} MW", "6 sites, installed"), unsafe_allow_html=True)
row1[1].markdown(kpi("Current demand", f"{p_now.demand:.1f} MW", "actual baseline"), unsafe_allow_html=True)
row1[2].markdown(kpi("Power utilization", f"{p_now.utilization:.0%}", "portfolio average", util_color), unsafe_allow_html=True)
row1[3].markdown(kpi("Headroom", f"{p_now.capacity - p_now.demand:.1f} MW", "capacity − demand"), unsafe_allow_html=True)
row1[4].markdown(kpi(f"Demand at {h} mo", f"{p_h.demand:.1f} MW", f"{p_h.utilization:.0%} of {p_h.capacity:.1f} MW"), unsafe_allow_html=True)
row1[5].markdown(kpi("Sites at risk", f"{len(at_risk)} of 6", ", ".join(at_risk.site_id) or "none",
                     COLORS["High"] if len(at_risk) else COLORS["Low"]), unsafe_allow_html=True)

st.write("")
row2 = st.columns(5)
f12, f24, f36 = (port("power", m).demand for m in (12, 24, 36))
row2[0].markdown(kpi("Cooling utilization", f"{c_now.utilization:.0%}",
                     f"{c_now.demand:,.0f} of {c_now.capacity:,.0f} kW"), unsafe_allow_html=True)
row2[1].markdown(kpi("Rack occupancy", f"{r_now.utilization:.0%}",
                     f"{r_now.demand:,.0f} of {r_now.capacity:,.0f} racks"), unsafe_allow_html=True)
row2[2].markdown(kpi("Power forecast (MW)", f"{f12:.0f} · {f24:.0f} · {f36:.0f}",
                     "at 12 · 24 · 36 months"), unsafe_allow_html=True)
row2[3].markdown(kpi("Earliest exhaustion", exh_value, exh_sub,
                     COLORS["Critical"] if len(exh) else COLORS["Low"]), unsafe_allow_html=True)
stranded_mw = stranded.stranded_power_mw.sum()
row2[4].markdown(kpi("Stranded power", f"{stranded_mw:.1f} MW",
                     "installed but blocked by cooling / racks",
                     COLORS["warning"] if stranded_mw >= 0.5 else COLORS["Low"]), unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# 8. Charts (Plotly)
# --------------------------------------------------------------------------- #
# Plotly builds a figure object; we add "traces" (lines, bars) to it, style the
# layout, then hand it to st.plotly_chart which renders it interactively.
def style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
        font=dict(color="#C9D4E5"),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#1F3157")
    fig.update_yaxes(gridcolor="#1F3157")
    return fig


chart_col, insight_col = st.columns([2, 1], gap="large")

with chart_col:
    st.markdown('<div class="section">Portfolio demand vs capacity</div>', unsafe_allow_html=True)
    res = st.radio("Resource", list(RESOURCES), horizontal=True, label_visibility="collapsed",
                   format_func=lambda r: RESOURCES[r][4])
    unit = RESOURCES[res][3]
    p = portfolio[(portfolio.resource == res) & (portfolio.month <= h)].copy()
    p["date"] = [BASELINE_DATE + pd.DateOffset(months=int(m)) for m in p.month]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p.date, y=p.capacity, name="Capacity", line=dict(color="#94A3B8", width=2, shape="hv")))
    fig.add_trace(go.Scatter(x=p.date, y=p.capacity * a.threshold_pct / 100, name=f"{a.threshold_pct:.0f}% threshold",
                             line=dict(color=COLORS["warning"], width=1.5, dash="dot", shape="hv")))
    b = band[(band.resource == res) & (band.month <= h)]
    fig.add_trace(go.Scatter(x=p.date, y=b.demand_high, line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=p.date, y=b.demand_low, line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(59,130,246,0.15)", hoverinfo="skip",
                             name=f"±{a.growth_uncertainty_pp:g} pp growth range"))
    fig.add_trace(go.Scatter(x=p.date, y=p.demand, name="Projected demand",
                             line=dict(color=RESOURCE_COLORS[res], width=3, dash="dash")))
    fig.add_trace(go.Scatter(x=p.date.iloc[:1], y=p.demand.iloc[:1], name="Actual (baseline)", mode="markers",
                             marker=dict(color=RESOURCE_COLORS[res], size=11, line=dict(color="white", width=2))))
    fig.update_yaxes(title_text=unit)
    fig.update_layout(legend_traceorder="normal")
    fig.update_xaxes(hoverformat="%b %Y", tickformat="%b %Y")
    st.plotly_chart(style(fig), width="stretch")

with insight_col:
    st.markdown('<div class="section">Executive insights</div>', unsafe_allow_html=True)
    for sev, msg in notes:
        st.markdown(f'<div class="insight" style="border-left:4px solid {COLORS[sev]}">'
                    f'{md_bold_to_html(msg)}</div>', unsafe_allow_html=True)

st.markdown(f'<div class="section">Site utilization at month {h} ({month_label(h)})</div>',
            unsafe_allow_html=True)
fig2 = go.Figure()
for r, (_, _, _, _, lbl) in RESOURCES.items():
    fig2.add_trace(go.Bar(x=risk.site_id, y=risk[f"util_horizon_{r}"] * 100, name=lbl,
                          marker_color=RESOURCE_COLORS[r],
                          hovertemplate="%{x}: %{y:.0f}%<extra>" + lbl + "</extra>"))
fig2.add_hline(y=a.threshold_pct, line=dict(color=COLORS["warning"], dash="dot"),
               annotation_text=f"{a.threshold_pct:.0f}% threshold", annotation_font_color=COLORS["warning"])
fig2.add_hline(y=100, line=dict(color=COLORS["Critical"], dash="dash"),
               annotation_text="100% capacity", annotation_font_color=COLORS["Critical"])
fig2.update_layout(barmode="group", hovermode="closest")
fig2.update_yaxes(title_text="Utilization (%)")
st.plotly_chart(style(fig2, 320), width="stretch")

# --------------------------------------------------------------------------- #
# 9. Stranded capacity
# --------------------------------------------------------------------------- #
st.markdown('<div class="section">Stranded power — installed capacity that cannot be used</div>',
            unsafe_allow_html=True)
sc_chart, sc_text = st.columns([2, 1], gap="large")
sd = stranded.iloc[::-1]   # DC1 at the top of a horizontal bar chart
fig3 = go.Figure()
fig3.add_trace(go.Bar(y=sd.site_id, x=sd.power_demand_mw, orientation="h", name="In use",
                      marker_color=RESOURCE_COLORS["power"]))
fig3.add_trace(go.Bar(y=sd.site_id, x=sd.power_usable_mw - sd.power_demand_mw, orientation="h",
                      name="Usable headroom", marker_color="#334A70"))
fig3.add_trace(go.Bar(y=sd.site_id, x=sd.stranded_power_mw, orientation="h",
                      name="Stranded", marker_color=COLORS["warning"]))
fig3.update_layout(barmode="stack", hovermode="y unified", legend_traceorder="normal")
fig3 = style(fig3, 300)
fig3.update_layout(margin=dict(t=40), legend=dict(y=1.15))
fig3.update_xaxes(title_text="MW (bar length = installed power)")
with sc_chart:
    st.plotly_chart(fig3, width="stretch")
with sc_text:
    st.markdown(
        '<div class="insight">Power, cooling and rack space have to grow together. When cooling or racks '
        'run out first, the remaining <b>installed power cannot be sold or used</b>. Fixing the smaller '
        'resource is usually a cheaper project than adding new MW.</div>', unsafe_allow_html=True)
    fixes = stranded[stranded.stranded_power_mw >= 0.1].sort_values("stranded_power_mw", ascending=False)
    for r in fixes.itertuples():
        need = []
        if r.unlock_racks > 0:
            need.append(f"{r.unlock_racks:,.0f} racks")
        if r.unlock_cooling_kw > 0:
            need.append(f"{r.unlock_cooling_kw:,.0f} kW cooling")
        st.markdown(f'<div class="insight" style="border-left:4px solid {COLORS["warning"]}">'
                    f'<b>{r.site_id}</b> · {r.stranded_power_mw:.1f} MW stranded '
                    f'({RESOURCES[r.binding_resource][4].lower()} binds) → add {" + ".join(need)}</div>',
                    unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# 10. Six-site comparison table
# --------------------------------------------------------------------------- #
st.markdown('<div class="section">Six-site comparison</div>', unsafe_allow_html=True)
table = pd.DataFrame({
    "Site": risk.site_id,
    "Name": risk.site_name,
    "Risk": risk.risk,
    "Limiting resource": risk.limiting_resource.map(lambda r: RESOURCES[r][4]),
    "Power now": risk.util_now_power * 100,
    "Cooling now": risk.util_now_cooling * 100,
    "Racks now": risk.util_now_racks * 100,
    f"Crosses {a.threshold_pct:.0f}%": [("Already over" if m == 0 else month_label(m)) if pd.notna(m) else "—"
                                       for m in risk.threshold_month],
    "Exhaustion": [month_label(m) if pd.notna(m) else "—" for m in risk.exhaustion_month],
    f"Range ±{a.growth_uncertainty_pp:g} pp": [fmt_range(ranges.loc[sid].exh_early, ranges.loc[sid].exh_late)
                                               for sid in risk.site_id],
})
styled = table.style.map(lambda v: f"color:{COLORS.get(v, '#E6ECF5')}; font-weight:600", subset=["Risk"])
pct = st.column_config.ProgressColumn
st.dataframe(
    styled, hide_index=True, width="stretch",
    column_config={
        "Power now": pct("Power now", min_value=0, max_value=100, format="%.0f%%", width="small"),
        "Cooling now": pct("Cooling now", min_value=0, max_value=100, format="%.0f%%", width="small"),
        "Racks now": pct("Racks now", min_value=0, max_value=100, format="%.0f%%", width="small"),
    },
)

with st.expander("Assumptions & methodology"):
    st.markdown(f"""
- **Forecast demand** = baseline demand × (1 + annual growth) ^ (months / 12), calculated monthly for 36 months.
- **Utilization** = demand / capacity · **Headroom** = capacity − demand · **Portfolio utilization** = Σ demand / Σ capacity.
- **Threshold crossing** = first month utilization ≥ {a.threshold_pct:.0f}%. **Exhaustion** = first month demand > capacity.
- **Efficiency** reduces projected power and cooling demand (not rack count); the month-0 baseline is never changed.
- **Planned expansions** add capacity from their activation month onward.
- **Risk:** Critical = exhaustion within 12 months · High = threshold within 12 months ·
  Medium = threshold within 36 months · Low = no threshold crossing in 36 months.
- **Forecast range:** the forecast is re-run with every site's growth ± {a.growth_uncertainty_pp:g} percentage points;
  the table shows the window between the earliest and latest exhaustion date.
- **Stranded capacity** = installed capacity that cannot be used because another resource at the same site runs out
  first. Each resource supports capacity / demand times today's load; the smallest ratio is the site's real limit,
  and capacity above it in the other resources is stranded. Calculated on today's installed capacity.
- Units: power in MW, cooling in kW of heat rejection, rack space in rack positions. All data is synthetic.
""")
