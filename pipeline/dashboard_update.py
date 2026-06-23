"""
Update the Streamlit dashboard's committed_actuals.json from imported
accountant-package CSVs.

Stage 2 of the monthly actuals integration pipeline:

  Stage 1: python run.py import-financials <path>     (already exists)
              → data/financials/{pl,bs,scf}_<Mon><Year>.csv
              → data/financials/studios_<Mon><Year>/<CODE>_<Mon><Year>.csv
              → data/financials/latest.json

  Stage 2: python run.py update-dashboard --month YYYY-MM
              → reads the CSVs above
              → updates dashboard/data/committed_actuals.json
              → writes dashboard/data/latest.json
              → snapshots committed_actuals.json to
                data/financials/streamlit_snapshots/

  Stage 3: python /path/to/financial-modeling/models/mighty/refresh_from_streamlit.py
              → reads committed_actuals.json
              → updates the Excel financial model in-place

Audit output emphasises (a) the new month being added and (b) any prior
months whose per-studio numbers changed since the prior import — e.g. the
2026-06-16 MTT geographic reclass that shifted Feb/Mar values between
studios while keeping the aggregate constant.
"""
from __future__ import annotations
import argparse
import calendar
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
FINANCIALS_DIR = PROJECT_ROOT / "data" / "financials"
DASHBOARD_DATA_DIR = PROJECT_ROOT / "dashboard" / "data"
SNAPSHOTS_DIR = FINANCIALS_DIR / "streamlit_snapshots"

COMMITTED_PATH = DASHBOARD_DATA_DIR / "committed_actuals.json"
LATEST_PATH = DASHBOARD_DATA_DIR / "latest.json"


def _month_label(year: int, month: int) -> str:
    return f"{calendar.month_abbr[month]} {year}"


def _month_tag(year: int, month: int) -> str:
    return f"{calendar.month_abbr[month]}{year}"


def _csv_to_account_dict(csv_path: Path, month_label: str, strict: bool = True) -> dict | None:
    """
    Read a PL/BS/SCF CSV and return {account: value} for the given month column.
    Returns None when the column is missing and strict=False (placeholder studio
    sparsity is normal — e.g. CDM has no April or May).
    """
    df = pd.read_csv(csv_path).set_index("Account")
    if month_label not in df.columns:
        if strict:
            raise ValueError(f"Column {month_label!r} not found in {csv_path.name}; "
                             f"have {list(df.columns)}")
        return None
    series = pd.to_numeric(df[month_label], errors="coerce").fillna(0)
    return {acct: float(v) for acct, v in series.items()}


# Specific subtotal labels that the dashboard expects populated (NOT all of them —
# expense-side subtotal labels like "602000 Payroll" stay at 0; the dashboard reads
# the corresponding "Total 602000 Payroll" sibling for those).
# Determined empirically from the May 26 actuals_snapshot.json baseline.
ENRICH_SUBTOTAL_LABELS = {
    "401000 Sessions",
    "403000 Breakage Revenue",
}

# Sign-flip applies ONLY to per-studio data. Consolidated PL keeps QBO-native
# negative values for refunds/discounts; the per-studio tabs flip them positive
# (this is how the snapshot was populated — preserving that convention here).
PER_STUDIO_SIGN_FLIP_ACCOUNTS = {"406000 Refunds", "407000 Discounts"}


def _enrich(account_dict: dict, *, is_per_studio: bool) -> dict:
    """
    Apply dashboard conventions to a raw {account: value} dict from QBO CSV.

    (a) For each whitelisted subtotal label that arrives as 0 in QBO, copy the
        sibling "Total X" value back into "X". Only applied to specific labels
        the dashboard depends on (revenue subtotals); expense subtotal labels
        stay at 0 per the established convention.
    (b) Per-studio only: flip sign on Refunds and Discounts (QBO native negative
        → dashboard positive). Consolidated PL keeps QBO-native sign.

    Returns a NEW dict — does not mutate the input.
    """
    out = dict(account_dict)
    # (a) subtotal injection — explicit whitelist
    for acct in ENRICH_SUBTOTAL_LABELS:
        total_key = f"Total {acct}"
        if acct in out and total_key in out:
            if abs(out[acct]) < 0.005 and abs(out[total_key]) >= 0.005:
                out[acct] = out[total_key]
    # (b) per-studio sign flip
    if is_per_studio:
        for acct in PER_STUDIO_SIGN_FLIP_ACCOUNTS:
            if acct in out and out[acct] < 0:
                out[acct] = abs(out[acct])
    return out


def _all_months_from_csv(csv_path: Path) -> list[str]:
    """All month columns in the CSV, in order."""
    df = pd.read_csv(csv_path, nrows=0)
    return [c for c in df.columns if c != "Account"]


def _diff_dict(old: dict | None, new: dict, tolerance: float = 0.005) -> dict:
    """Return {key: (old_value, new_value)} for any key whose value changed."""
    diffs = {}
    old = old or {}
    keys = set(old) | set(new)
    for k in keys:
        ov = float(old.get(k, 0.0) or 0.0)
        nv = float(new.get(k, 0.0) or 0.0)
        if abs(ov - nv) > tolerance:
            diffs[k] = (ov, nv)
    return diffs


def update_dashboard(year: int, month: int, source_label: str | None = None,
                     verbose: bool = True) -> dict:
    """
    Update committed_actuals.json with the latest accountant-package import.

    Pulls every month present in the CSVs (so prior-month restatements are
    reflected). Snapshots the resulting file. Returns an audit summary.
    """
    month_label = _month_label(year, month)
    month_tag = _month_tag(year, month)

    pl_csv = FINANCIALS_DIR / f"pl_{month_tag}.csv"
    bs_csv = FINANCIALS_DIR / f"bs_{month_tag}.csv"
    scf_csv = FINANCIALS_DIR / f"scf_{month_tag}.csv"
    studios_dir = FINANCIALS_DIR / f"studios_{month_tag}"

    for p in (pl_csv, bs_csv, scf_csv, studios_dir):
        if not p.exists():
            raise FileNotFoundError(
                f"{p} missing — did Stage 1 (import-financials) run for {month_label}?"
            )

    # Load existing committed_actuals
    if COMMITTED_PATH.exists():
        committed = json.loads(COMMITTED_PATH.read_text())
    else:
        committed = {"pl": {}, "bs": {}, "scf": {}, "studios": {}, "metadata": {}}

    audit = {
        "new_month_label": month_label,
        "prior_state_last_month": committed.get("metadata", {}).get("last_actuals_month"),
        "consolidated_diffs": {},   # {sheet: {month: {account: (old,new)}}}
        "studio_diffs": {},          # {studio_code: {month: {account: (old,new)}}}
    }

    # --- Consolidated PL / BS / SCF (refresh every month from latest CSV) ---
    all_months = _all_months_from_csv(pl_csv)
    for sheet_name, csv_path in [("pl", pl_csv), ("bs", bs_csv), ("scf", scf_csv)]:
        sheet = committed.setdefault(sheet_name, {})
        per_sheet_diffs = {}
        for m in all_months:
            new_vals = _enrich(_csv_to_account_dict(csv_path, m), is_per_studio=False)
            old_vals = sheet.get(m, {})
            diffs = _diff_dict(old_vals, new_vals)
            if diffs:
                per_sheet_diffs[m] = diffs
            sheet[m] = new_vals
        if per_sheet_diffs:
            audit["consolidated_diffs"][sheet_name] = per_sheet_diffs

    # --- Per-studio P&Ls ---
    studios = committed.setdefault("studios", {})
    studio_files = sorted(studios_dir.glob(f"*_{month_tag}.csv"))
    for csv_path in studio_files:
        code = csv_path.stem.split(f"_{month_tag}")[0]
        studio_obj = studios.setdefault(code, {"name": code, "data": {}})
        studio_data = studio_obj.setdefault("data", {})
        # Each studio CSV may have its own subset of months (placeholder studios
        # like CDM/PS only show historical months they existed in).
        studio_months = _all_months_from_csv(csv_path)
        per_studio_diffs = {}
        for m in studio_months:
            raw = _csv_to_account_dict(csv_path, m, strict=False)
            if raw is None:
                continue
            new_vals = _enrich(raw, is_per_studio=True)
            old_vals = studio_data.get(m, {})
            diffs = _diff_dict(old_vals, new_vals)
            if diffs:
                per_studio_diffs[m] = diffs
            studio_data[m] = new_vals
        if per_studio_diffs:
            audit["studio_diffs"][code] = per_studio_diffs

    # --- Metadata ---
    now_iso = datetime.now().isoformat()
    metadata_file = FINANCIALS_DIR / f"metadata_{month_tag}.json"
    accountant_source = ""
    if metadata_file.exists():
        try:
            accountant_source = json.loads(metadata_file.read_text()).get("source_file", "")
        except Exception:
            pass

    committed["metadata"] = {
        **committed.get("metadata", {}),
        "month_tag": month_tag,
        "last_actuals_month": month_label,
        "imported_at": now_iso,
        "updated_at": now_iso,
        "source_file": accountant_source,
        "expense_source": source_label or accountant_source,
        # revenue_source is the same accountant package — QBO data already
        # includes the month's Saasant upload + any reclass JEs by the time
        # Crew sends the financial package.
        "revenue_source": accountant_source,
    }
    committed["_last_updated"] = now_iso

    # --- Write outputs ---
    DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    COMMITTED_PATH.write_text(json.dumps(committed, indent=2))

    LATEST_PATH.write_text(json.dumps({
        "month_tag": month_tag,
        "last_actuals_month": month_label,
        "updated_at": now_iso,
        "committed_actuals_path": str(COMMITTED_PATH.relative_to(PROJECT_ROOT)),
    }, indent=2))

    # --- Snapshot for audit trail ---
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / f"committed_actuals_{month_tag}.json"
    shutil.copy(COMMITTED_PATH, snapshot_path)
    audit["snapshot_path"] = str(snapshot_path)

    if verbose:
        _print_audit(audit, all_months, month_label)

    return audit


def _print_audit(audit: dict, all_months: list[str], new_month_label: str):
    print(f"\n{'='*70}")
    print(f"DASHBOARD UPDATE — Added {new_month_label}")
    print(f"{'='*70}")
    prior = audit["prior_state_last_month"]
    print(f"  Prior last actuals month: {prior}")
    print(f"  New last actuals month:   {new_month_label}")
    print(f"  Months in CSVs:           {len(all_months)}  ({', '.join(all_months)})")
    print(f"  Snapshot saved:           {Path(audit['snapshot_path']).name}")

    # Consolidated diffs by month/sheet
    if audit["consolidated_diffs"]:
        print("\n  Consolidated changes:")
        for sheet, per_month in audit["consolidated_diffs"].items():
            for m, diffs in per_month.items():
                # Skip the new month (everything is "new" for it)
                if m == new_month_label:
                    n_changed = len(diffs)
                    total = sum(abs(n) - abs(o) for o, n in diffs.values())
                    print(f"    {sheet.upper()} {m:>9} — {n_changed} accounts added (new month)")
                else:
                    n_changed = len(diffs)
                    biggest = sorted(diffs.items(),
                                    key=lambda x: -abs(x[1][1] - x[1][0]))[:3]
                    print(f"    {sheet.upper()} {m:>9} — {n_changed} accounts changed vs prior import")
                    for acct, (o, n) in biggest:
                        print(f"        {acct[:50]:<50}  {o:>12,.2f} → {n:>12,.2f}  (Δ {n-o:>+10,.2f})")

    # Studio diffs by month
    if audit["studio_diffs"]:
        print("\n  Per-studio changes (likely from MTT reclass or restatement):")
        for code, per_month in sorted(audit["studio_diffs"].items()):
            for m, diffs in per_month.items():
                if m == new_month_label:
                    continue  # new month — not a "change"
                # Focus on net-zero shifts (Δ summed ~0 = pure reallocation)
                deltas = [n - o for o, n in diffs.values()]
                net = sum(deltas)
                gross = sum(abs(d) for d in deltas)
                if gross < 0.5:
                    continue
                print(f"    {code} {m:>9}: net Δ {net:>+12,.2f}, gross moves ${gross:,.2f}")
                for acct, (o, n) in sorted(diffs.items(),
                                            key=lambda x: -abs(x[1][1] - x[1][0]))[:3]:
                    print(f"        {acct[:50]:<50}  {o:>12,.2f} → {n:>12,.2f}")

    print(f"\n  Files written:")
    print(f"    {COMMITTED_PATH.relative_to(PROJECT_ROOT)}")
    print(f"    {LATEST_PATH.relative_to(PROJECT_ROOT)}")
    print(f"    {Path(audit['snapshot_path']).relative_to(PROJECT_ROOT)}")
    print(f"{'='*70}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM (e.g. 2026-05)")
    ap.add_argument("--source-label", default=None,
                   help="Optional override for metadata.expense_source")
    args = ap.parse_args()
    y, m = map(int, args.month.split("-"))
    update_dashboard(y, m, source_label=args.source_label)


if __name__ == "__main__":
    main()
