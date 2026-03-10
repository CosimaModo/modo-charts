#!/usr/bin/env python3
"""
One-time migration: build enhanced deals.csv from current deals.csv + europe_deal_summary.csv.

Adds:
  - revenue_model column to all 2025 deals
  - 25 backfilled 2024 deals from europe_deal_summary.csv

Result: 90-row deals.csv (25 from 2024 + 65 from 2025) that is the single source of truth
for all 9 charts in generate_charts.py.
"""

import csv
import re
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_PATH = (
    Path(__file__).parent.parent
    / "output"
    / "Transaction article "
    / "Europe"
    / "europe_deal_summary.csv"
)

# ── Editorial revenue model for 2025 deals ──────────────────────────
# Takes priority over europe_deal_summary.csv values.
# Covers: deals with no summary match, wrong summary classification, or "Other" country bucket.

EDITORIAL_REVENUE_MODEL = {
    # Germany (13m, 7t, 2h, 3u)
    "Green Flexibility and Hansa Battery 500 MW BESS Portfolio Acquisition": "merchant",
    "ju:niz Energy 100 MWh BESS Portfolio": "merchant",
    "Förderstedt 300 MW Battery Storage Project": "merchant",
    "Luxcara Waltrop BESS Acquisition": "merchant",
    "Giga Albatross BESS Acquisition": "merchant",
    "EWR AG Worms 30 MW Battery Storage Project": "merchant",
    "Econergy Brandenburg BESS Acquisition": "merchant",
    "Obton German BESS Portfolio Subordinated Debt Financing": "merchant",
    "Stendal Battery Storage Project": "tolling",
    "Terra One €150m Mezzanine Financing for 3GWh Germany BESS Pipeline": "hybrid",
    "Project Jupiter - WBS Power sale to Prime Capital": "undisclosed",
    "Return acquisition of four BESSMART battery storage sites in Eastern Germany": "undisclosed",
    "Hoxter Battery Park Acquisition": "undisclosed",
    # United Kingdom (9m, 3t, 3h, 0u)
    "Shetland Standby Project - Lerwick BESS": "merchant",
    "RWE Pembroke Battery Storage FID": "merchant",
    "Coalburn 2 BESS - 50% Stake Sale to AIP": "hybrid",
    "Drax acquisition of Apatura 260MW BESS portfolio": "hybrid",
    # Netherlands (1m, 1t, 3h, 0u)
    "GIGA Leopard Battery Storage Project": "hybrid",
    "Lion Storage Mufasa Project": "hybrid",
    # Italy (0m, 0t, 1h, 3u)
    "Project Sophocles Solar and Battery Green Loan": "hybrid",
    "Verdian 280 MW BESS Portfolio Acquisition Italy": "undisclosed",
    "Ric Energy Apulia 200MW BESS Acquisition": "undisclosed",
    "Gruppo Futura Agrivoltaic Project with BESS": "undisclosed",
    # Poland (1m, 0t, 2h, 0u)
    "Energix Polska Nowe Czarnowo I & II BESS Project Finance": "hybrid",
    # France (0m, 1t, 0h, 1u)
    "Kallista Energy Saleux BESS": "tolling",
    "Neoen Pan-European Warehouse Financing": "undisclosed",
    # Finland (1m, 2t, 0h, 0u)
    "OX2 Finland BESS Portfolio Financing": "tolling",
    # Greece (0m, 0t, 1h, 1u)
    "ib vogt Greece Solar+Storage Portfolio Sale to Faria Renewables": "undisclosed",
    # Lithuania → "Other" (0m, 0t, 0h, 3u)
    "Green Genius Izabelinė and Lieponys Solar+BESS Projects": "undisclosed",
    # Denmark → "Other"
    "Kvosted Solar Park BESS Optimisation Deal": "undisclosed",
    # Belgium → "Other"
    "Kallima Tihange BESS Financing": "undisclosed",
}


# ── 2024 deal filtering ─────────────────────────────────────────────

EXCLUDE_2024_NAMES = {
    "NW Groupe BESS Portfolio Non-Recourse Financing",                          # Multi-country
    "Trina Solar €150m Revolving Credit Facility for European Solar and BESS Development",  # Multi-country dup
    "DB Energie-Iqony Duisburg-Walsum BESS Power Storage Agreement",            # Tolling not counted
    "Harmony Energy 200MW BESS Sale to EDF Renewables Polska",                  # Sale type
    "Nofar Energy Germany Tolling-Backed BESS",                                 # Stendal duplicate
}

DEAL_TYPE_MAP = {
    "project_finance": "Project Finance",
    "acquisition": "Acquisition",
    "tolling": "Offtake Agreement",
    "equity_investment": "Equity Investment",
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def parse_sponsors(sponsors_str):
    """Parse 'Name1 (role1); Name2 (role2)' into list of (name, role) tuples."""
    result = []
    for entry in sponsors_str.split("; "):
        entry = entry.strip()
        match = re.match(r"^(.+?)\s*\(([^)]+)\)$", entry)
        if match:
            result.append((match.group(1).strip(), match.group(2).strip()))
        elif entry:
            result.append((entry, ""))
    return result


def extract_lead_sponsor(sponsors):
    """Extract lead sponsor (developer or first entry)."""
    for name, role in sponsors:
        if role == "developer":
            return name
    for name, role in sponsors:
        if role == "spv":
            return name
    return sponsors[0][0] if sponsors else ""


def extract_buyer(sponsors, deal_type, tolling_counterparty=""):
    """Extract buyer/counterparty."""
    if tolling_counterparty:
        return tolling_counterparty
    if deal_type == "acquisition":
        for name, role in sponsors:
            if role in ("equity_holder", "buyer"):
                return name
    elif deal_type == "tolling":
        for name, role in sponsors:
            if role == "offtaker":
                return name
    return ""


def clean_lender_string(lenders_str):
    """Clean lender string from summary format to deals.csv format.
    Strips role annotations like (lead_arranger), (participant), etc."""
    if not lenders_str:
        return ""
    parts = []
    for entry in lenders_str.split("; "):
        entry = entry.strip()
        # Strip role annotation
        cleaned = re.sub(r"\s*\([^)]*\)$", "", entry).strip()
        if cleaned:
            parts.append(cleaned)
    return "; ".join(parts)


def format_deal_value(debt_m, total_m):
    """Format deal value as €XXXm from total or debt value."""
    for val in [total_m, debt_m]:
        if val:
            try:
                v = float(val)
                if v >= 1000:
                    return f"€{v:,.0f}m"
                else:
                    return f"€{v:.0f}m"
            except (ValueError, TypeError):
                pass
    return ""


def quarter_of(date_str):
    """Return quarter string like 'Q1 2024'."""
    parts = date_str.split("-")
    year = parts[0]
    month = int(parts[1]) if len(parts) > 1 else 1
    q = (month - 1) // 3 + 1
    return f"Q{q} {year}"


def main():
    # ── Step 1: Read europe_deal_summary for revenue_model matching and 2024 deals ──
    summary_rows = []
    with open(SUMMARY_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            summary_rows.append(row)

    # Build name-to-revenue_model lookup from summary (2025 deals)
    summary_rev_model = {}
    for row in summary_rows:
        if row["date"].startswith("2025"):
            name = row["deal_name"]
            rm = row.get("revenue_model", "").strip()
            if rm:
                summary_rev_model[name] = rm

    # ── Step 2: Read current deals.csv (65 2025 deals) and add revenue_model ──
    deals_2025 = []
    with open(DATA_DIR / "deals.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            deals_2025.append(row)

    print(f"Read {len(deals_2025)} 2025 deals from deals.csv")

    # Assign revenue_model to each 2025 deal
    editorial, matched, unmatched = 0, 0, 0
    for deal in deals_2025:
        name = deal["name"]
        # Editorial override takes priority
        if name in EDITORIAL_REVENUE_MODEL:
            deal["revenue_model"] = EDITORIAL_REVENUE_MODEL[name]
            editorial += 1
        else:
            # Fall back to summary match
            rm = None
            for sname, srm in summary_rev_model.items():
                if name in sname or sname in name or _name_match(name, sname):
                    rm = srm
                    break
            if rm:
                deal["revenue_model"] = rm
                matched += 1
            else:
                deal["revenue_model"] = ""
                unmatched += 1
                print(f"  WARNING: no revenue_model for: {name}")

    print(f"  Editorial: {editorial}, Summary-matched: {matched}, Unmatched: {unmatched}")

    # ── Step 3: Build 2024 deals from europe_deal_summary ──
    deals_2024 = []
    for row in summary_rows:
        date = row["date"]
        if not date.startswith("2024"):
            continue
        name = row["deal_name"]
        if name in EXCLUDE_2024_NAMES:
            continue
        deal_type_raw = row["deal_type"]
        transaction_type = DEAL_TYPE_MAP.get(deal_type_raw)
        if not transaction_type:
            continue  # Skip sale, development, etc.

        sponsors = parse_sponsors(row.get("sponsors", ""))
        lead_sponsor = extract_lead_sponsor(sponsors)
        buyer = extract_buyer(
            sponsors, deal_type_raw,
            row.get("tolling_counterparty", "").strip()
        )
        lender = clean_lender_string(row.get("lenders", ""))

        mw = row.get("mw", "").strip()
        mwh = row.get("mwh", "").strip()
        duration = ""
        if mw and mwh:
            try:
                mw_f = float(mw)
                mwh_f = float(mwh)
                if mw_f > 0:
                    duration = f"{mwh_f / mw_f:.1f}"
            except (ValueError, TypeError):
                pass

        deal_value = format_deal_value(
            row.get("debt_eur_m", ""),
            row.get("total_value_eur_m", ""),
        )

        # Date display
        parts = date.split("-")
        year = parts[0]
        month = int(parts[1]) if len(parts) > 1 else 1
        date_display = f"{MONTH_NAMES[month]} {year}"

        country = row.get("country", "").strip()
        revenue_model = row.get("revenue_model", "").strip()

        # Format MW (some are decimal like 99.0 -> 99)
        mw_clean = ""
        if mw:
            try:
                mw_f = float(mw)
                if mw_f == int(mw_f):
                    mw_clean = str(int(mw_f))
                else:
                    mw_clean = str(mw_f)
            except ValueError:
                mw_clean = mw

        deals_2024.append({
            "name": name,
            "transaction_type": transaction_type,
            "mw": mw_clean,
            "duration_hrs": duration,
            "country": country,
            "lead_sponsor": lead_sponsor,
            "buyer_counterparty": buyer,
            "lender": lender,
            "deal_value": deal_value,
            "date": date,
            "date_display": date_display,
            "lat": row.get("lat", ""),
            "lon": row.get("lon", ""),
            "revenue_model": revenue_model,
        })

    print(f"Built {len(deals_2024)} 2024 deals from europe_deal_summary")

    # ── Step 4: Verify quarterly counts ──
    expected_quarterly = {
        "Q1 2024": {"europe": {"Project Finance": 4, "Acquisition": 2, "Equity Investment": 0, "Offtake Agreement": 1}},
        "Q2 2024": {"europe": {"Project Finance": 2, "Acquisition": 2, "Equity Investment": 0, "Offtake Agreement": 1}},
        "Q3 2024": {"europe": {"Project Finance": 2, "Acquisition": 1, "Equity Investment": 0, "Offtake Agreement": 0}},
        "Q4 2024": {"europe": {"Project Finance": 4, "Acquisition": 6, "Equity Investment": 0, "Offtake Agreement": 0}},
    }
    expected_germany = {
        "Q1 2024": {"Project Finance": 1, "Acquisition": 1},
        "Q2 2024": {"Project Finance": 1, "Acquisition": 1},
        "Q3 2024": {"Project Finance": 1, "Acquisition": 1},
        "Q4 2024": {"Project Finance": 0, "Acquisition": 4},
    }

    print("\nVerifying 2024 quarterly counts...")
    all_ok = True

    quarter_counts = defaultdict(lambda: defaultdict(int))
    germany_counts = defaultdict(lambda: defaultdict(int))
    for d in deals_2024:
        q = quarter_of(d["date"])
        quarter_counts[q][d["transaction_type"]] += 1
        if d["country"] == "Germany":
            germany_counts[q][d["transaction_type"]] += 1

    for q, expected in expected_quarterly.items():
        for tt in ["Project Finance", "Acquisition", "Equity Investment", "Offtake Agreement"]:
            actual = quarter_counts.get(q, {}).get(tt, 0)
            exp = expected["europe"].get(tt, 0)
            if actual != exp:
                print(f"  MISMATCH {q} Europe {tt}: got {actual}, expected {exp}")
                all_ok = False

    for q, expected in expected_germany.items():
        for tt in ["Project Finance", "Acquisition"]:
            actual = germany_counts.get(q, {}).get(tt, 0)
            exp = expected.get(tt, 0)
            if actual != exp:
                print(f"  MISMATCH {q} Germany {tt}: got {actual}, expected {exp}")
                all_ok = False

    if all_ok:
        print("  All quarterly counts match!")
    else:
        print("  ERRORS found. Aborting.")
        return

    # ── Step 5: Verify revenue-by-country totals (2025 only) ──
    expected_rbc = {
        "Germany": {"merchant": 13, "tolling": 7, "hybrid": 2, "undisclosed": 3},
        "United Kingdom": {"merchant": 9, "tolling": 3, "hybrid": 3, "undisclosed": 0},
        "Netherlands": {"merchant": 1, "tolling": 1, "hybrid": 3, "undisclosed": 0},
        "Italy": {"merchant": 0, "tolling": 0, "hybrid": 1, "undisclosed": 3},
        "Poland": {"merchant": 1, "tolling": 0, "hybrid": 2, "undisclosed": 0},
        "Finland": {"merchant": 1, "tolling": 2, "hybrid": 0, "undisclosed": 0},
        "Romania": {"merchant": 3, "tolling": 0, "hybrid": 0, "undisclosed": 0},
        "Greece": {"merchant": 0, "tolling": 0, "hybrid": 1, "undisclosed": 1},
        "France": {"merchant": 0, "tolling": 1, "hybrid": 0, "undisclosed": 1},
    }
    TOP_COUNTRIES = list(expected_rbc.keys())

    print("\nVerifying 2025 revenue-by-country...")
    rbc = defaultdict(lambda: defaultdict(int))
    for d in deals_2025:
        rm = d.get("revenue_model", "")
        c = d["country"]
        if c not in TOP_COUNTRIES:
            c = "Other"
        if rm in ("merchant", "tolling", "hybrid", "undisclosed"):
            rbc[c][rm] += 1
        elif rm == "ppa":
            rbc[c]["hybrid"] += 1  # PPA maps to hybrid

    rbc_ok = True
    for country, expected in expected_rbc.items():
        for rm_key in ["merchant", "tolling", "hybrid", "undisclosed"]:
            actual = rbc.get(country, {}).get(rm_key, 0)
            exp = expected[rm_key]
            if actual != exp:
                print(f"  MISMATCH {country} {rm_key}: got {actual}, expected {exp}")
                rbc_ok = False

    # Check Other = 0,0,0,3
    other_counts = rbc.get("Other", {})
    for rm_key, exp in [("merchant", 0), ("tolling", 0), ("hybrid", 0), ("undisclosed", 3)]:
        actual = other_counts.get(rm_key, 0)
        if actual != exp:
            print(f"  MISMATCH Other {rm_key}: got {actual}, expected {exp}")
            rbc_ok = False

    if rbc_ok:
        print("  All revenue-by-country counts match!")
    else:
        print("  ERRORS found. Aborting.")
        return

    # ── Step 6: Write enhanced deals.csv ──
    all_deals = deals_2024 + deals_2025
    # Sort by date descending (newest first)
    all_deals.sort(key=lambda d: d["date"], reverse=True)

    fieldnames = [
        "name", "transaction_type", "mw", "duration_hrs", "country",
        "lead_sponsor", "buyer_counterparty", "lender", "deal_value",
        "date", "date_display", "lat", "lon", "revenue_model",
    ]

    out_path = DATA_DIR / "deals.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in all_deals:
            writer.writerow({k: d.get(k, "") for k in fieldnames})

    print(f"\nWrote {len(all_deals)} deals to {out_path}")
    print(f"  2024: {len(deals_2024)}")
    print(f"  2025: {len(deals_2025)}")


def _name_match(a, b):
    """Simple name matching: check if significant words overlap."""
    def words(s):
        return set(w.lower() for w in re.findall(r"\w{4,}", s))
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    overlap = len(wa & wb)
    return overlap >= 2 and overlap / min(len(wa), len(wb)) >= 0.5


if __name__ == "__main__":
    main()
