"""
Apply September 2026 cash sales per studio.

Total sales is a CASH figure for the financial model + client view only (NOT the P&L).
Use Cat's spreadsheet **column K "Total Sales"** verbatim so the model ties to Cat's own
numbers (= MindBody Sales incl retail + ClassPass + Wellhub). Rev-rec/GL is unaffected.

Writes ONLY the dashboard JSON. The internal Excel model was retired 2026-08-24; the
external workbook (model-of-record) pulls from committed_actuals.json via
scripts/refresh_external_workbook.py.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

# Cat's Sep 2026 spreadsheet column K "Total Sales" per studio.
CAT_SEP_2026 = {
    "BK": 109267, "CC":  36019, "DN":  16085, "LF": 103010,
    "MR": 111265, "OP":  46218, "PH": 146809, "RH":  82506,
    "SB":  16728, "SM": 127321, "WP":    225, "WW":  51749,
}
CAT_TOTAL = round(sum(CAT_SEP_2026.values()), 2)   # 847,202 (per-studio sum)
TARGET_TOTAL = 847205                              # Cat's col K grand-total row ($3 rounding)

MONTH_DASH = "2026-09"

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_JSON = REPO_ROOT / "dashboard" / "data" / "baseline.json"
USER_OVERRIDES_JSON = REPO_ROOT / "dashboard" / "data" / "user_overrides.json"
DASHBOARD_JSON = REPO_ROOT / "dashboard" / "data" / "committed_actuals.json"


def update_baseline():
    print(f"\n[A0] Updating {BASELINE_JSON.relative_to(REPO_ROOT)}")
    data = json.loads(BASELINE_JSON.read_text())
    sf = data.setdefault("sales_forecast", {})
    for code, amt in CAT_SEP_2026.items():
        bucket = sf.setdefault(code, {})
        old = bucket.get(MONTH_DASH, 0)
        bucket[MONTH_DASH] = float(amt)
        print(f"   baseline[{code}][{MONTH_DASH}]: ${old:>12,.2f} → ${amt:>12,.2f}")
    BASELINE_JSON.write_text(json.dumps(data, indent=2))


def update_user_overrides():
    print(f"\n[A] Updating {USER_OVERRIDES_JSON.relative_to(REPO_ROOT)}")
    data = json.loads(USER_OVERRIDES_JSON.read_text())
    sf = data.setdefault("sales_forecast", {})
    for code, amt in CAT_SEP_2026.items():
        bucket = sf.setdefault(code, {})
        bucket[MONTH_DASH] = float(amt)
    data["_last_updated"] = datetime.now().isoformat()
    USER_OVERRIDES_JSON.write_text(json.dumps(data, indent=2))
    print(f"   user_overrides sales_forecast[*][{MONTH_DASH}] set for {len(CAT_SEP_2026)} studios")


def update_dashboard_json():
    print(f"\n[1/1] Updating {DASHBOARD_JSON.relative_to(REPO_ROOT)}")
    data = json.loads(DASHBOARD_JSON.read_text())
    csf = data.setdefault("client_sales_forecast", {})
    csfc = data.setdefault("client_sales_forecast_consolidated", {})
    ms = data.setdefault("monthly_sales", {})
    for code, amt in CAT_SEP_2026.items():
        bucket = csf.setdefault(code, {})
        bucket[MONTH_DASH] = float(amt)
    csfc[MONTH_DASH] = float(TARGET_TOTAL)
    ms[MONTH_DASH] = float(TARGET_TOTAL)
    print(f"   client_sales_forecast_consolidated[{MONTH_DASH}] = ${TARGET_TOTAL:,.2f}")
    print(f"   monthly_sales[{MONTH_DASH}]                     = ${TARGET_TOTAL:,.2f}")
    data["_last_updated"] = datetime.now().isoformat()
    DASHBOARD_JSON.write_text(json.dumps(data, indent=2))


def main():
    print("=" * 78)
    print(f"Apply September 2026 cash sales (Cat col K 'Total Sales', ${TARGET_TOTAL:,.2f})")
    print("=" * 78)
    update_baseline()
    update_user_overrides()
    update_dashboard_json()
    print(f"\n[Done] Dashboard JSON updated. Per-studio sum: ${CAT_TOTAL:,.2f} "
          f"(Cat reported total ${TARGET_TOTAL:,.2f}). Excel writes skipped (model retired).")


if __name__ == "__main__":
    main()
