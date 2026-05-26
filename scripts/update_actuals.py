#!/usr/bin/env python3
"""
Month-End Actuals Update Script

Combines:
  - Revenue lines from our GL/Saasant output (corrected rev rec)
  - Expense/below-the-line lines from accountant's financials package
  - Balance sheet and SCF from accountant's financials package
  - Owner tax liability estimate (37% blended rate, 35% Cricket / 65% Khary)

Updates:
  - dashboard/data/actuals_snapshot.json (for Streamlit)

Usage:
    python scripts/update_actuals.py --gl-dir outputs/ --accountant-file <path> [--month "Apr 2026"]
    python scripts/update_actuals.py --update-revenue-only  # just replace revenue lines in existing snapshot
"""

import argparse
import json
import copy
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
SNAPSHOT_PATH = ROOT / "dashboard" / "data" / "actuals_snapshot.json"

# ─── Revenue account labels (from our GL/Saasant) ───────────────────────────
REVENUE_ACCOUNTS = [
    "401001 Machine",
    "401002 Private Pilates",
    "401003 Class Pass",
    "401004 Mighty Teacher Training",
    "401005 Livestream Classes",
    "403001 Machine Breakage",
    "403002 Mighty Teacher Training Breakage",
    "403003 Private Pilates Breakage",
    "403004 Other Breakage",
    "404000 Retail Sales",
    "406000 Refunds",
    "407000 Discounts",
]

# Summary rows that roll up revenue (recomputed from detail)
REVENUE_SUMMARY_ROWS = {
    "401000 Sessions",
    "Total for 401000 Sessions",
    "Total 401000 Sessions",
    "403000 Breakage Revenue",
    "Total for 403000 Breakage Revenue",
    "Total 403000 Breakage Revenue",
    "Total for Income",
    "Total Income",
    "Income",
    "Gross Profit",
}

# Saasant account name → snapshot account label mapping
SAASANT_TO_SNAPSHOT = {
    "Machine": "401001 Machine",
    "Private Pilates": "401002 Private Pilates",
    "Class Pass": "401003 Class Pass",
    "Mighty Teacher Training": "401004 Mighty Teacher Training",
    "Livestream Classes": "401005 Livestream Classes",
    "Machine Breakage": "403001 Machine Breakage",
    "Mighty Teacher Training Breakage": "403002 Mighty Teacher Training Breakage",
    "Private Pilates Breakage": "403003 Private Pilates Breakage",
    "Other Breakage": "403004 Other Breakage",
    "Retail Sales": "404000 Retail Sales",
    "Refunds": "406000 Refunds",
    "Discounts": "407000 Discounts",
}

# ─── Expense summary rows to extract from accountant P&L ────────────────────
# These are the stable subtotal labels that don't change when detail rows shift.
# We match with contains/startswith to handle "Total for XXX" vs "Total XXX" variants.
EXPENSE_SUMMARY_PATTERNS = [
    "Total for Cost of Goods Sold",
    "Total Cost of Goods Sold",
    "Total for 601000",    # Sales & Marketing
    "Total 601000",
    "Total for 602000",    # Payroll
    "Total 602000",
    "603000 Software",     # Single line (not a subtotal)
    "Total for 604000",    # Professional Fees
    "Total 604000",
    "Total for 616000",    # Utilities
    "Total 616000",
    "Total for 700000",    # Property Costs
    "Total 700000",
    "Total for Expenses",
    "Total Expenses",
    "Net Operating Income",
    "Total for Other Expenses",
    "Total Other Expenses",
    "Net Income",
]

# ─── Owner tax liability config ──────────────────────────────────────────────
TAX_RATE = 0.37  # Blended federal + state
OWNERSHIP = {"Cricket": 0.35, "Khary": 0.65}


def load_snapshot() -> dict:
    """Load existing actuals snapshot."""
    if SNAPSHOT_PATH.exists():
        with open(SNAPSHOT_PATH) as f:
            return json.load(f)
    return {"metadata": {}, "pl": {}, "bs": {}, "scf": {}, "studios": {}}


def save_snapshot(snap: dict):
    """Save actuals snapshot."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(snap, f, indent=2, default=str)
    print(f"  Saved: {SNAPSHOT_PATH}")


def load_saasant_revenue(gl_dir: Path, months: list[str]) -> dict:
    """
    Load revenue lines from FINAL Saasant files.
    Returns {month_label: {account: amount}} with positive amounts for revenue.
    """
    revenue = {}
    for month_label in months:
        # Find the FINAL Saasant file for this month
        m_short = month_label.split()[0][:3]  # "Jan 2026" → "Jan"
        year = month_label.split()[1]
        pattern = f"Saasant_Upload_{m_short}_{year}_*FINAL*.xlsx"
        matches = sorted(gl_dir.glob(pattern))
        if not matches:
            # Try without FINAL
            pattern = f"Saasant_Upload_{m_short}_{year}_*.xlsx"
            matches = sorted(gl_dir.glob(pattern))
        if not matches:
            print(f"  WARNING: No Saasant file found for {month_label}")
            continue

        fpath = matches[-1]  # Latest file
        print(f"  Loading revenue from: {fpath.name}")
        df = pd.read_excel(fpath)

        month_rev = {}
        for _, row in df.iterrows():
            acct = str(row.get(" Account ", "")).strip()
            amt = row.get(" Amount", 0)
            if acct in SAASANT_TO_SNAPSHOT:
                label = SAASANT_TO_SNAPSHOT[acct]
                month_rev[label] = month_rev.get(label, 0) + amt

        # Revenue lines are negative (credits) in Saasant → positive in snapshot
        # Refunds/Discounts are positive (debits) in Saasant → negative in snapshot
        for label in month_rev:
            if label in ("406000 Refunds", "407000 Discounts"):
                month_rev[label] = -abs(month_rev[label])
            else:
                month_rev[label] = abs(month_rev[label])

        revenue[month_label] = month_rev

    return revenue


def load_accountant_expenses(accountant_file: Path) -> dict:
    """
    Load expense summary rows from accountant's financials package.
    Returns {month_label: {account: amount}} for expense/below-the-line rows.
    """
    from pipeline.accountant_import import import_financials
    result = import_financials(str(accountant_file))

    expenses = {}
    pl_df = result["pl"]

    for col in pl_df.columns:
        if col == "Account":
            continue
        month_data = {}
        for _, row in pl_df.iterrows():
            acct = str(row["Account"]).strip()
            val = row[col]
            if pd.isna(val):
                val = 0
            month_data[acct] = float(val)
        expenses[col] = month_data

    return expenses, result


def match_summary_row(account_label: str) -> bool:
    """Check if an account label matches an expense summary pattern."""
    for pattern in EXPENSE_SUMMARY_PATTERNS:
        if pattern.lower() in account_label.lower():
            return True
    return False


def is_revenue_account(account_label: str) -> bool:
    """Check if an account label is a revenue line we control."""
    for rev_acct in REVENUE_ACCOUNTS:
        if account_label.strip() == rev_acct:
            return True
    if account_label.strip() in REVENUE_SUMMARY_ROWS:
        return True
    return False


def recompute_revenue_summaries(month_data: dict, is_studio: bool = False) -> dict:
    """Recompute revenue summary/subtotal rows from detail lines.

    is_studio: if True, refunds/discounts are positive (studio convention).
               if False, refunds/discounts are negative (consolidated convention).
    """
    data = dict(month_data)

    # Sessions subtotal
    sessions = sum(data.get(a, 0) for a in [
        "401001 Machine", "401002 Private Pilates", "401003 Class Pass",
        "401004 Mighty Teacher Training", "401005 Livestream Classes",
        "401006 Wellhub",
    ])
    for key in ["401000 Sessions", "Total for 401000 Sessions", "Total 401000 Sessions"]:
        if key in data:
            data[key] = sessions

    # Breakage subtotal
    breakage = sum(data.get(a, 0) for a in [
        "403001 Machine Breakage", "403002 Mighty Teacher Training Breakage",
        "403003 Private Pilates Breakage", "403004 Other Breakage",
    ])
    for key in ["403000 Breakage Revenue", "Total for 403000 Breakage Revenue",
                 "Total 403000 Breakage Revenue"]:
        if key in data:
            data[key] = breakage

    # Total Income
    refunds = data.get("406000 Refunds", 0)
    discounts = data.get("407000 Discounts", 0)
    if is_studio:
        # Studio: refunds/discounts are positive, subtract them
        total_income = (sessions + breakage +
                        data.get("404000 Retail Sales", 0) -
                        abs(refunds) - abs(discounts))
    else:
        # Consolidated: refunds/discounts are negative, just add them
        total_income = (sessions + breakage +
                        data.get("404000 Retail Sales", 0) +
                        refunds + discounts)
    for key in ["Total for Income", "Total Income"]:
        if key in data:
            data[key] = total_income

    # Gross Profit = Total Income - COGS
    cogs = 0
    for key in ["Total for Cost of Goods Sold", "Total Cost of Goods Sold"]:
        if key in data:
            cogs = data[key]
            break
    if "Gross Profit" in data:
        data["Gross Profit"] = total_income - cogs

    return data


def compute_owner_tax_liability(pl_data: dict) -> dict:
    """
    Compute estimated owner tax liability from cumulative net income.
    Returns {month: {Cricket: amount, Khary: amount, Total: amount}}
    """
    tax_liability = {}
    cumulative_ni = 0

    for month in sorted(pl_data.keys()):
        ni = 0
        for key in ["Net Income"]:
            if key in pl_data[month]:
                ni = pl_data[month][key]
                break
        cumulative_ni += ni
        est_tax = cumulative_ni * TAX_RATE
        tax_liability[month] = {
            "Cumulative Net Income": round(cumulative_ni, 2),
            "Estimated Tax (37%)": round(est_tax, 2),
            "Cricket (35%)": round(est_tax * OWNERSHIP["Cricket"], 2),
            "Khary (65%)": round(est_tax * OWNERSHIP["Khary"], 2),
        }

    return tax_liability


def update_snapshot_revenue(snap: dict, revenue: dict) -> dict:
    """Replace revenue lines in snapshot P&L with our GL values."""
    snap = copy.deepcopy(snap)

    for month_label, rev_data in revenue.items():
        if month_label not in snap["pl"]:
            print(f"  WARNING: {month_label} not in snapshot P&L, skipping")
            continue

        month_pl = snap["pl"][month_label]

        # Replace revenue detail lines
        for acct_label, amount in rev_data.items():
            if acct_label in month_pl:
                old = month_pl[acct_label]
                month_pl[acct_label] = amount
                if abs(old - amount) > 0.01:
                    print(f"    {month_label} {acct_label}: {old:,.2f} → {amount:,.2f}")

        # Recompute summaries
        snap["pl"][month_label] = recompute_revenue_summaries(month_pl)

    return snap


def update_snapshot_studio_revenue(snap: dict, gl_dir: Path, months: list[str]) -> dict:
    """Update per-studio revenue from Saasant files."""
    snap = copy.deepcopy(snap)

    # Studio code → Location name mapping
    studio_map = {
        "BK": "Berkeley", "CC": "Culver City", "CDM": "Corona Del Mar",
        "DN": "Danville", "HO": "Home Office", "LF": "Lafayette",
        "MR": "Marin", "OP": "Ocean Park", "PH": "Presidio Heights",
        "PS": "Presidio Heights",  # alias
        "RH": "Russian Hill", "SB": "Santa Barbara", "SM": "Santa Monica",
        "WP": "West Portal", "WW": "Westwood",
    }
    location_to_code = {v: k for k, v in studio_map.items()}
    # Handle duplicates
    location_to_code["Presidio Heights"] = "PH"

    for month_label in months:
        m_short = month_label.split()[0][:3]
        year = month_label.split()[1]
        pattern = f"Saasant_Upload_{m_short}_{year}_*FINAL*.xlsx"
        matches = sorted(gl_dir.glob(pattern))
        if not matches:
            continue
        df = pd.read_excel(matches[-1])

        # Group by Location
        for location in df["Location"].dropna().unique():
            code = location_to_code.get(location)
            if not code or code not in snap.get("studios", {}):
                continue

            studio_data = snap["studios"][code].get("data", {})
            if month_label not in studio_data:
                continue

            # First, zero out MTT Breakage (always $0 under new methodology)
            if "403002 Mighty Teacher Training Breakage" in studio_data[month_label]:
                studio_data[month_label]["403002 Mighty Teacher Training Breakage"] = 0

            loc_df = df[df["Location"] == location]
            for _, row in loc_df.iterrows():
                acct = str(row.get(" Account ", "")).strip()
                amt = row.get(" Amount", 0)
                if acct in SAASANT_TO_SNAPSHOT:
                    label = SAASANT_TO_SNAPSHOT[acct]
                    if label in studio_data[month_label]:
                        # Studio snapshot stores all values as positive
                        # (refunds/discounts positive, unlike consolidated which is negative)
                        studio_data[month_label][label] = abs(amt)

            # Recompute studio summaries
            snap["studios"][code]["data"][month_label] = recompute_revenue_summaries(
                studio_data[month_label], is_studio=True
            )

    return snap


def main():
    parser = argparse.ArgumentParser(description="Update Mighty Pilates actuals")
    parser.add_argument("--gl-dir", default=str(ROOT / "outputs"),
                        help="Directory with Saasant FINAL files")
    parser.add_argument("--accountant-file",
                        help="Path to accountant's financials Excel")
    parser.add_argument("--months", nargs="+",
                        default=["Jan 2026", "Feb 2026", "Mar 2026"],
                        help="Months to update")
    parser.add_argument("--update-revenue-only", action="store_true",
                        help="Only update revenue lines in existing snapshot")

    args = parser.parse_args()
    gl_dir = Path(args.gl_dir)

    print("Loading existing snapshot...")
    snap = load_snapshot()
    print(f"  Current actuals through: {snap['metadata'].get('last_actuals_month', 'unknown')}")

    # Step 1: Load and replace revenue from Saasant
    print(f"\nStep 1: Loading revenue from Saasant files ({', '.join(args.months)})...")
    revenue = load_saasant_revenue(gl_dir, args.months)

    print("\nStep 2: Updating consolidated P&L revenue...")
    snap = update_snapshot_revenue(snap, revenue)

    print("\nStep 3: Updating per-studio revenue...")
    snap = update_snapshot_studio_revenue(snap, gl_dir, args.months)

    if args.accountant_file and not args.update_revenue_only:
        print(f"\nStep 4: Loading expenses from accountant file...")
        expenses, acct_result = load_accountant_expenses(Path(args.accountant_file))
        # Expenses are already in the snapshot from the original import
        # Only needed when importing a NEW month's actuals
        print("  (Expense lines retained from existing snapshot)")

    # Step 5: Compute owner tax liability
    print("\nStep 5: Computing owner tax liability...")
    tax = compute_owner_tax_liability(snap["pl"])
    snap["owner_tax_liability"] = tax
    for month, vals in tax.items():
        print(f"  {month}: NI={vals['Cumulative Net Income']:>12,.2f}  "
              f"Tax={vals['Estimated Tax (37%)']:>10,.2f}  "
              f"Cricket={vals['Cricket (35%)']:>10,.2f}  "
              f"Khary={vals['Khary (65%)']:>10,.2f}")

    # Update metadata
    snap["metadata"]["updated_at"] = datetime.now().isoformat()
    snap["metadata"]["revenue_source"] = "Saasant FINAL 20260512 (corrected rev rec)"
    snap["metadata"]["expense_source"] = snap["metadata"].get("source_file", "accountant package")

    print("\nSaving snapshot...")
    save_snapshot(snap)

    # Summary
    print("\n" + "=" * 60)
    print("ACTUALS UPDATE COMPLETE")
    print("=" * 60)
    for month in args.months:
        if month in snap["pl"]:
            pl = snap["pl"][month]
            ti = 0
            for key in ["Total for Income", "Total Income"]:
                if key in pl:
                    ti = pl[key]
                    break
            ni = pl.get("Net Income", 0)
            print(f"  {month}: Revenue={ti:>12,.2f}  Net Income={ni:>12,.2f}")


if __name__ == "__main__":
    main()
