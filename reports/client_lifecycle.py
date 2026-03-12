"""
Client Lifecycle & LTV Report.

Tabs:
1. Client Overview — total clients, visits, revenue by studio
2. Top Clients by LTV — lifetime revenue, visits, tenure
3. New Client Acquisition — monthly new clients by studio (first sale date)
4. Client Activity Segments — active/lapsed/dormant/lost by studio
5. Visit Frequency Distribution — how often clients visit per month
6. Predicted Big Spenders — clients flagged by MART_CLIENTS
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def generate_client_lifecycle_report(conn, output_dir: str = None) -> str:
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    print("Generating Client Lifecycle & LTV Report...")

    # === 1. Client Overview by Studio ===
    print("  Loading client overview...")
    overview = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            COUNT(*) AS TOTAL_CLIENTS,
            SUM(CASE WHEN c.INACTIVE_FLAG = 0 THEN 1 ELSE 0 END) AS ACTIVE_CLIENTS,
            SUM(CASE WHEN c.INACTIVE_FLAG = 1 THEN 1 ELSE 0 END) AS INACTIVE_CLIENTS,
            ROUND(AVG(c.TOTAL_VISITS), 1) AS AVG_LIFETIME_VISITS,
            ROUND(AVG(c.TOTAL_SALES), 2) AS AVG_LIFETIME_REVENUE,
            ROUND(SUM(c.TOTAL_SALES), 2) AS TOTAL_LIFETIME_REVENUE,
            ROUND(AVG(c.PROFILE_AGE_MONTHS), 1) AS AVG_TENURE_MONTHS,
            SUM(c.YTD_VISITS) AS YTD_VISITS,
            ROUND(SUM(c.YTD_SALES), 2) AS YTD_REVENUE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.STUDIO_NAME IS NOT NULL
        GROUP BY 1
        ORDER BY TOTAL_LIFETIME_REVENUE DESC
    """)

    # Add totals
    if not overview.empty:
        # Convert Snowflake Decimal types to float so pandas recognizes them as numeric
        for col in overview.columns:
            if col != "STUDIO":
                overview[col] = pd.to_numeric(overview[col], errors="coerce")
        num_cols = overview.select_dtypes(include='number')
        totals = num_cols.sum()
        # Recalculate averages
        totals["AVG_LIFETIME_VISITS"] = num_cols["AVG_LIFETIME_VISITS"].mean().round(1)
        totals["AVG_LIFETIME_REVENUE"] = num_cols["AVG_LIFETIME_REVENUE"].mean().round(2)
        totals["AVG_TENURE_MONTHS"] = num_cols["AVG_TENURE_MONTHS"].mean().round(1)
        totals_row = pd.DataFrame([["ALL STUDIOS"] + totals.tolist()], columns=overview.columns)
        overview = pd.concat([totals_row, overview], ignore_index=True)

    # === 2. Top Clients by LTV ===
    print("  Loading top clients by LTV...")
    top_ltv = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            c.NAME AS CLIENT_NAME,
            c.TOTAL_SALES AS LIFETIME_REVENUE,
            c.TOTAL_VISITS AS LIFETIME_VISITS,
            c.PROFILE_AGE_MONTHS AS TENURE_MONTHS,
            c.FIRST_SALE_DATE,
            c.LAST_VISIT_DATE,
            c.VISITS_REMAINING,
            c.CURRENT_MEMBER_STATUS,
            c.PRIMARY_MEMBERSHIP,
            ROUND(c.TOTAL_SALES / NULLIF(c.TOTAL_VISITS, 0), 2) AS REV_PER_VISIT,
            ROUND(c.TOTAL_SALES / NULLIF(c.PROFILE_AGE_MONTHS, 0), 2) AS MONTHLY_LTV
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.TOTAL_SALES > 0
          AND c.STUDIO_NAME IS NOT NULL
        ORDER BY c.TOTAL_SALES DESC
        LIMIT 500
    """)

    # === 3. New Client Acquisition (monthly) ===
    print("  Loading new client acquisition...")
    acquisition = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(c.FIRST_SALE_DATE, 'YYYY-MM') AS MONTH,
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            COUNT(*) AS NEW_CLIENTS,
            ROUND(AVG(c.TOTAL_SALES), 2) AS AVG_LTV_SO_FAR,
            ROUND(AVG(c.TOTAL_VISITS), 1) AS AVG_VISITS_SO_FAR
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.FIRST_SALE_DATE >= DATEADD(MONTH, -12, CURRENT_DATE())
          AND c.STUDIO_NAME IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)

    # Pivot new clients
    acq_pvt = pd.DataFrame()
    if not acquisition.empty:
        acq_pvt = acquisition.pivot_table(
            index="STUDIO", columns="MONTH", values="NEW_CLIENTS",
            aggfunc="sum", fill_value=0
        ).sort_index()
        acq_pvt["TOTAL"] = acq_pvt.sum(axis=1)
        # Add all-studios row
        acq_pvt.loc["ALL STUDIOS"] = acq_pvt.sum()
        acq_pvt = acq_pvt.sort_values("TOTAL", ascending=False)

    # === 4. Client Activity Segments ===
    print("  Loading activity segments...")
    segments = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            CASE
                WHEN c.LAST_VISIT_DATE >= DATEADD(DAY, -30, CURRENT_DATE()) THEN 'Active (30d)'
                WHEN c.LAST_VISIT_DATE >= DATEADD(DAY, -60, CURRENT_DATE()) THEN 'Lapsed (30-60d)'
                WHEN c.LAST_VISIT_DATE >= DATEADD(DAY, -90, CURRENT_DATE()) THEN 'At Risk (60-90d)'
                WHEN c.LAST_VISIT_DATE >= DATEADD(DAY, -180, CURRENT_DATE()) THEN 'Dormant (90-180d)'
                ELSE 'Lost (180d+)'
            END AS SEGMENT,
            COUNT(*) AS CLIENT_COUNT,
            ROUND(SUM(c.TOTAL_SALES), 2) AS LIFETIME_REVENUE,
            ROUND(AVG(c.TOTAL_VISITS), 1) AS AVG_VISITS
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.LAST_VISIT_DATE IS NOT NULL
          AND c.STUDIO_NAME IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1,
            CASE SEGMENT
                WHEN 'Active (30d)' THEN 1
                WHEN 'Lapsed (30-60d)' THEN 2
                WHEN 'At Risk (60-90d)' THEN 3
                WHEN 'Dormant (90-180d)' THEN 4
                ELSE 5
            END
    """)

    # === 5. Visit Frequency Distribution ===
    print("  Loading visit frequency...")
    frequency = execute_query_df(conn, f"""
        WITH monthly_visits AS (
            SELECT
                {CANON_STUDIO_SQL}(v.STUDIO_NAME) AS STUDIO,
                v.CLIENT_ID,
                TO_VARCHAR(v.CLASS_DATE, 'YYYY-MM') AS MONTH,
                COUNT(*) AS VISITS
            FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
            WHERE v.CLASS_DATE >= DATEADD(MONTH, -3, CURRENT_DATE())
              AND v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
            GROUP BY 1, 2, 3
        )
        SELECT
            STUDIO,
            CASE
                WHEN VISITS = 1 THEN '1 visit'
                WHEN VISITS BETWEEN 2 AND 4 THEN '2-4 visits'
                WHEN VISITS BETWEEN 5 AND 8 THEN '5-8 visits'
                WHEN VISITS BETWEEN 9 AND 12 THEN '9-12 visits'
                WHEN VISITS BETWEEN 13 AND 20 THEN '13-20 visits'
                ELSE '20+ visits'
            END AS FREQUENCY_BUCKET,
            COUNT(*) AS CLIENT_MONTHS,
            ROUND(AVG(VISITS), 1) AS AVG_VISITS_IN_BUCKET
        FROM monthly_visits
        GROUP BY 1, 2
        ORDER BY 1,
            CASE FREQUENCY_BUCKET
                WHEN '1 visit' THEN 1
                WHEN '2-4 visits' THEN 2
                WHEN '5-8 visits' THEN 3
                WHEN '9-12 visits' THEN 4
                WHEN '13-20 visits' THEN 5
                ELSE 6
            END
    """)

    # === 6. Predicted Big Spenders ===
    print("  Loading predicted big spenders...")
    big_spenders = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(c.STUDIO_NAME) AS STUDIO,
            c.NAME AS CLIENT_NAME,
            c.PREDICTED_BIG_SPENDER,
            c.TOTAL_SALES AS LIFETIME_REVENUE,
            c.TOTAL_VISITS AS LIFETIME_VISITS,
            c.LAST_VISIT_DATE,
            c.CURRENT_MEMBER_STATUS,
            c.PRIMARY_MEMBERSHIP,
            c.CHURN_RISK
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_CLIENTS c
        WHERE c.PREDICTED_BIG_SPENDER = 1
          AND c.STUDIO_NAME IS NOT NULL
        ORDER BY c.TOTAL_SALES DESC
        LIMIT 200
    """)

    # === Build Excel ===
    print("  Building Excel workbook...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_Client_Lifecycle_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as w:
        wb = w.book
        money = wb.add_format({"num_format": "#,##0.00"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})

        def _write_tab(df, name, col_widths=None, money_cols=None):
            if df.empty:
                return
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for i, col in enumerate(df.columns):
                ws.write(0, i, col, header_fmt)
            if col_widths:
                for i, width in enumerate(col_widths):
                    if money_cols and i in money_cols:
                        ws.set_column(i, i, width, money)
                    else:
                        ws.set_column(i, i, width)

        _write_tab(overview, "Client Overview",
                   [28, 14, 14, 14, 16, 18, 20, 16, 12, 14],
                   money_cols={5, 6, 9})

        _write_tab(top_ltv, "Top Clients LTV",
                   [28, 25, 16, 14, 14, 14, 14, 14, 16, 28, 14, 14],
                   money_cols={2, 10, 11})

        if not acq_pvt.empty:
            acq_pvt.to_excel(w, sheet_name="New Client Acquisition")
            ws = w.sheets["New Client Acquisition"]
            ws.set_row(0, None, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 15, 10)

        _write_tab(segments, "Activity Segments",
                   [28, 18, 14, 18, 12],
                   money_cols={3})

        _write_tab(frequency, "Visit Frequency",
                   [28, 14, 14, 16])

        _write_tab(big_spenders, "Predicted Big Spenders",
                   [28, 25, 18, 16, 14, 14, 16, 28, 10],
                   money_cols={3})

    print(f"  Saved: {filepath}")
    return str(filepath)
