# Six-Site Data Center Capacity Planning Simulator

An interactive Streamlit dashboard that shows how a regional data center operations leader can evaluate six facilities, forecast power, cooling and rack-space demand over 6–36 months, and spot the earliest capacity constraint before the portfolio average hides it.

> **Synthetic data — demonstration only.** All facilities and figures are invented.

## Features (prototype)

- Executive KPI cards: capacity, demand, utilization, headroom, 12/24/36-month forecast, sites at risk, earliest exhaustion
- Earliest site-level constraint banner, so a healthy portfolio average cannot hide a site that is about to run out
- Portfolio demand vs capacity chart (power, cooling or rack space), with planned expansions as capacity steps
- Site utilization at the selected horizon, against the threshold and 100% capacity
- Six-site comparison table with risk level, limiting resource, threshold and exhaustion dates
- Scenario presets (Baseline, High Growth, Efficiency) plus sliders for horizon, growth, efficiency and threshold
- Rules-based executive insights that cite the metrics behind them
- **Stranded capacity:** installed power that cannot be used because cooling or rack space runs out first, with the racks / cooling needed to unlock it
- **Forecast range:** growth ± N percentage points, shown as a band on the chart and an exhaustion window per site

See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the reasoning behind these choices.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python data/generate_data.py       # recreates data/sites.csv
streamlit run app.py
```

Run the tests:

```bash
pytest
```

## Deploy to Streamlit Community Cloud

1. Push this folder to a public GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io), choose **New app**, select the repository and set the main file to `app.py`.
3. Deploy. The theme in `.streamlit/config.toml` is picked up automatically.

## Project structure

```
app.py                 Streamlit UI (Executive Overview)
core/model.py          Forecasting, risk rules and insights (no UI code; fully tested)
data/generate_data.py  Reproducible six-site synthetic dataset
data/sites.csv         Generated dataset
tests/test_model.py    Unit tests for the calculations
.streamlit/config.toml Dark navy theme
```

## Methodology

| Quantity | Formula |
| --- | --- |
| Utilization | demand / capacity |
| Headroom | capacity − demand |
| Forecast demand | baseline demand × (1 + annual growth) ^ (months / 12) |
| Portfolio utilization | Σ demand / Σ capacity |
| Threshold crossing | first month utilization ≥ threshold (default 85%) |
| Exhaustion | first month demand > capacity |

- The model always forecasts 36 months monthly; the horizon control only changes what is displayed, so risk ratings stay stable.
- Efficiency improvements reduce projected power and cooling demand. Rack count is a physical footprint and is not reduced. The month-0 baseline is never changed.
- Planned expansions add capacity from their activation month onward.
- **Risk:** Critical = a resource runs out within 12 months · High = crosses the threshold within 12 months · Medium = crosses it within 36 months · Low = no crossing in 36 months.
- **Limiting resource:** the resource that crosses the threshold first (if none does, the most utilized today).
- **Stranded capacity:** each resource supports capacity / demand times today's load; the smallest ratio is the site's real limit, and capacity above it in the other resources is stranded.
- **Forecast range:** the forecast is re-run with every site's growth ± the uncertainty setting (default 3 pp).

## Data dictionary

| Column | Unit | Description |
| --- | --- | --- |
| site_id | – | DC1–DC6 |
| site_name, region | – | Fictional name and region |
| power_capacity_mw / power_demand_mw | MW | Installed electrical capacity / current demand |
| cooling_capacity_kw / cooling_load_kw | kW | Heat-rejection capacity / current heat load |
| rack_capacity / racks_occupied | racks | Rack positions available / in use |
| annual_growth_pct | % per year | Compound demand growth for the site |
| expansion_power_mw, expansion_cooling_kw, expansion_racks | MW, kW, racks | Planned added capacity |
| expansion_month | months | Months after baseline (Nov 2026) when the expansion goes live |

## Limitations

This is a decision-support demonstration, not an engineering or financial model. It does not model redundancy (N+1, 2N), PUE changes, seasonal load or detailed electrical/mechanical design.
