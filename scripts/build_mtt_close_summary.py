"""Build the per-cohort MTT / PTT recognition summary workbook for the monthly close.

Cat requested this as a standing follow-up deliverable to the standard rev rec
package. It reconciles: cohort cash sales feeding this month's recognition,
current-month recognition split (visit-based vs cohort schedule spread), MoM
comparison against the immediately prior close, per-studio breakdown after the
MTT geographic remap, and forward-looking commentary on months without cohort
dates.

Usage
-----
    python scripts/build_mtt_close_summary.py --month 2026-06

The script queries live Snowflake for the current recognition, joins to the
FROZEN_MONTHLY_GL entry for the prior month, and writes an Excel workbook to
outputs/MTT_<Month><Year>_Summary_for_Cat.xlsx. Each cohort's config lives in
sql/v2/revenue_recognition_v2.sql §4B-MTT (MTT_COHORT_WINDOWS + class dates).

Reconciliation gotcha
---------------------
Cash sales are NET (after discounts). GL revenue is GROSS. Never subtract them
without labeling both sides. See feedback_mighty_pilates_mtt_recognition memory
for the mechanic.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font, PatternFill

from pipeline.connection import get_connection, execute_query_df


COHORTS = {
    "Winter 2026":   ("2025-12-01", "2026-03-22", 12, ["2026-02-07","2026-02-08","2026-02-14","2026-02-15","2026-02-21","2026-02-22","2026-02-28","2026-03-01","2026-03-14","2026-03-15","2026-03-21","2026-03-22"]),
    "Summer 2026":   ("2026-03-23", "2026-06-28", 12, ["2026-05-16","2026-05-17","2026-05-23","2026-05-24","2026-05-30","2026-05-31","2026-06-06","2026-06-07","2026-06-20","2026-06-21","2026-06-27","2026-06-28"]),
    "Fall 2026":     ("2026-06-29", "2026-11-15", 12, ["2026-10-03","2026-10-04","2026-10-10","2026-10-11","2026-10-17","2026-10-18","2026-10-24","2026-10-25","2026-11-07","2026-11-08","2026-11-14","2026-11-15"]),
    "Winter 2027":   ("2026-11-16", "2027-03-22", 12, ["2027-02-07","2027-02-08","2027-02-14","2027-02-15","2027-02-21","2027-02-22","2027-02-28","2027-03-01","2027-03-14","2027-03-15","2027-03-21","2027-03-22"]),
}


def _cohort_for_month(month_ym: str) -> tuple[str, list[str]] | None:
    """Return (cohort_name, class_dates_in_this_month) if any cohort's class dates fall in this month."""
    for name, (_, _, _, dates) in COHORTS.items():
        in_month = [d for d in dates if d.startswith(month_ym)]
        if in_month:
            return name, in_month
    return None


def _cohort_sale_window(cohort_name: str) -> tuple[str, str]:
    start, end, _, _ = COHORTS[cohort_name]
    return start, end


def _cash_sales_by_month(conn, sale_start: str, sale_end: str) -> pd.DataFrame:
    return execute_query_df(conn, f"""
        SELECT TO_VARCHAR(SALE_DATE, 'YYYY-MM') AS SALE_MONTH,
               COUNT(*) AS PACKS_SOLD,
               SUM(NET_PACKAGE_PRICE) AS CASH_SALES_NET
        FROM PRICING_PER_VISIT_UNIQ
        WHERE (REVENUE_CATEGORY = 'Mighty Teacher Training'
               OR PRODUCT_DESCRIPTION ILIKE '%teacher%training%'
               OR PRODUCT_DESCRIPTION ILIKE '%TTT%')
          AND SALE_DATE >= '{sale_start}'
          AND SALE_DATE <= '{sale_end}'
          AND NET_PACKAGE_PRICE > 0
        GROUP BY 1 ORDER BY 1
    """)


def _month_recognition(conn, month_ym: str) -> pd.DataFrame:
    return execute_query_df(conn, f"""
        SELECT EVENT_TYPE,
               SUM(GROSS_EARNED_REVENUE) AS GROSS,
               SUM(NET_EARNED_REVENUE) AS NET,
               COUNT(*) AS N_EVENTS
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE TO_VARCHAR(EVENT_DATE, 'YYYY-MM') = '{month_ym}'
          AND SERVICE_TYPE = 'Mighty Teacher Training'
        GROUP BY 1
    """)


def _prior_month_frozen(conn, prior_month_ym: str) -> float:
    df = execute_query_df(conn, f"""
        SELECT SUM(AMOUNT) AS FROZEN_GROSS
        FROM EARNED_REVENUE_ANALYTICS.FROZEN_MONTHLY_GL
        WHERE MONTH_YM = '{prior_month_ym}' AND GL_CODE = '401004'
    """)
    return float(df.iloc[0, 0] or 0) if len(df) else 0.0


def _month_by_studio(conn, month_ym: str) -> pd.DataFrame:
    return execute_query_df(conn, f"""
        SELECT STUDIO_NAME, SUM(AMOUNT) AS AMOUNT
        FROM EARNED_REVENUE_ANALYTICS.FROZEN_MONTHLY_GL
        WHERE MONTH_YM = '{month_ym}' AND GL_CODE = '401004'
        GROUP BY 1 ORDER BY 2 DESC NULLS LAST
    """)


def build(month_ym: str, out_dir: Path) -> Path:
    conn = get_connection()

    cohort_info = _cohort_for_month(month_ym)
    if not cohort_info:
        print(f"[INFO] No cohort class dates fall in {month_ym}. Expected zero MTT recognition.")
        cohort_name, class_dates_this_month = "(none)", []
    else:
        cohort_name, class_dates_this_month = cohort_info

    if cohort_name != "(none)":
        sale_start, sale_end = _cohort_sale_window(cohort_name)
        cash = _cash_sales_by_month(conn, sale_start, sale_end)
    else:
        cash = pd.DataFrame(columns=["SALE_MONTH", "PACKS_SOLD", "CASH_SALES_NET"])

    recog = _month_recognition(conn, month_ym)

    # Prior month frozen GL for the same account
    y, m = map(int, month_ym.split("-"))
    prior_month_ym = f"{y - 1 if m == 1 else y:04d}-{12 if m == 1 else m - 1:02d}"
    prior_gross = _prior_month_frozen(conn, prior_month_ym)

    by_studio = _month_by_studio(conn, month_ym)

    conn.close()

    # ---- Assemble sheets ----
    total_cash = float(cash["CASH_SALES_NET"].sum()) if len(cash) else 0.0
    this_gross = float(recog["GROSS"].sum()) if len(recog) else 0.0
    this_net = float(recog["NET"].sum()) if len(recog) else 0.0
    total_recog = prior_gross + this_gross

    overview = pd.DataFrame([
        ["Cohort", cohort_name],
        ["Prior month recognition (frozen GL 401004, GROSS)", f"${prior_gross:,.2f}"],
        [f"{month_ym} recognition (GL 401004, GROSS)", f"${this_gross:,.2f}"],
        ["Total recognized prior + this month (GROSS)", f"${total_recog:,.2f}"],
        ["Cohort cash sales (NET after discounts)", f"${total_cash:,.2f}"],
        ["", ""],
        ["Method", "Hybrid: visits reduce residual first; residual spreads evenly across cohort's 12 class dates"],
        ["Breakage", "None on MTT"],
        ["Reconciliation gotcha", "Cash sales = NET, GL revenue = GROSS. Do not subtract without labeling both sides."],
    ], columns=["Item", "Value"])

    reconciliation = pd.DataFrame([
        [f"Cohort cash sales (NET, after discounts)", total_cash, f"{len(cash)} sale month(s)"],
        ["", "", ""],
        [f"{prior_month_ym} recognition (frozen GL 401004, GROSS)", prior_gross, "Shipped in prior close"],
        [f"{month_ym} recognition (GL 401004, GROSS)", this_gross, "This close"],
        ["Total recognized (GROSS)", total_recog, ""],
    ], columns=["Line", "Amount", "Notes"])

    class_dates_df = pd.DataFrame({
        "Class Date": class_dates_this_month,
        "Recognized In": [f"{month_ym} close"] * len(class_dates_this_month),
    })

    outpath = out_dir / f"MTT_{month_ym.replace('-', '')}_Summary_for_Cat.xlsx"
    out_dir.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(outpath, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Overview", index=False)
        reconciliation.to_excel(w, sheet_name="Recognition Reconciliation", index=False)
        cash.to_excel(w, sheet_name="Cohort Cash Sales by Month", index=False)
        class_dates_df.to_excel(w, sheet_name="Cohort Class Dates This Month", index=False)
        recog.to_excel(w, sheet_name="Recognition by Event Type", index=False)
        by_studio.to_excel(w, sheet_name="By Studio (post remap)", index=False)
        hf = PatternFill(start_color="305496", end_color="305496", fill_type="solid")
        fnt = Font(bold=True, color="FFFFFF")
        for sheet in w.sheets.values():
            for cell in sheet[1]:
                cell.fill = hf
                cell.font = fnt
            for col in sheet.columns:
                mx = max((len(str(c.value or "")) for c in col), default=10)
                sheet.column_dimensions[col[0].column_letter].width = min(95, max(14, mx + 2))
    print(f"[OK] {outpath}")
    return outpath


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True, help="Close month in YYYY-MM format")
    p.add_argument("--out", default=str(Path(__file__).parent.parent / "outputs"),
                   help="Output directory")
    args = p.parse_args()
    build(args.month, Path(args.out))


if __name__ == "__main__":
    main()
