# Design Notes

**Why this dashboard is built the way it is**

This prototype was built against the Six-Site Capacity Planning SOW. Anyone can turn the SOW's formulas into charts. This document explains the decisions behind the build: what an operations leader actually needs from a capacity tool, and how each part of the dashboard answers that.

---

## 1. Start from the question the director asks

A regional data center director does not open a capacity tool to read "portfolio utilization is 66%". The real question is:

> **Which site, which resource, and when?**

So the first thing on the page is not a KPI card. It is a single banner naming the **earliest site-level constraint**: the site, the resource, the date, and how full it is today. Every other number on the page supports or explains that sentence.

## 2. Averages hide risk

The SOW says portfolio-level exhaustion must not hide earlier site-level constraints. This is the most important rule in the brief, and the synthetic data was built to prove the dashboard respects it:

| View | Rack space utilization |
| --- | --- |
| Portfolio average | 66% |
| DC5 Granite Falls | 88% (already over the 85% threshold) |

A dashboard that leads with the portfolio number says "healthy". This one leads with DC5.

## 3. Capacity has three dimensions, and they must grow together

Power, cooling and rack space are separate budgets. A new customer deployment needs all three at the same time. That has two consequences most capacity models ignore:

**The limiting resource.** Each site is judged on whichever resource runs out first, not on power alone. In the baseline, DC3 Red Mesa is limited by **cooling**, while DC1 and DC5 are limited by **rack space**.

**Stranded capacity.** When cooling or racks run out first, the remaining installed power cannot be used or sold. It was paid for, but it is idle. The dashboard measures this directly:

- Each resource can support (capacity ÷ demand) times today's load.
- The smallest of those ratios is the site's real growth limit.
- Capacity above that limit in the other resources is stranded.

In the baseline, **4.8 MW of installed power is stranded** across DC3, DC5 and DC1. The dashboard also shows what would unlock it: about **296 racks and 3,060 kW of cooling**. Adding racks or cooling is usually a much smaller project than adding new electrical capacity, so this turns a capacity report into a list of practical, lower-cost actions.

(It also shows that DC3's planned 3,000 kW cooling expansion is the right project: the site needs about 2,890 kW to release all 2.1 MW of its stranded power.)

## 4. Forecast dates are ranges, not points

Growth assumptions are estimates. A board that sees "DC5 runs out in September 2027" will plan to that date, and a single date implies a precision the model does not have.

The dashboard re-runs the forecast with growth ± 3 percentage points (adjustable) and shows:

- a shaded band around the projected demand line, and
- an **exhaustion window** per site (DC5: August – October 2027).

This stays fully deterministic, as the SOW requires. It is the same formula, run three times.

## 5. Expansion timing matters as much as expansion size

A planned expansion that goes live after the site runs out does not prevent the outage. The insights panel checks every planned expansion against the projected exhaustion date. In the baseline, DC5's expansion activates **five months after** its rack space is projected to run out, so the recommendation is to pull it forward.

## 6. Small modeling choices that keep the numbers honest

| Choice | Why |
| --- | --- |
| The model always forecasts the full 36 months | Risk ratings do not change when a user switches the horizon from 24 to 6 months. |
| Efficiency improvements reduce power and cooling demand, but not rack count | Better efficiency lowers energy use. It does not shrink a rack's footprint. |
| The month-0 baseline is never changed by a scenario | The SOW asks to separate actual data from projections. The baseline is drawn as a single "actual" point. |
| Planned expansions are capacity steps | Capacity arrives on a commissioning date, not gradually, so the chart draws it as a staircase. |
| Recommendations are rule-based and cite their numbers | Every insight names the site, metric and date behind it, so an executive can check it. |
| Inputs are validated | Negative values, zero capacity and demand above installed capacity are rejected with a clear message. |

## 7. Engineering approach

**One calculation engine, many pages.** All math lives in `core/model.py`, which contains no UI code. Every page calls the same functions with the same scenario assumptions. That is how "calculations must remain consistent across all dashboard pages" is guaranteed by design rather than by careful copying.

**Tested against the acceptance criteria.** The calculation engine has 14 automated tests with hand-checkable numbers:

| SOW acceptance criterion | Covered by |
| --- | --- |
| Forecast calculations verified against documented test cases | compound growth, utilization, headroom, growth override tests |
| Earliest site-level constraints correctly identified | portfolio-average-does-not-hide-site test, limiting-resource test |
| No negative or inconsistent inputs accepted | validation test |
| Changes reflected consistently | efficiency, expansion activation and forecast range tests |

**Reproducible data.** `data/generate_data.py` regenerates the exact six-site dataset, so every reviewer sees the same numbers.

## 8. From prototype to full build

This prototype covers the Executive Overview. The full build follows the SOW's five milestones:

| Milestone | Adds |
| --- | --- |
| 1 | Final architecture, dataset and calculation spec, matched to your reference mockup |
| 2 | Facility-level page: per-site drill-down and side-by-side comparison |
| 3 | Forecasting page and the remaining scenarios: Infrastructure Expansion and Budget-Constrained |
| 4 | Capital planning with configurable cost per MW, per kW of cooling and per rack; a transparent ranking by urgency, risk and cost; the consequences of deferring each project |
| 5 | CSV exports, printable executive summary, full test suite, documentation, deployment and walkthrough |

Optional ideas I would suggest discussing, outside the current scope:

- **Redundancy-aware capacity:** planning on usable capacity under N+1 or 2N design rather than installed nameplate capacity.
- **PUE linkage:** deriving cooling load from IT load and PUE, so an efficiency gain flows through to both power and cooling automatically.

## 9. Limitations

This is a decision-support demonstration, not an engineering or financial model. It does not model redundancy, seasonal load or detailed electrical and mechanical design, and it does not estimate financial ROI. All data is synthetic.
