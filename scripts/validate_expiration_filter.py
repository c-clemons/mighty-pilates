"""
Quantify the impact of the PROPOSED visit-expiration filter on May 2026.

Drafted 2026-06-11. Companion to sql/PROPOSED_visit_expiration_filter.sql.

What it does:
  - Pulls May 2026 visits that linked to packages whose EXPIRATION_DATE is
    BEFORE the visit date (these are the events the filter would drop).
  - Sums the per-visit revenue that would no longer recognize, broken out by:
      * Studio × Revenue Category × Link Type
      * Sale-month vintage (M0 through M-7+) to confirm where it lands
      * Studio totals for "before vs after" comparison
  - Does NOT mutate any production table or re-run the model.

Output: prints to stdout. Optionally writes a CSV to outputs/.

Usage:
  python scripts/validate_expiration_filter.py
  python scripts/validate_expiration_filter.py --month 2026-05
  python scripts/validate_expiration_filter.py --month 2026-05 --csv
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from pipeline.connection import get_connection, execute_query_df

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", None)


def _month_bounds(month_arg: str):
    """Return (first_day, last_day, year, month) for a YYYY-MM string."""
    import calendar
    y, m = map(int, month_arg.split("-"))
    last = calendar.monthrange(y, m)[1]
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}", y, m


def pull_dropped_visits(conn, start: str, end: str) -> pd.DataFrame:
    """
    Return visits that the proposed filter would drop, with the dollar amount
    the current model is recognizing for each one.
    """
    sql = f"""
    WITH cm_visits AS (
      -- All non-cancelled, non-missed visits in the close month
      SELECT vl.UNIQUE_VISIT_REF_NO,
             vl.UNIQUE_PACKAGE_ID_LNK     AS PACKAGE_ID,
             REPLACE(vl.STUDIO_NAME,'Mighty Pilates ','') AS STUDIO,
             vl.VISIT_DATE::DATE          AS VISIT_DATE,
             vl.LINK_TYPE
      FROM EARNED_REVENUE_ANALYTICS.VISITS_LINKED vl
      WHERE vl.VISIT_DATE BETWEEN '{start}' AND '{end}'
        AND vl.IS_CANCELLED = 0
        AND vl.IS_MISSED    = 0
    ),
    -- Registry holds the expiration date the model used at last freeze
    reg AS (
      SELECT PACKAGE_ID, EXPIRATION_DATE::DATE AS EXPIRATION_DATE,
             EXPIRATION_SOURCE, START_DATE::DATE AS START_DATE,
             PACKAGE_DURATION_DAYS, REVENUE_CATEGORY
      FROM EARNED_REVENUE_ANALYTICS.PACKAGE_EXPIRATION_REGISTRY
    ),
    priced AS (
      SELECT PACKAGE_ID, NET_REVENUE_PER_VISIT
      FROM EARNED_REVENUE_ANALYTICS.PRICING_PER_VISIT_UNIQ
    )
    SELECT v.STUDIO, v.VISIT_DATE, v.LINK_TYPE,
           r.REVENUE_CATEGORY,
           r.EXPIRATION_DATE,
           r.START_DATE,
           r.EXPIRATION_SOURCE,
           r.PACKAGE_DURATION_DAYS,
           COALESCE(p.NET_REVENUE_PER_VISIT, 0) AS REV_PER_VISIT,
           v.PACKAGE_ID
    FROM cm_visits v
    JOIN reg     r ON r.PACKAGE_ID = v.PACKAGE_ID
    LEFT JOIN priced p ON p.PACKAGE_ID = v.PACKAGE_ID
    WHERE v.VISIT_DATE > r.EXPIRATION_DATE   -- the filter's effect
    """
    return execute_query_df(conn, sql)


def pull_total_usage(conn, start: str, end: str) -> pd.DataFrame:
    """Current model's USAGE revenue in the close month (the baseline)."""
    sql = f"""
    SELECT REPLACE(STUDIO_NAME,'Mighty Pilates ','') AS STUDIO,
           SERVICE_TYPE,
           SUM(NET_EARNED_REVENUE) AS USAGE_REV
    FROM EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL
    WHERE EVENT_TYPE = 'Usage'
      AND EVENT_DATE BETWEEN '{start}' AND '{end}'
    GROUP BY 1, 2
    """
    return execute_query_df(conn, sql)


def vintage_label(visit_date, close_first):
    if pd.isna(visit_date):
        return "Unknown"
    months = (close_first.year - visit_date.year) * 12 + (close_first.month - visit_date.month)
    if months <= 0:
        return "M0"
    if months >= 7:
        return "M-7+"
    return f"M-{months}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM (defaults to prior month)")
    ap.add_argument("--csv", action="store_true", help="Write detail CSV to outputs/")
    args = ap.parse_args()

    if not args.month:
        from datetime import datetime, timedelta
        today = datetime.now()
        first = today.replace(day=1)
        prior = first - timedelta(days=1)
        args.month = prior.strftime("%Y-%m")

    start, end, year, month = _month_bounds(args.month)
    close_first = date(year, month, 1)

    print(f"\n{'='*78}")
    print(f"PROPOSED visit-expiration filter — IMPACT FORECAST for {args.month}")
    print(f"{'='*78}\n")

    conn = get_connection()
    try:
        dropped = pull_dropped_visits(conn, start, end)
        usage   = pull_total_usage(conn, start, end)
    finally:
        conn.close()

    dropped["REV_PER_VISIT"] = dropped["REV_PER_VISIT"].astype(float)
    # Vintage by package SALE_DATE (matches waterfall semantics)
    dropped["VINTAGE"] = dropped["START_DATE"].apply(lambda d: vintage_label(d, close_first))

    total_dropped = float(dropped["REV_PER_VISIT"].sum())
    n_visits      = len(dropped)
    n_pkgs        = dropped["PACKAGE_ID"].nunique()
    current_usage_total = float(usage["USAGE_REV"].astype(float).sum())
    new_usage_total     = current_usage_total - total_dropped
    pct_reduction = (total_dropped / current_usage_total) if current_usage_total else 0.0

    print(f"Headline:")
    print(f"  Current month USAGE revenue (model output) : ${current_usage_total:,.2f}")
    print(f"  Visits the filter would drop               : {n_visits:,} visits across {n_pkgs:,} packages")
    print(f"  Revenue that would no longer recognize     : ${total_dropped:,.2f}")
    print(f"  Reduction in USAGE revenue                 : {pct_reduction*100:.2f}%")
    print(f"  Adjusted USAGE revenue post-filter         : ${new_usage_total:,.2f}")
    print()

    if total_dropped == 0:
        print("No visits past expiration found. Filter would have zero effect this month.")
        return

    # By sale-month vintage
    print("=== Dropped revenue by VINTAGE (sale month relative to close month) ===")
    vint_order = ["M0", "M-1", "M-2", "M-3", "M-4", "M-5", "M-6", "M-7+", "Unknown"]
    g = dropped.groupby("VINTAGE")["REV_PER_VISIT"].agg(["count","sum"]).reindex(vint_order, fill_value=0)
    g.columns = ["Visits", "Revenue"]
    g["% of dropped"] = (g["Revenue"] / total_dropped) if total_dropped else 0.0
    g["% of dropped"] = g["% of dropped"].map(lambda x: f"{x*100:.1f}%")
    g["Revenue"] = g["Revenue"].map(lambda x: f"${x:,.2f}")
    print(g.to_string())

    print()
    print("=== Dropped revenue by STUDIO × REVENUE_CATEGORY ===")
    h = dropped.groupby(["STUDIO","REVENUE_CATEGORY"]).agg(
        visits=("REV_PER_VISIT", "size"),
        revenue=("REV_PER_VISIT", "sum"),
    ).reset_index().sort_values("revenue", ascending=False)
    h["revenue"] = h["revenue"].map(lambda x: f"${x:,.2f}")
    print(h.to_string(index=False))

    print()
    print("=== Dropped revenue by LINK_TYPE (HARD vs SOFT_GLOBAL — diagnoses MindBody contamination) ===")
    lt = dropped.groupby("LINK_TYPE")["REV_PER_VISIT"].agg(["count","sum"]).rename(
        columns={"count":"Visits","sum":"Revenue"})
    lt["% of dropped"] = lt["Revenue"] / total_dropped
    lt["% of dropped"] = lt["% of dropped"].map(lambda x: f"{x*100:.1f}%")
    lt["Revenue"] = lt["Revenue"].map(lambda x: f"${x:,.2f}")
    print(lt.to_string())

    print()
    print("=== Dropped revenue by REGISTRY EXPIRATION_SOURCE ===")
    es = dropped.groupby("EXPIRATION_SOURCE")["REV_PER_VISIT"].agg(["count","sum"]).rename(
        columns={"count":"Visits","sum":"Revenue"})
    es["% of dropped"] = es["Revenue"] / total_dropped
    es["% of dropped"] = es["% of dropped"].map(lambda x: f"{x*100:.1f}%")
    es["Revenue"] = es["Revenue"].map(lambda x: f"${x:,.2f}")
    print(es.to_string())

    print()
    print("=== Days past expiration — distribution ===")
    dropped["DAYS_PAST"] = (pd.to_datetime(dropped["VISIT_DATE"]) -
                          pd.to_datetime(dropped["EXPIRATION_DATE"])).dt.days
    bins = [0, 30, 60, 90, 180, 365, 9999]
    labels = ["1-30d","31-60d","61-90d","91-180d","181-365d","366d+"]
    dropped["DAYS_BUCKET"] = pd.cut(dropped["DAYS_PAST"], bins=bins, labels=labels, include_lowest=True)
    db = dropped.groupby("DAYS_BUCKET", observed=False)["REV_PER_VISIT"].agg(["count","sum"]).rename(
        columns={"count":"Visits","sum":"Revenue"})
    db["% of dropped"] = db["Revenue"] / total_dropped
    db["% of dropped"] = db["% of dropped"].map(lambda x: f"{x*100:.1f}%")
    db["Revenue"] = db["Revenue"].map(lambda x: f"${x:,.2f}")
    print(db.to_string())

    if args.csv:
        out_dir = Path(__file__).resolve().parents[1] / "outputs"
        out_dir.mkdir(exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = out_dir / f"expiration_filter_impact_{args.month}_{stamp}.csv"
        dropped.to_csv(csv_path, index=False)
        print(f"\nDetail CSV saved: {csv_path}")


if __name__ == "__main__":
    main()
