#!/usr/bin/env python3
"""
generate_charts.py — Regenerate all Plotly HTML charts from canonical CSVs.

Reads data from:
  data/quarterly_deal_counts.csv
  data/revenue_by_country.csv
  data/rolling_averages.csv

Generates:
  deal-types-2025.html
  deals-by-quarter-2025.html
  europe-deals-doubled-2025.html
  germany-by-quarter-2025.html
  revenue-by-country-2025.html
  rolling-averages-2025.html

Usage:
  python3 generate_charts.py          # Regenerate all charts
  python3 generate_charts.py --check  # Dry-run: print totals, don't write files
"""

import csv
import os
import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"

# ── Modo design tokens ──────────────────────────────────────────────
COLORS = {
    "project_finance": "#B8CCE4",
    "acquisition": "#4472C4",
    "equity_investment": "#A0A0B8",
    "offtake_agreement": "#F5D5B0",
    "merchant": "#B8CCE4",
    "tolling": "#4472C4",
    "hybrid": "#A0A0B8",
    "undisclosed": "#E0E0E8",
    "bar_primary": "#B8CCE4",
    "line_primary": "#4472C4",
}
FONT = "DM Sans, Arial, sans-serif"
TEXT_COLOR = "#1A1A2E"
MUTED_COLOR = "#8C8CAA"
LIGHT_COLOR = "#AAAACC"
HOVER_BG = "#1A1A2E"
PLOTLY_CDN = (
    '<script charset="utf-8" src="https://cdn.plot.ly/plotly-3.3.1.min.js" '
    'integrity="sha256-4rD3fugVb/nVJYUv5Ky3v+fYXoouHaBSP20WIJuEiWg=" '
    'crossorigin="anonymous"></script>'
)
GOOGLE_FONTS = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">'
)

DEAL_TYPES = ["project_finance", "acquisition", "equity_investment", "offtake_agreement"]
DEAL_TYPE_LABELS = {
    "project_finance": "Project finance",
    "acquisition": "Acquisition",
    "equity_investment": "Equity investment",
    "offtake_agreement": "Offtake agreement",
}


# ── Data loading ─────────────────────────────────────────────────────

def load_quarterly_deal_counts():
    """Returns dict: {scope: [{quarter, project_finance, ...}, ...]}"""
    rows = []
    with open(DATA_DIR / "quarterly_deal_counts.csv", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for dt in DEAL_TYPES:
                row[dt] = int(row[dt])
            rows.append(row)
    result = {}
    for row in rows:
        scope = row["scope"]
        if scope not in result:
            result[scope] = []
        result[scope].append(row)
    return result


def load_revenue_by_country():
    """Returns list of dicts: [{country, merchant, tolling, hybrid, undisclosed}, ...]"""
    rows = []
    with open(DATA_DIR / "revenue_by_country.csv", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ["merchant", "tolling", "hybrid", "undisclosed"]:
                row[key] = int(row[key])
            rows.append(row)
    return rows


def load_rolling_averages():
    """Returns list of dicts: [{quarter, avg_capacity_mw, ...}, ...]"""
    rows = []
    with open(DATA_DIR / "rolling_averages.csv", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["avg_capacity_mw"] = int(row["avg_capacity_mw"])
            row["avg_duration_hrs"] = float(row["avg_duration_hrs"])
            row["n_deals_capacity"] = int(row["n_deals_capacity"])
            row["n_deals_duration"] = int(row["n_deals_duration"])
            rows.append(row)
    return rows


# ── HTML wrapper (new Modo CSS template) ─────────────────────────────

CSS_WRAPPER = """\
<html>
<head>
{google_fonts}
<meta charset="utf-8" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', Arial, sans-serif; background: white; }}
  .chart-wrapper {{ width: 100%; overflow: hidden; }}
  .chart-header {{ padding: 16px 20px 4px; }}
  .chart-title {{ font-size: 18px; font-weight: 700; color: #1A1A2E; line-height: 1.3; }}
  .chart-subtitle {{ font-size: 13px; color: #8C8CAA; margin-top: 4px; }}
  .chart-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  .chart-footer {{
    padding: 8px 20px 12px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  .chart-source {{ font-size: 10px; color: #8C8CAA; line-height: 1.5; }}
  .chart-notes {{ font-size: 9px; color: #AAAACC; }}
  .chart-logo {{
    font-size: 14px;
    font-weight: 700;
    color: #1A1A2E;
    letter-spacing: 4px;
    white-space: nowrap;
  }}
</style>
</head>
<body>
<div class="chart-wrapper">
  <div class="chart-header">
    <div class="chart-title">{title}</div>
    <div class="chart-subtitle">{subtitle}</div>
  </div>
  <div class="chart-scroll">
    <script type="text/javascript">window.PlotlyConfig = {{MathJaxConfig: 'local'}};</script>
    {plotly_cdn}
    <div id="{div_id}" style="height:{height}px; min-width:700px;"></div>
    <script type="text/javascript">
      window.PLOTLYENV=window.PLOTLYENV || {{}};
      if (document.getElementById("{div_id}")) {{
        Plotly.newPlot("{div_id}", {traces}, {layout}, {config});
      }};
    </script>
  </div>
  <div class="chart-footer">
    <div>
      <div class="chart-source">{source}</div>
      <div class="chart-notes">{notes}</div>
    </div>
    <div class="chart-logo">MODOENERGY</div>
  </div>
</div>
</body>
</html>"""


def render_chart(
    filename, div_id, title, subtitle, traces, layout,
    source="Source: Modo Energy",
    notes="Notes: Only publicly disclosed transactions are counted.",
    height=380,
):
    """Render a Plotly chart into the CSS wrapper template."""
    config = {"displayModeBar": False, "displaylogo": False, "responsive": True}
    html = CSS_WRAPPER.format(
        google_fonts=GOOGLE_FONTS,
        plotly_cdn=PLOTLY_CDN,
        div_id=div_id,
        title=title,
        subtitle=subtitle,
        traces=json.dumps(traces),
        layout=json.dumps(layout),
        config=json.dumps(config),
        source=source,
        notes=notes,
        height=height,
    )
    return html


# ── Shared layout helpers ────────────────────────────────────────────

def base_layout():
    return {
        "font": {"family": FONT, "size": 12, "color": TEXT_COLOR},
        "legend": {
            "font": {"size": 11, "color": TEXT_COLOR},
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0.0,
            "traceorder": "normal",
            "itemsizing": "constant",
            "bgcolor": "rgba(0,0,0,0)",
        },
        "hoverlabel": {
            "font": {"family": FONT, "size": 13, "color": "white"},
            "bgcolor": HOVER_BG,
            "bordercolor": "rgba(0,0,0,0)",
            "namelength": -1,
        },
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
    }


def stacked_bar_layout(y_max, tick_angle=-45):
    layout = base_layout()
    layout.update({
        "barmode": "stack",
        "bargap": 0.25,
        "xaxis": {
            "tickfont": {"size": 11, "color": TEXT_COLOR},
            "showgrid": False,
            "showline": False,
            "tickangle": tick_angle,
        },
        "yaxis": {
            "showgrid": False,
            "showline": False,
            "zeroline": False,
            "showticklabels": False,
            "range": [0, y_max],
        },
        "margin": {"l": 30, "r": 40, "t": 30, "b": 50},
        "height": 380,
    })
    return layout


def total_annotations(quarters, totals):
    """Create bar-total annotations above stacked bars."""
    annotations = []
    for q, t in zip(quarters, totals):
        annotations.append({
            "font": {"color": TEXT_COLOR, "family": FONT, "size": 11},
            "showarrow": False,
            "text": str(t),
            "x": q,
            "xanchor": "center",
            "y": t + 0.5,
            "yanchor": "bottom",
        })
    return annotations


# ── Chart generators ─────────────────────────────────────────────────

def generate_deal_types_chart(data, check=False):
    """Europe stacked bar: deal types by quarter."""
    rows = data["europe"]
    quarters = [r["quarter"] for r in rows]
    totals = [sum(r[dt] for dt in DEAL_TYPES) for r in rows]

    if check:
        print(f"deal-types-2025: quarters={quarters}")
        print(f"  totals={totals} (sum={sum(totals)})")
        return

    traces = []
    for dt in DEAL_TYPES:
        traces.append({
            "hovertemplate": f"{DEAL_TYPE_LABELS[dt]}: %{{y}}<extra></extra>",
            "marker": {"color": COLORS[dt], "line": {"width": 0}},
            "name": DEAL_TYPE_LABELS[dt],
            "x": quarters,
            "y": [r[dt] for r in rows],
            "type": "bar",
        })

    y_max = max(totals) + 4
    layout = stacked_bar_layout(y_max)
    layout["annotations"] = total_annotations(quarters, totals)

    html = render_chart(
        filename="deal-types-2025.html",
        div_id="dealtypes2025",
        title="Project finance dominated every quarter in 2025",
        subtitle="Number of deals by type, Q1 2024 \u2013 Q4 2025",
        traces=traces,
        layout=layout,
    )
    out_path = SCRIPT_DIR / "deal-types-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_deals_by_quarter_chart(data, check=False):
    """Europe stacked bar: identical data, different title (for article embed)."""
    rows = data["europe"]
    quarters = [r["quarter"] for r in rows]
    totals = [sum(r[dt] for dt in DEAL_TYPES) for r in rows]

    if check:
        print(f"deals-by-quarter-2025: quarters={quarters}")
        print(f"  totals={totals} (sum={sum(totals)})")
        return

    traces = []
    for dt in DEAL_TYPES:
        traces.append({
            "hovertemplate": f"{DEAL_TYPE_LABELS[dt]}: %{{y}}<extra></extra>",
            "marker": {"color": COLORS[dt], "line": {"width": 0}},
            "name": DEAL_TYPE_LABELS[dt],
            "x": quarters,
            "y": [r[dt] for r in rows],
            "type": "bar",
        })

    y_max = max(totals) + 4
    layout = stacked_bar_layout(y_max)
    layout["annotations"] = total_annotations(quarters, totals)

    html = render_chart(
        filename="deals-by-quarter-2025.html",
        div_id="dealsbyquarter2025",
        title="Activity accelerated through 2025, with Q3 and Q4 accounting for two thirds of all deals",
        subtitle="Number of deals",
        traces=traces,
        layout=layout,
    )
    out_path = SCRIPT_DIR / "deals-by-quarter-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_europe_doubled_chart(data, check=False):
    """Europe stacked bar: same data, title about deals doubling."""
    rows = data["europe"]
    quarters = [r["quarter"] for r in rows]
    totals = [sum(r[dt] for dt in DEAL_TYPES) for r in rows]

    if check:
        print(f"europe-deals-doubled-2025: quarters={quarters}")
        print(f"  totals={totals} (sum={sum(totals)})")
        return

    traces = []
    for dt in DEAL_TYPES:
        traces.append({
            "hovertemplate": f"{DEAL_TYPE_LABELS[dt]}: %{{y}}<extra></extra>",
            "marker": {"color": COLORS[dt], "line": {"width": 0}},
            "name": DEAL_TYPE_LABELS[dt],
            "x": quarters,
            "y": [r[dt] for r in rows],
            "type": "bar",
        })

    y_max = max(totals) + 4
    layout = stacked_bar_layout(y_max)
    layout["annotations"] = total_annotations(quarters, totals)

    html = render_chart(
        filename="europe-deals-doubled-2025.html",
        div_id="europe-deals-doubled",
        title="Across Europe, BESS deal numbers more than doubled from 2024 to 2025",
        subtitle="Number of deals by type, Q1 2024 \u2013 Q4 2025",
        traces=traces,
        layout=layout,
    )
    out_path = SCRIPT_DIR / "europe-deals-doubled-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_germany_chart(data, check=False):
    """Germany stacked bar: deal types by quarter."""
    rows = data["germany"]
    quarters = [r["quarter"] for r in rows]
    totals = [sum(r[dt] for dt in DEAL_TYPES) for r in rows]

    if check:
        print(f"germany-by-quarter-2025: quarters={quarters}")
        print(f"  totals={totals} (sum={sum(totals)})")
        return

    traces = []
    for dt in DEAL_TYPES:
        traces.append({
            "hovertemplate": f"{DEAL_TYPE_LABELS[dt]}: %{{y}}<extra></extra>",
            "marker": {"color": COLORS[dt], "line": {"width": 0}},
            "name": DEAL_TYPE_LABELS[dt],
            "x": quarters,
            "y": [r[dt] for r in rows],
            "type": "bar",
        })

    y_max = max(totals) + 3
    layout = stacked_bar_layout(y_max)
    layout["annotations"] = total_annotations(quarters, totals)

    html = render_chart(
        filename="germany-by-quarter-2025.html",
        div_id="germanybyquarter2025",
        title="Germany's deal activity surged in H2 2025, led by acquisitions",
        subtitle="Number of deals by type",
        traces=traces,
        layout=layout,
    )
    out_path = SCRIPT_DIR / "germany-by-quarter-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_revenue_by_country_chart(country_data, check=False):
    """Horizontal stacked bar: deals by revenue model per country."""
    rev_types = ["merchant", "tolling", "hybrid", "undisclosed"]
    rev_labels = {
        "merchant": "Merchant",
        "tolling": "Tolling",
        "hybrid": "Hybrid",
        "undisclosed": "Undisclosed",
    }
    countries = [r["country"] for r in country_data]
    totals = [sum(r[rt] for rt in rev_types) for r in country_data]

    if check:
        print(f"revenue-by-country-2025: countries={countries}")
        print(f"  totals={totals} (sum={sum(totals)})")
        return

    traces = []
    for rt in rev_types:
        traces.append({
            "hovertemplate": f"{rev_labels[rt]}: %{{x}}<extra></extra>",
            "marker": {"color": COLORS[rt], "line": {"width": 0}},
            "name": rev_labels[rt],
            "orientation": "h",
            "x": [r[rt] for r in country_data],
            "y": countries,
            "type": "bar",
        })

    x_max = max(totals) + 3
    layout = base_layout()
    layout.update({
        "barmode": "stack",
        "bargap": 0.25,
        "xaxis": {
            "showgrid": False,
            "showline": False,
            "showticklabels": False,
            "zeroline": False,
            "range": [0, x_max],
        },
        "yaxis": {
            "tickfont": {"size": 11, "color": TEXT_COLOR},
            "showgrid": False,
            "showline": False,
            "automargin": True,
        },
        "margin": {"l": 100, "r": 40, "t": 30, "b": 30},
        "height": 420,
    })

    # Total annotations to the right of bars
    annotations = []
    for country, total in zip(countries, totals):
        annotations.append({
            "font": {"color": TEXT_COLOR, "family": FONT, "size": 11},
            "showarrow": False,
            "text": str(total),
            "x": total + 0.3,
            "xanchor": "left",
            "y": country,
            "yanchor": "middle",
        })
    layout["annotations"] = annotations

    html = render_chart(
        filename="revenue-by-country-2025.html",
        div_id="revenuebycountry2025",
        title="Merchant revenue dominated in the UK and Germany",
        subtitle="Number of deals by revenue model, 2025",
        traces=traces,
        layout=layout,
        height=420,
    )
    out_path = SCRIPT_DIR / "revenue-by-country-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_rolling_averages_chart(avg_data, check=False):
    """Dual-axis bar+line: average capacity and duration per quarter."""
    quarters = [r["quarter"] for r in avg_data]
    capacities = [r["avg_capacity_mw"] for r in avg_data]
    durations = [r["avg_duration_hrs"] for r in avg_data]
    n_cap = [r["n_deals_capacity"] for r in avg_data]
    n_dur = [r["n_deals_duration"] for r in avg_data]

    if check:
        print(f"rolling-averages-2025: quarters={quarters}")
        print(f"  capacities={capacities}")
        print(f"  durations={durations}")
        return

    traces = [
        {
            "x": quarters,
            "y": capacities,
            "text": [f"{n} deals" for n in n_cap],
            "hovertemplate": (
                "<b>%{x}</b><br>Average capacity: %{y} MW"
                "<br><span style='color:#aaa'>%{text}</span><extra></extra>"
            ),
            "textposition": "none",
            "marker": {"color": COLORS["bar_primary"], "line": {"width": 0}},
            "name": "Average capacity (MW)",
            "yaxis": "y",
            "type": "bar",
        },
        {
            "x": quarters,
            "y": durations,
            "text": [f"{n} with data" for n in n_dur],
            "hovertemplate": (
                "<b>%{x}</b><br>Average duration: %{y:.1f} hrs"
                "<br><span style='color:#aaa'>%{text}</span><extra></extra>"
            ),
            "line": {"color": COLORS["line_primary"], "width": 2.5},
            "marker": {"color": COLORS["line_primary"], "size": 7},
            "mode": "lines+markers",
            "name": "Average duration (hrs)",
            "yaxis": "y2",
            "type": "scatter",
        },
    ]

    layout = base_layout()
    layout.update({
        "xaxis": {
            "tickfont": {"size": 11, "color": TEXT_COLOR},
            "showgrid": False,
            "showline": False,
            "tickangle": -45,
        },
        "yaxis": {
            "showgrid": False,
            "showline": False,
            "zeroline": False,
            "showticklabels": True,
            "tickfont": {"size": 10, "color": MUTED_COLOR},
            "range": [0, 600],
            "dtick": 100,
        },
        "yaxis2": {
            "showgrid": False,
            "showline": False,
            "zeroline": False,
            "showticklabels": True,
            "tickfont": {"size": 10, "color": COLORS["line_primary"]},
            "range": [0, 6],
            "dtick": 1,
            "ticksuffix": "h",
            "overlaying": "y",
            "side": "right",
        },
        "margin": {"l": 40, "r": 40, "t": 50, "b": 50},
        "barmode": "group",
        "bargap": 0.35,
        "height": 380,
    })

    # Callout annotations for largest deals
    layout["annotations"] = [
        {
            "x": "Q1 2024",
            "y": 538,
            "yref": "y",
            "yanchor": "bottom",
            "yshift": 8,
            "text": "<span style='color:#8C8CAA;'>Largest: Sosteneo / Enel Libra<br>1,700 MW</span>",
            "showarrow": False,
            "font": {"family": FONT, "size": 9, "color": MUTED_COLOR},
        },
        {
            "x": "Q3 2025",
            "y": 380,
            "yref": "y",
            "yanchor": "bottom",
            "yshift": 8,
            "text": "<span style='color:#8C8CAA;'>Largest: Thorpe Marsh<br>1,450 MW</span>",
            "showarrow": False,
            "font": {"family": FONT, "size": 9, "color": MUTED_COLOR},
        },
    ]

    html = render_chart(
        filename="rolling-averages-2025.html",
        div_id="rollingaverages2025",
        title="Average project size of recorded deals increased five times since Q2 2024",
        subtitle="Average project capacity (MW, bars) and duration (hours, line) per quarter.",
        traces=traces,
        layout=layout,
        notes="Notes: Excludes platform equity investments. Q2 and Q3 2024 averages based on 2-3 data points.",
    )
    out_path = SCRIPT_DIR / "rolling-averages-2025.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    check = "--check" in sys.argv

    print("Loading canonical data...")
    quarterly = load_quarterly_deal_counts()
    country = load_revenue_by_country()
    averages = load_rolling_averages()

    # Quick sanity checks
    europe_2024 = sum(
        sum(r[dt] for dt in DEAL_TYPES)
        for r in quarterly["europe"]
        if "2024" in r["quarter"]
    )
    europe_2025 = sum(
        sum(r[dt] for dt in DEAL_TYPES)
        for r in quarterly["europe"]
        if "2025" in r["quarter"]
    )
    country_total = sum(sum(r[rt] for rt in ["merchant", "tolling", "hybrid", "undisclosed"]) for r in country)

    print(f"  Europe 2024: {europe_2024} deals")
    print(f"  Europe 2025: {europe_2025} deals")
    print(f"  Europe total: {europe_2024 + europe_2025} deals")
    print(f"  Revenue-by-country total: {country_total} deals (2025 only)")
    print()

    if europe_2025 != country_total:
        print(f"  WARNING: Europe 2025 ({europe_2025}) != revenue-by-country ({country_total})")
        print()

    if check:
        print("Dry run (--check). Data per chart:")
        print()
        generate_deal_types_chart(quarterly, check=True)
        generate_deals_by_quarter_chart(quarterly, check=True)
        generate_europe_doubled_chart(quarterly, check=True)
        generate_germany_chart(quarterly, check=True)
        generate_revenue_by_country_chart(country, check=True)
        generate_rolling_averages_chart(averages, check=True)
        print()
        print("No files written.")
        return

    print("Generating charts...")
    generate_deal_types_chart(quarterly)
    generate_deals_by_quarter_chart(quarterly)
    generate_europe_doubled_chart(quarterly)
    generate_germany_chart(quarterly)
    generate_revenue_by_country_chart(country)
    generate_rolling_averages_chart(averages)
    print()
    print("Done. All 6 Plotly charts regenerated from canonical CSVs.")
    print()
    print("Charts NOT regenerated (manual/non-Plotly):")
    print("  top-15-projects-2025.html  (HTML table)")
    print("  top-lenders-2025.html      (HTML table)")
    print("  europe-bess-map-2025.html  (D3 map)")


if __name__ == "__main__":
    main()
