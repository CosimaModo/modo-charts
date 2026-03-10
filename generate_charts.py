#!/usr/bin/env python3
"""
generate_charts.py — Regenerate all 9 HTML charts from a single data source.

Single source of truth:
  data/deals.csv   (90 deals: 25 from 2024 + 65 from 2025)

All aggregate data (quarterly counts, revenue-by-country, rolling averages,
lender league table) is derived at runtime from deals.csv.

To add a deal: edit deals.csv, run this script, push to GitHub Pages.

Generates (Plotly):
  deal-types-2025.html
  deals-by-quarter-2025.html
  europe-deals-doubled-2025.html
  germany-by-quarter-2025.html
  revenue-by-country-2025.html
  rolling-averages-2025.html

Generates (HTML table / D3):
  top-15-projects-2025.html
  top-lenders-2025.html
  europe-bess-map-2025.html

Usage:
  python3 generate_charts.py          # Regenerate all charts
  python3 generate_charts.py --check  # Dry-run: print totals, don't write files
"""

import colorsys
import csv
import os
import sys
import json
from html import escape as _esc
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

MAP_TYPES = {
    "Project Finance": ("Project finance", "#4472C4"),
    "Acquisition": ("M&A", "#2F9FC4"),
    "Equity Investment": ("Equity", "#A0A0B8"),
    "Offtake Agreement": ("Offtake", "#F5D5B0"),
}


def _parse_num(s):
    """Parse a possibly comma-formatted number. Returns 0 for empty/dash."""
    s = s.strip().replace(",", "")
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _fmt_comma(n):
    """Format integer with comma separators."""
    return f"{n:,}" if n else ""


def _deal_hash_color(name):
    """Generate a deterministic muted color from a deal name."""
    h = 0
    for c in name:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    hue = (h % 360) / 360.0
    sat = 0.40 + ((h >> 8) % 100) / 400.0
    val = 0.45 + ((h >> 16) % 100) / 400.0
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


# ── Data loading ─────────────────────────────────────────────────────
# All data is derived from the single canonical file: data/deals.csv


def _quarter_of(date_str):
    """Return 'Q1 2024' etc. from an ISO date string."""
    parts = date_str.split("-")
    year = parts[0]
    month = int(parts[1]) if len(parts) > 1 else 1
    q = (month - 1) // 3 + 1
    return f"Q{q} {year}"


_TRANSACTION_TYPE_KEY = {
    "Project Finance": "project_finance",
    "Acquisition": "acquisition",
    "Equity Investment": "equity_investment",
    "Offtake Agreement": "offtake_agreement",
}


def load_deals():
    """Returns list of deal dicts from data/deals.csv (90 deals: 2024 + 2025).
    Each dict gets computed fields: mw_num, duration_num, quarter, year."""
    rows = []
    with open(DATA_DIR / "deals.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["mw_num"] = _parse_num(row["mw"])
            dur = row.get("duration_hrs", "").strip()
            row["duration_num"] = float(dur) if dur else 0
            row["quarter"] = _quarter_of(row["date"])
            row["year"] = row["date"][:4]
            rows.append(row)
    return rows


def derive_quarterly_deal_counts(deals):
    """Derive quarterly deal counts from deals list.
    Returns dict: {scope: [{quarter, project_finance, acquisition, ...}, ...]}"""
    from collections import defaultdict

    # Collect all quarters (sorted)
    all_quarters = sorted(set(d["quarter"] for d in deals))

    result = {}
    for scope in ("europe", "germany"):
        scope_deals = deals if scope == "europe" else [d for d in deals if d["country"] == "Germany"]
        counts = defaultdict(lambda: defaultdict(int))
        for d in scope_deals:
            q = d["quarter"]
            tt_key = _TRANSACTION_TYPE_KEY.get(d["transaction_type"], "")
            if tt_key:
                counts[q][tt_key] += 1
        rows = []
        for q in all_quarters:
            row = {"quarter": q, "scope": scope}
            for dt in DEAL_TYPES:
                row[dt] = counts[q].get(dt, 0)
            rows.append(row)
        result[scope] = rows
    return result


def derive_revenue_by_country(deals):
    """Derive revenue-by-country from 2025 deals.
    Returns list of dicts: [{country, merchant, tolling, hybrid, undisclosed}, ...]"""
    from collections import defaultdict

    TOP_COUNTRIES = [
        "Germany", "United Kingdom", "Netherlands", "Italy",
        "Poland", "Finland", "Romania", "Greece", "France",
    ]
    REV_TYPES = ["merchant", "tolling", "hybrid", "undisclosed"]

    counts = defaultdict(lambda: defaultdict(int))
    for d in deals:
        if d["year"] != "2025":
            continue
        rm = d.get("revenue_model", "").strip()
        if rm == "ppa":
            rm = "hybrid"
        if rm not in REV_TYPES:
            continue
        country = d["country"] if d["country"] in TOP_COUNTRIES else "Other"
        counts[country][rm] += 1

    rows = []
    for country in TOP_COUNTRIES + ["Other"]:
        row = {"country": country}
        for rt in REV_TYPES:
            row[rt] = counts[country].get(rt, 0)
        rows.append(row)
    return rows


def derive_rolling_averages(deals):
    """Derive rolling averages from Project Finance deals only.
    Returns list of dicts: [{quarter, avg_capacity_mw, avg_duration_hrs, ...}, ...]
    Note: 2024 values may differ slightly from the original hand-curated CSV
    because the 2024 deals in deals.csv are a curated subset."""
    from collections import defaultdict

    all_quarters = sorted(set(d["quarter"] for d in deals))
    pf_deals = [d for d in deals if d["transaction_type"] == "Project Finance"]

    cap_by_q = defaultdict(list)
    dur_by_q = defaultdict(list)
    for d in pf_deals:
        q = d["quarter"]
        if d["mw_num"] > 0:
            cap_by_q[q].append(d["mw_num"])
        if d["duration_num"] > 0:
            dur_by_q[q].append(d["duration_num"])

    rows = []
    for q in all_quarters:
        caps = cap_by_q.get(q, [])
        durs = dur_by_q.get(q, [])
        avg_cap = round(sum(caps) / len(caps)) if caps else 0
        avg_dur = round(sum(durs) / len(durs), 1) if durs else 0
        rows.append({
            "quarter": q,
            "avg_capacity_mw": avg_cap,
            "avg_duration_hrs": avg_dur,
            "n_deals_capacity": len(caps),
            "n_deals_duration": len(durs),
        })
    return rows


# ── Lender derivation constants ──────────────────────────────────────

_LENDER_NAME_MAP = {
    "Kommunalkredit Austria AG": "Kommunalkredit",
    "Société Générale S.A.": "Société Générale",
    "Hamburg Commercial Bank AG": "HCOB",
    "Deutsche Kreditbank AG": "DKB",
    "National Westminster Bank Plc": "NatWest",
    "KfW IPEX-BANK": "KfW IPEX-Bank",
    "National Bank of Greece S.A.": "National Bank of Greece",
    "Berenberg Green Energy Debt Funds": "Berenberg",
    "KKR Capital Markets Partners LLP": "KKR",
    "Santander Bank Polska": "Santander",
    "Santander CIB": "Santander",
    "Santander UK": "Santander",
    "Landesbank Saar": "SaarLB",
    "DAL Deutsche Anlagen-Leasing": "DAL / Deutsche Leasing",
}

_LENDER_EXCLUDE = {
    "Deutsche Anlagen-Leasing",
    "Deutsche Leasing Finance",
    "Goldman Sachs Alternatives",
    "Private Credit at Goldman Sachs Alternatives",
    "Aviva Investors",
    "Debt fund",
    "Syndicate of energy transition lenders",
    "8 European lenders",
    "Club of 8 European lenders",
    "European Union Recovery and Resilience Fund",
}


def _parse_lender_names(lender_str):
    """Parse semicolon-separated lender string into list of clean names."""
    import re
    if not lender_str or not lender_str.strip():
        return []
    names = []
    for part in lender_str.split(";"):
        part = part.strip()
        if not part:
            continue
        # Skip "+N" entries
        if re.match(r"^\+\d+$", part):
            continue
        # Strip trailing "+N" from last lender
        part = re.sub(r"\s*\+\d+$", "", part)
        if not part:
            continue
        # Apply name mapping
        mapped = _LENDER_NAME_MAP.get(part, part)
        # Check exclusion
        if mapped in _LENDER_EXCLUDE or part in _LENDER_EXCLUDE:
            continue
        names.append(mapped)
    return names


def derive_lender_data(deals):
    """Derive lender league table from 2025 Project Finance deals.
    Returns list of lender dicts matching the format expected by generate_top_lenders_chart."""
    from collections import defaultdict

    pf_2025 = [d for d in deals if d["year"] == "2025" and d["transaction_type"] == "Project Finance"]

    lender_deals = defaultdict(list)
    for d in pf_2025:
        lender_names = _parse_lender_names(d.get("lender", ""))
        for lname in lender_names:
            lender_deals[lname].append(d)

    lender_list = []
    for lname, ld in lender_deals.items():
        total_mw = sum(d["mw_num"] for d in ld)
        # Compute energy (MWh) from MW * duration
        energy_vals = []
        for d in ld:
            if d["mw_num"] > 0 and d["duration_num"] > 0:
                energy_vals.append(d["mw_num"] * d["duration_num"])
        energy_mwh = f"{int(sum(energy_vals)):,}" if energy_vals else "-"
        countries = ", ".join(sorted(set(d["country"] for d in ld)))
        deal_details = []
        for d in sorted(ld, key=lambda x: x["mw_num"], reverse=True):
            if d["mw_num"] > 0:
                deal_details.append({
                    "name": d["name"],
                    "sponsor": d["lead_sponsor"],
                    "mw": d["mw_num"],
                })
        lender_list.append({
            "lender": lname,
            "deal_count": len(ld),
            "total_mw": total_mw,
            "energy_mwh": energy_mwh,
            "countries": countries,
            "deals": deal_details,
        })

    # Sort by deal_count desc, then total_mw desc
    lender_list.sort(key=lambda x: (-x["deal_count"], -x["total_mw"]))
    return lender_list


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


# ── Non-Plotly chart generators ──────────────────────────────────────

# Shared CSS block for table-based charts (projects + lenders)
_TABLE_CSS_BASE = """\
* { margin:0; padding:0; box-sizing:border-box; }
html, body { height:100%; }
body { font-family: DM Sans, Arial, sans-serif; background:white; color:#1A1A2E; }
.chart-wrapper { width:100%; height:100%; display:flex; flex-direction:column; overflow:hidden; }
.chart-header { padding:16px 20px 4px; flex-shrink:0; }
.chart-title { font-size:18px; font-weight:700; color:#1A1A2E; line-height:1.3; }
.chart-subtitle { font-size:13px; color:#8C8CAA; margin-top:4px; }
.chart-scroll { flex:1; overflow:auto; -webkit-overflow-scrolling:touch; padding:0 20px; }
.chart-footer { padding:8px 20px 12px; display:flex; justify-content:space-between; align-items:flex-end; flex-shrink:0; }
.chart-source { font-size:10px; color:#8C8CAA; line-height:1.5; }
.chart-notes { font-size:9px; color:#AAAACC; }
.chart-logo { font-size:14px; font-weight:700; color:#1A1A2E; letter-spacing:4px; white-space:nowrap; }
.search-box { margin-bottom:12px; }
.search-box input { width:180px; padding:6px 10px; font-size:12px; font-family:DM Sans, Arial, sans-serif; border:1px solid #ddd; border-radius:4px; outline:none; color:#333; }
.search-box input::placeholder { color:#999; }
th { background:#555; color:white; text-align:left; padding:10px 8px; font-weight:600; font-size:11px; border:none; white-space:nowrap; }
th:first-child { border-radius: 4px 0 0 0; }
th:last-child { border-radius: 0 4px 0 0; }
td { padding:8px 8px; border-bottom:1px solid #f0f0f0; font-size:11px; vertical-align:middle; }
tr:hover td { background:#f0f4ff !important; }
.value-cell { text-align:right; font-variant-numeric: tabular-nums; }"""


def generate_top15_projects_chart(deals, check=False):
    """HTML table: all 2025 deals with search box, MW bars, zebra striping."""
    n_deals = len(deals)
    total_gw = sum(d["mw_num"] for d in deals) / 1000
    n_countries = len(set(d["country"] for d in deals if d["country"]))
    max_mw = max((d["mw_num"] for d in deals), default=1) or 1

    if check:
        print(f"top-15-projects-2025: {n_deals} deals, {total_gw:.0f} GW, {n_countries} countries")
        return

    # Build table rows
    row_parts = []
    for i, d in enumerate(deals):
        bg = "white" if i % 2 == 0 else "#F8F8FC"
        if d["mw_num"] > 0:
            pct = d["mw_num"] / max_mw * 100
            mw_cell = (
                '<div class="mw-bar-container">'
                '<div class="mw-bar" style="width:%.2f%%"></div>'
                '<span class="mw-label">%s</span></div>'
            ) % (pct, _fmt_comma(d["mw_num"]))
        else:
            mw_cell = ""
        dur = d["duration_hrs"].strip()
        val = d.get("deal_value", "").strip()
        val_display = val.replace("\u20ac", "").strip() if val else ""
        row_parts.append(
            "<tr>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s;text-align:center\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s;font-size:10px\">%s</td>"
            "<td style=\"background:%s\" class=\"value-cell\">%s</td>"
            "<td style=\"background:%s;white-space:nowrap\">%s</td>"
            "</tr>" % (
                bg, _esc(d["name"]),
                bg, _esc(d["transaction_type"]),
                bg, mw_cell,
                bg, dur,
                bg, _esc(d["country"]),
                bg, _esc(d.get("lead_sponsor", "")),
                bg, _esc(d.get("buyer_counterparty", "")),
                bg, _esc(d.get("lender", "")),
                bg, val_display,
                bg, d["date_display"],
            )
        )

    title = "%d deals totalling %d GW closed in 2025 across %d European countries" % (
        n_deals, int(total_gw), n_countries)

    out = [
        "<!DOCTYPE html><html><head>",
        '<meta charset="utf-8">',
        GOOGLE_FONTS,
        "<style>",
        _TABLE_CSS_BASE,
        "table { border-collapse:collapse; width:100%; font-size:11px; min-width:700px; }",
        ".mw-bar-container { display:flex; align-items:center; gap:6px; min-width:120px; }",
        ".mw-bar { height:14px; background:#4472C4; border-radius:2px; min-width:1px; }",
        ".mw-label { font-size:10px; font-weight:600; white-space:nowrap; color:#333; }",
        "</style>",
        "<script>",
        "function filterTable(){",
        '  var q = document.getElementById("search").value.toLowerCase();',
        '  var rows = document.querySelectorAll("#t1 tbody tr");',
        "  rows.forEach(function(row){",
        "    var text = row.textContent.toLowerCase();",
        '    row.style.display = text.indexOf(q) !== -1 ? "" : "none";',
        "  });",
        "}",
        "</script></head><body>",
        '<div class="chart-wrapper">',
        '<div class="chart-header">',
        '<div class="chart-title">%s</div>' % _esc(title),
        '<div class="chart-subtitle">2025 European BESS transactions</div>',
        "</div>",
        '<div class="chart-scroll">',
        '<div class="search-box"><input id="search" type="text" '
        'placeholder="Search..." oninput="filterTable()"></div>',
        '<table id="t1"><thead><tr>',
        "<th>Project Name</th>",
        "<th>Transaction Type</th>",
        "<th>Power (MW)</th>",
        "<th>Duration (hrs)</th>",
        "<th>Country</th>",
        "<th>Lead Sponsor</th>",
        "<th>Buyer/Counterparty</th>",
        "<th>Lender</th>",
        "<th>Deal Value (EUR m)</th>",
        "<th>Date</th>",
        "</tr></thead><tbody>",
    ]
    out.extend(row_parts)
    out.extend([
        "</tbody></table>",
        "</div>",
        '<div class="chart-footer">',
        "<div>",
        '<div class="chart-source">Source: Modo Energy</div>',
        '<div class="chart-notes">Notes: Only publicly disclosed transactions are counted.</div>',
        "</div>",
        '<div class="chart-logo">MODOENERGY</div>',
        "</div></div></body></html>",
    ])
    page_html = "\n".join(out)
    out_path = SCRIPT_DIR / "top-15-projects-2025.html"
    out_path.write_text(page_html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_top_lenders_chart(lender_data, check=False):
    """HTML table: lenders ranked by deal count, with colored stacked bar segments."""
    n_lenders = len(lender_data)
    max_total_mw = max((l["total_mw"] for l in lender_data), default=1) or 1

    if check:
        print(f"top-lenders-2025: {n_lenders} lenders, max MW = {max_total_mw}")
        return

    row_parts = []
    for i, lender in enumerate(lender_data):
        bg = "white" if i % 2 == 0 else "#F8F8FC"
        if lender["total_mw"] > 0 and lender["deals"]:
            bar_pct = lender["total_mw"] / max_total_mw * 100
            segments = []
            for deal in lender["deals"]:
                seg_pct = deal["mw"] / lender["total_mw"] * 100
                color = _deal_hash_color(deal["name"])
                segments.append(
                    '<div class="bar-seg" '
                    'data-sponsor="%s" '
                    'data-deal="%s" '
                    'data-mw="%s" '
                    'style="width:%.1f%%;height:14px;background:%s"></div>'
                    % (
                        _esc(deal["sponsor"]),
                        _esc(deal["name"]),
                        _fmt_comma(deal["mw"]),
                        seg_pct,
                        color,
                    )
                )
            bar_html = (
                '<div style="display:flex;align-items:center;gap:8px">'
                '<div style="display:flex;height:14px;border-radius:2px;'
                'overflow:hidden;width:%.1f%%;min-width:4px">%s</div>'
                '<span style="font-size:10px;font-weight:600;white-space:nowrap;'
                'color:#333;flex-shrink:0">%s</span></div>'
                % (bar_pct, "".join(segments), _fmt_comma(lender["total_mw"]))
            )
        else:
            bar_html = '<span style="color:#aaa;font-size:10px">-</span>'

        energy = lender["energy_mwh"] if lender["energy_mwh"] != "-" else "-"
        row_parts.append(
            "<tr>"
            "<td style=\"background:%s;font-weight:500\">%s</td>"
            "<td style=\"background:%s;text-align:center\">%s</td>"
            "<td style=\"background:%s\">%s</td>"
            "<td style=\"background:%s\" class=\"value-cell\">%s</td>"
            "<td style=\"background:%s;font-size:10px\">%s</td>"
            "</tr>" % (
                bg, _esc(lender["lender"]),
                bg, lender["deal_count"],
                bg, bar_html,
                bg, energy,
                bg, _esc(lender["countries"]),
            )
        )

    top_lender = _esc(lender_data[0]["lender"]) if lender_data else "Unknown"
    out = [
        "<!DOCTYPE html><html><head>",
        '<meta charset="utf-8">',
        GOOGLE_FONTS,
        "<style>",
        _TABLE_CSS_BASE,
        "table { border-collapse:collapse; width:100%; font-size:11px; "
        "table-layout:fixed; min-width:700px; }",
        "col.c-lender { width:17%; }",
        "col.c-deals  { width:5%; }",
        "col.c-power  { width:38%; }",
        "col.c-energy { width:13%; }",
        "col.c-country { width:27%; }",
        "td { overflow:hidden; text-overflow:ellipsis; }",
        ".bar-seg { display:inline-block; min-width:2px; cursor:pointer; "
        "position:relative; }",
        ".bar-seg:hover { opacity:0.85; }",
        "#tooltip {",
        "  display:none; position:fixed; z-index:1000;",
        "  background:rgba(26,26,46,0.92); color:#fff; padding:7px 11px;",
        "  border-radius:5px; font-size:11px; font-family:DM Sans, Arial, sans-serif;",
        "  pointer-events:none; white-space:nowrap; line-height:1.4;",
        "  box-shadow:0 2px 8px rgba(0,0,0,0.18);",
        "}",
        "#tooltip .tt-mw { color:#ccc; }",
        "</style>",
        "<script>",
        "function filterTable(){",
        '  var q = document.getElementById("search").value.toLowerCase();',
        '  var rows = document.querySelectorAll("#t7 tbody tr");',
        "  rows.forEach(function(row){",
        "    var text = row.textContent.toLowerCase();",
        '    row.style.display = text.indexOf(q) !== -1 ? "" : "none";',
        "  });",
        "}",
        "document.addEventListener('DOMContentLoaded', function(){",
        "  var tip = document.getElementById('tooltip');",
        "  document.querySelectorAll('.bar-seg').forEach(function(el){",
        "    el.addEventListener('mouseenter', function(e){",
        "      tip.innerHTML = '<span class=\"tt-mw\">' + el.dataset.deal "
        "+ ' \\u2014 ' + el.dataset.mw + ' MW</span>';",
        "      tip.style.display = 'block';",
        "    });",
        "    el.addEventListener('mousemove', function(e){",
        "      tip.style.left = (e.clientX + 12) + 'px';",
        "      tip.style.top = (e.clientY - 10) + 'px';",
        "    });",
        "    el.addEventListener('mouseleave', function(){",
        "      tip.style.display = 'none';",
        "    });",
        "  });",
        "});",
        "</script></head><body>",
        '<div id="tooltip"></div>',
        '<div class="chart-wrapper">',
        '<div class="chart-header">',
        '<div class="chart-title">%s was the most active European BESS '
        'lender by deal count in 2025</div>' % top_lender,
        '<div class="chart-subtitle">Lenders ranked by number of deals, '
        'then by total rated power (MW). Hover bars for project details.</div>',
        "</div>",
        '<div class="chart-scroll">',
        '<div class="search-box"><input id="search" type="text" '
        'placeholder="Search..." oninput="filterTable()"></div>',
        '<table id="t7"><colgroup><col class="c-lender"><col class="c-deals">'
        '<col class="c-power"><col class="c-energy"><col class="c-country"></colgroup>',
        "<thead><tr>",
        "<th>Lender</th>",
        '<th style="text-align:center">Deals</th>',
        "<th>Rated Power (MW) - disclosed</th>",
        '<th style="text-align:right">Energy (MWh)</th>',
        "<th>Countries</th>",
        "</tr></thead><tbody>",
    ]
    out.extend(row_parts)
    out.extend([
        "</tbody></table>",
        "</div>",
        '<div class="chart-footer">',
        "<div>",
        '<div class="chart-source">Source: Modo Energy</div>',
        '<div class="chart-notes">Notes: Bars show project breakdown by lead sponsor. '
        'Hover bars for details. Deals with undisclosed capacity show no bar. '
        'Excludes tolling agreements, equity-only deals, and mezzanine financing.</div>',
        "</div>",
        '<div class="chart-logo">MODOENERGY</div>',
        "</div></div></body></html>",
    ])
    page_html = "\n".join(out)
    out_path = SCRIPT_DIR / "top-lenders-2025.html"
    out_path.write_text(page_html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


def generate_europe_map_chart(deals, check=False):
    """D3.js + TopoJSON map with deal bubbles sized by MW, colored by type."""
    countries = sorted(set(d["country"] for d in deals if d["country"]))

    if check:
        print(f"europe-bess-map-2025: {len(deals)} deals, "
              f"{len(countries)} countries: {countries}")
        return

    # Build JS deals array
    js_entries = []
    for d in deals:
        ttype, color = MAP_TYPES.get(d["transaction_type"], ("Other", "#999"))
        mw_num = d["mw_num"]
        mw_str = "%s MW" % _fmt_comma(mw_num) if mw_num > 0 else ""
        name_js = d["name"].replace("\\", "\\\\").replace('"', '\\"')
        country_js = d["country"].replace('"', '\\"')
        js_entries.append(
            '{name:"%s",lat:%s,lon:%s,country:"%s",type:"%s",'
            'color:"%s",mw:"%s",date:"%s"}'
            % (name_js, d["lat"], d["lon"], country_js,
               ttype, color, mw_str, d["date"])
        )
    deals_js = ",\n".join(js_entries)
    countries_js = ", ".join('"%s"' % c for c in countries)

    # D3 rendering script
    d3_script = r"""
        const deals = [
%DEALS%
];
        const dealCountryNames = new Set([%COUNTRIES%]);

        const parseMW = s => { const n = parseFloat((s||"").replace(/,/g,"")); return isNaN(n) ? 0 : n; };
        const maxMW = Math.max(...deals.map(d => parseMW(d.mw))) || 1;
        deals.forEach(d => {
            const mwVal = parseMW(d.mw);
            d.radius = mwVal > 0 ? 3 + (Math.sqrt(mwVal / maxMW) * 16) : 4;
            d.capacity = d.mw || "Undisclosed";
        });

        const width = 800;
        const height = 480;

        const projection = d3.geoMercator()
            .center([10, 52])
            .scale(600)
            .translate([width / 2 - 20, height / 2]);

        const path = d3.geoPath().projection(projection);

        const svg = d3.select("#map")
            .append("svg")
            .attr("width", width)
            .attr("height", height)
            .attr("viewBox", `0 0 ${width} ${height}`);

        svg.append("defs").append("clipPath")
            .attr("id", "map-clip")
            .append("rect")
            .attr("width", width)
            .attr("height", height);

        const mapGroup = svg.append("g").attr("clip-path", "url(#map-clip)");

        mapGroup.append("rect")
            .attr("width", width)
            .attr("height", height)
            .attr("class", "ocean");

        const tooltip = d3.select("#tooltip");

        d3.json("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json").then(function(world) {
            const countries = topojson.feature(world, world.objects.countries);

            const numericToName = {
                "826": "United Kingdom", "276": "Germany", "250": "France",
                "380": "Italy", "724": "Spain", "528": "Netherlands",
                "616": "Poland", "246": "Finland", "642": "Romania",
                "300": "Greece", "208": "Denmark", "440": "Lithuania",
                "056": "Belgium", "372": "Ireland", "620": "Portugal",
                "752": "Sweden", "040": "Austria", "756": "Switzerland",
                "203": "Czech Republic", "703": "Slovakia", "348": "Hungary",
                "191": "Croatia", "705": "Slovenia", "100": "Bulgaria",
                "804": "Ukraine", "112": "Belarus", "498": "Moldova",
                "688": "Serbia", "070": "Bosnia and Herzegovina",
                "499": "Montenegro", "807": "North Macedonia", "008": "Albania",
                "578": "Norway", "352": "Iceland", "233": "Estonia",
                "428": "Latvia", "442": "Luxembourg", "470": "Malta",
                "196": "Cyprus", "900": "Kosovo",
            };

            const europeFeatures = countries.features.filter(f => {
                const centroid = d3.geoCentroid(f);
                return centroid[1] > 34 && centroid[1] < 72 && centroid[0] > -25 && centroid[0] < 45;
            });

            mapGroup.selectAll(".country")
                .data(europeFeatures)
                .enter().append("path")
                .attr("class", d => {
                    const name = numericToName[d.id] || d.properties?.name || "";
                    return "country " + (dealCountryNames.has(name) ? "country-deal" : "country-no-deal");
                })
                .attr("d", path);

            const sortedDeals = [...deals].sort((a, b) => b.radius - a.radius);

            mapGroup.selectAll(".deal-bubble")
                .data(sortedDeals)
                .enter().append("circle")
                .attr("class", "deal-bubble")
                .attr("cx", d => projection([d.lon, d.lat])[0])
                .attr("cy", d => projection([d.lon, d.lat])[1])
                .attr("r", d => d.radius)
                .attr("fill", d => d.color)
                .attr("opacity", 0.85)
                .on("mouseover", function(event, d) {
                    d3.select(this).attr("opacity", 1).attr("stroke-width", "1.5px");
                    tooltip.style("opacity", 1)
                        .html(`<b>${d.name}</b><br>Country: ${d.country}<br>Capacity: ${d.capacity}<br>Type: ${d.type}<br>Date: ${d.date}`);
                })
                .on("mousemove", function(event) {
                    const containerRect = document.querySelector('.map-container').getBoundingClientRect();
                    const x = event.clientX - containerRect.left;
                    const y = event.clientY - containerRect.top;
                    const tooltipEl = document.getElementById('tooltip');
                    const tw = tooltipEl.offsetWidth;
                    let left = x + 15;
                    if (left + tw > 800) { left = x - tw - 15; }
                    tooltip.style("left", left + "px").style("top", (y - 10) + "px");
                })
                .on("mouseout", function() {
                    d3.select(this).attr("opacity", 0.85).attr("stroke-width", "0.6px");
                    tooltip.style("opacity", 0);
                });
        });
    """.replace("%DEALS%", deals_js).replace("%COUNTRIES%", countries_js)

    out = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '    <meta charset="utf-8">',
        "    <title>European BESS deal map 2025</title>",
        '    ' + GOOGLE_FONTS,
        '    <script src="https://d3js.org/d3.v7.min.js"></script>',
        '    <script src="https://cdn.jsdelivr.net/npm/topojson-client@3"></script>',
        "    <style>",
        "        * { margin: 0; padding: 0; box-sizing: border-box; }",
        "        body { font-family: 'DM Sans', Arial, sans-serif; background: white; }",
        "        .chart-wrapper { width: 100%; overflow: hidden; }",
        "        .chart-header { padding: 16px 20px 4px; }",
        "        .chart-title { font-size: 18px; font-weight: 700; color: #1A1A2E; "
        "line-height: 1.3; }",
        "        .chart-subtitle { font-size: 13px; color: #8C8CAA; margin-top: 4px; }",
        "        .chart-legend { display: flex; gap: 18px; padding: 8px 20px 4px; }",
        "        .legend-item { display: flex; align-items: center; gap: 5px; "
        "font-size: 11px; color: #1A1A2E; }",
        "        .legend-dot { width: 10px; height: 10px; border-radius: 50%; }",
        "        .chart-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }",
        "        .map-container { position: relative; min-width: 800px; }",
        "        .chart-footer {",
        "            padding: 8px 20px 12px;",
        "            display: flex;",
        "            justify-content: space-between;",
        "            align-items: flex-end;",
        "        }",
        "        .chart-source { font-size: 10px; color: #8C8CAA; line-height: 1.5; }",
        "        .chart-notes { font-size: 9px; color: #AAAACC; }",
        "        .chart-logo {",
        "            font-size: 14px;",
        "            font-weight: 700;",
        "            color: #1A1A2E;",
        "            letter-spacing: 4px;",
        "            white-space: nowrap;",
        "        }",
        "        svg { display: block; }",
        "        .country { stroke: white; stroke-width: 0.8px; }",
        "        .country-deal { fill: #D6DFED; }",
        "        .country-no-deal { fill: #EDEDF0; }",
        "        .ocean { fill: white; }",
        "        .deal-bubble { stroke: white; stroke-width: 0.6px; cursor: pointer; }",
        "        .tooltip {",
        "            position: absolute;",
        "            background: #1A1A2E;",
        "            color: white;",
        "            padding: 10px 14px;",
        "            border-radius: 6px;",
        "            font-size: 13px;",
        "            font-family: 'DM Sans', Arial, sans-serif;",
        "            pointer-events: none;",
        "            opacity: 0;",
        "            transition: opacity 0.15s;",
        "            line-height: 1.5;",
        "            max-width: 320px;",
        "            z-index: 10;",
        "        }",
        "        .tooltip b { font-weight: 700; }",
        "    </style>",
        "</head>",
        "<body>",
        '<div class="chart-wrapper">',
        '    <div class="chart-header">',
        '        <div class="chart-title">Germany and the UK accounted for '
        'most BESS deals in 2025</div>',
        '        <div class="chart-subtitle">European BESS transactions by '
        'location and type, 2025</div>',
        "    </div>",
        '    <div class="chart-legend">',
        '        <div class="legend-item"><div class="legend-dot" '
        'style="background:#4472C4;"></div>Project finance</div>',
        '        <div class="legend-item"><div class="legend-dot" '
        'style="background:#2F9FC4;"></div>M&amp;A</div>',
        '        <div class="legend-item"><div class="legend-dot" '
        'style="background:#A0A0B8;"></div>Equity</div>',
        '        <div class="legend-item"><div class="legend-dot" '
        'style="background:#F5D5B0;"></div>Offtake</div>',
        "    </div>",
        '    <div class="chart-scroll">',
        '        <div class="map-container">',
        '            <div id="map"></div>',
        '            <div class="tooltip" id="tooltip"></div>',
        "        </div>",
        "    </div>",
        '    <div class="chart-footer">',
        "        <div>",
        '            <div class="chart-source">Source: Modo Energy</div>',
        '            <div class="chart-notes">Circle size proportional to '
        'capacity (MW). For portfolio deals, location reflects company HQ.</div>',
        "        </div>",
        '        <div class="chart-logo">MODOENERGY</div>',
        "    </div>",
        "</div>",
        "    <script>",
        d3_script,
        "    </script>",
        "</body>",
        "</html>",
    ]
    page_html = "\n".join(out)
    out_path = SCRIPT_DIR / "europe-bess-map-2025.html"
    out_path.write_text(page_html, encoding="utf-8")
    print(f"  Wrote {out_path.name}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    check = "--check" in sys.argv

    print("Loading deals.csv (single source of truth)...")
    deals = load_deals()

    n_2024 = sum(1 for d in deals if d["year"] == "2024")
    n_2025 = sum(1 for d in deals if d["year"] == "2025")
    print(f"  {len(deals)} deals total ({n_2024} from 2024, {n_2025} from 2025)")

    print("Deriving aggregate data...")
    quarterly = derive_quarterly_deal_counts(deals)
    country = derive_revenue_by_country(deals)
    averages = derive_rolling_averages(deals)
    lender_data = derive_lender_data(deals)

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
    print(f"  Lenders: {len(lender_data)}")
    print()

    if europe_2025 != country_total:
        print(f"  WARNING: Europe 2025 ({europe_2025}) != revenue-by-country ({country_total})")
        print()

    # Top-15 and map charts only use 2025 deals
    deals_2025 = [d for d in deals if d["year"] == "2025"]

    if check:
        print("Dry run (--check). Data per chart:")
        print()
        generate_deal_types_chart(quarterly, check=True)
        generate_deals_by_quarter_chart(quarterly, check=True)
        generate_europe_doubled_chart(quarterly, check=True)
        generate_germany_chart(quarterly, check=True)
        generate_revenue_by_country_chart(country, check=True)
        generate_rolling_averages_chart(averages, check=True)
        generate_top15_projects_chart(deals_2025, check=True)
        generate_top_lenders_chart(lender_data, check=True)
        generate_europe_map_chart(deals_2025, check=True)
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
    generate_top15_projects_chart(deals_2025)
    generate_top_lenders_chart(lender_data)
    generate_europe_map_chart(deals_2025)
    print()
    print("Done. All 9 charts regenerated from deals.csv (single source of truth).")


if __name__ == "__main__":
    main()
