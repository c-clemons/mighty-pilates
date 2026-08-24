"""
Membership & Churn Analytics Report.

Tabs:
1. Membership Summary — active/suspended/churned by studio, current snapshot
2. Churn Trends — monthly new/reactivated/churned over trailing 12 months
3. Churn by Studio — monthly churn counts per studio
4. Membership Mix — breakdown by membership type (MMP, Founders, Student, etc.)
5. At-Risk Members — members with churn risk flags from MART_CLIENTS
6. Retention Cohorts — first-purchase month cohorts, % still active
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def generate_membership_report(conn, output_dir: str = None) -> str:
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    today = datetime.now()
    print(f"Generating Membership & Churn Report...")

    # === 1. Current Membership Snapshot ===
    print("  Loading membership snapshot...")
    snapshot = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
            SUM(IS_ACTIVE_MEMBERSHIP) AS ACTIVE,
            SUM(IS_SUSPENDED_MEMBERSHIP) AS SUSPENDED,
            SUM(IS_CHURN_MEMBERSHIP) AS CHURNED_TODAY,
            SUM(IS_NEW_MEMBERSHIP) AS NEW_TODAY,
            SUM(IS_REACTIVATED_MEMBERSHIP) AS REACTIVATED_TODAY,
            COUNT(DISTINCT CLIENT_ID) AS UNIQUE_MEMBERS
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE = CURRENT_DATE()
        GROUP BY 1
        ORDER BY ACTIVE DESC
    """)

    # Add totals row
    totals = snapshot.select_dtypes(include='number').sum()
    totals_row = pd.DataFrame([['ALL STUDIOS'] + totals.tolist()], columns=snapshot.columns)
    snapshot = pd.concat([totals_row, snapshot], ignore_index=True)

    # === 2. Monthly Churn Trends (trailing 12 months) ===
    print("  Loading churn trends...")
    churn_trends = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(DATE, 'YYYY-MM') AS MONTH,
            SUM(IS_NEW_MEMBERSHIP) AS NEW_MEMBERS,
            SUM(IS_REACTIVATED_MEMBERSHIP) AS REACTIVATED,
            SUM(IS_CHURN_MEMBERSHIP) AS CHURNED,
            SUM(CASE WHEN DATE = DATE_TRUNC('MONTH', DATE) THEN IS_ACTIVE_MEMBERSHIP END) AS ACTIVE_BOM,
            SUM(CASE WHEN DATE = LAST_DAY(DATE) THEN IS_ACTIVE_MEMBERSHIP END) AS ACTIVE_EOM,
            SUM(CASE WHEN DATE = LAST_DAY(DATE) THEN IS_SUSPENDED_MEMBERSHIP END) AS SUSPENDED_EOM
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE >= DATE_TRUNC('MONTH', DATEADD(MONTH, -12, CURRENT_DATE()))
        GROUP BY 1
        ORDER BY 1
    """)
    # Calculate net change and churn rate (churn during month over the beginning-of-month base)
    if not churn_trends.empty:
        churn_trends["NET_CHANGE"] = churn_trends["NEW_MEMBERS"] + churn_trends["REACTIVATED"] - churn_trends["CHURNED"]
        churn_trends["CHURN_RATE_PCT"] = (churn_trends["CHURNED"] / churn_trends["ACTIVE_BOM"] * 100).round(2)
        # An in-progress month has no month-end row yet; its partial churn count over a full
        # BOM base would understate the rate and read as a trend break, so leave it blank.
        churn_trends["CHURN_RATE_PCT"] = churn_trends["CHURN_RATE_PCT"].where(churn_trends["ACTIVE_EOM"].notna())

    # === 3. Churn by Studio (monthly) ===
    print("  Loading churn by studio...")
    churn_by_studio = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(DATE, 'YYYY-MM') AS MONTH,
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
            SUM(IS_CHURN_MEMBERSHIP) AS CHURNED,
            SUM(IS_NEW_MEMBERSHIP) AS NEW_MEMBERS,
            SUM(CASE WHEN DATE = DATE_TRUNC('MONTH', DATE) THEN IS_ACTIVE_MEMBERSHIP END) AS ACTIVE_BOM,
            SUM(CASE WHEN DATE = LAST_DAY(DATE) THEN IS_ACTIVE_MEMBERSHIP END) AS ACTIVE_EOM
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE >= DATE_TRUNC('MONTH', DATEADD(MONTH, -12, CURRENT_DATE()))
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)

    # Pivot churn by studio
    churn_pvt = pd.DataFrame()
    if not churn_by_studio.empty:
        churn_pvt = churn_by_studio.pivot_table(
            index="STUDIO", columns="MONTH", values="CHURNED",
            aggfunc="sum", fill_value=0
        ).sort_index()
        churn_pvt["TOTAL"] = churn_pvt.sum(axis=1)

    # === 4. Membership Mix ===
    print("  Loading membership mix...")
    mix = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
            MEMBERSHIP_NAME,
            SUM(IS_ACTIVE_MEMBERSHIP) AS ACTIVE,
            SUM(IS_SUSPENDED_MEMBERSHIP) AS SUSPENDED,
            SUM(IS_CHURN_MEMBERSHIP) AS CHURNED,
            COUNT(DISTINCT CLIENT_ID) AS UNIQUE_CLIENTS
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE = CURRENT_DATE()
          AND IS_ACTIVE_MEMBERSHIP = 1
        GROUP BY 1, 2
        ORDER BY ACTIVE DESC
    """)

    # === 5. At-Risk Members ===
    print("  Loading at-risk members...")
    at_risk = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            c.NAME AS CLIENT_NAME,
            c.CHURN_RISK,
            c.CHURN_RISK_FACTORS,
            c.TOTAL_VISITS,
            c.TOTAL_SALES,
            c.LAST_VISIT_DATE,
            c.CURRENT_MEMBER_STATUS,
            c.PRIMARY_MEMBERSHIP,
            DATEDIFF(DAY, c.LAST_VISIT_DATE, CURRENT_DATE()) AS DAYS_SINCE_LAST_VISIT
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.CHURN_RISK IS NOT NULL
          AND c.CHURN_RISK IN ('High', 'Medium')
          AND c.CURRENT_MEMBER_STATUS = 'Active'
        ORDER BY c.TOTAL_SALES DESC
        LIMIT 200
    """)

    # === 6. Retention Cohorts ===
    print("  Loading retention cohorts...")
    cohorts = execute_query_df(conn, f"""
        WITH first_activation AS (
            SELECT
                CLIENT_ID,
                {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
                TO_VARCHAR(FIRST_MEMBERSHIP_ACTIVATION_DATE, 'YYYY-MM') AS COHORT_MONTH,
                FIRST_MEMBERSHIP_ACTIVATION_DATE
            FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
            WHERE DATE = CURRENT_DATE()
              AND FIRST_MEMBERSHIP_ACTIVATION_DATE IS NOT NULL
            GROUP BY 1, 2, 3, 4
        ),
        cohort_status AS (
            SELECT
                fa.COHORT_MONTH,
                COUNT(DISTINCT fa.CLIENT_ID) AS COHORT_SIZE,
                COUNT(DISTINCT CASE WHEN m.IS_ACTIVE_MEMBERSHIP = 1 THEN fa.CLIENT_ID END) AS STILL_ACTIVE,
                ROUND(COUNT(DISTINCT CASE WHEN m.IS_ACTIVE_MEMBERSHIP = 1 THEN fa.CLIENT_ID END) * 100.0
                      / NULLIF(COUNT(DISTINCT fa.CLIENT_ID), 0), 1) AS RETENTION_PCT
            FROM first_activation fa
            LEFT JOIN PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS m
              ON m.CLIENT_ID = fa.CLIENT_ID
              AND m.STUDIO_NAME = fa.STUDIO
              AND m.DATE = CURRENT_DATE()
            WHERE fa.COHORT_MONTH >= TO_VARCHAR(DATEADD(MONTH, -24, CURRENT_DATE()), 'YYYY-MM')
            GROUP BY fa.COHORT_MONTH
            ORDER BY fa.COHORT_MONTH
        )
        SELECT * FROM cohort_status
    """)

    # === Build Excel ===
    print("  Building Excel workbook...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_Membership_Churn_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as w:
        wb = w.book
        money = wb.add_format({"num_format": "#,##0.00"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        pct_fmt = wb.add_format({"num_format": "0.0%"})

        def _write_tab(df, name, col_widths=None):
            if df.empty:
                return
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for i, col in enumerate(df.columns):
                ws.write(0, i, col, header_fmt)
            if col_widths:
                for i, width in enumerate(col_widths):
                    ws.set_column(i, i, width)

        _write_tab(snapshot, "Membership Snapshot", [28, 10, 12, 14, 10, 14, 16])
        _write_tab(churn_trends, "Churn Trends", [10, 14, 14, 10, 12, 12, 14, 12, 14])

        if not churn_pvt.empty:
            churn_pvt.to_excel(w, sheet_name="Churn by Studio")
            ws = w.sheets["Churn by Studio"]
            ws.set_row(0, None, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 20, 10)

        _write_tab(mix, "Membership Mix", [28, 45, 10, 12, 10, 16])
        _write_tab(at_risk, "At-Risk Members", [28, 25, 10, 35, 12, 14, 14, 14, 30, 16])
        _write_tab(cohorts, "Retention Cohorts", [14, 12, 12, 14])

    print(f"  Saved: {filepath}")
    return str(filepath)
