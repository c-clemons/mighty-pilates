"""
Deep Dive Analytics Reports for Mighty Pilates.

Generates Excel workbook with multiple analysis tabs:
1. Package Breakage Detail — which packages broke, when purchased, revenue category
2. Breakage Duration — average time from purchase to breakage by category/studio
3. Top Clients by Earned Revenue — per studio
4. Top Clients by Breakage Revenue — per studio
5. Package Utilization — usage rates by product/studio
6. Monthly Trends — month-over-month earned revenue, breakage, utilization
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def generate_deep_dive(conn, start_date: str, end_date: str, output_dir: str = None) -> str:
    """
    Generate deep dive Excel workbook.

    Args:
        conn: Snowflake connection
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        output_dir: Where to save

    Returns:
        Path to generated file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    print(f"Generating Deep Dive: {start_date} to {end_date}")

    # === 1. Package Breakage Detail ===
    print("  Loading breakage detail...")
    breakage_detail = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
            bp.PRODUCT_DESCRIPTION,
            bp.REVENUE_CATEGORY,
            bp.SALE_DATE AS PURCHASE_DATE,
            pe.EXPIRATION_DATE,
            DATEDIFF(DAY, bp.SALE_DATE, pe.EXPIRATION_DATE) AS DAYS_TO_BREAKAGE,
            bp.PO_CAPACITY_COUNT AS TOTAL_SESSIONS,
            COALESCE(ut.SESSIONS_USED_COUNT, 0) AS SESSIONS_USED,
            bp.PO_CAPACITY_COUNT - COALESCE(ut.SESSIONS_USED_COUNT, 0) AS SESSIONS_UNUSED,
            CASE WHEN bp.PO_CAPACITY_COUNT > 0
                 THEN ROUND(COALESCE(ut.SESSIONS_USED_COUNT, 0) * 100.0 / bp.PO_CAPACITY_COUNT, 1)
                 ELSE 0 END AS UTILIZATION_PCT,
            bp.UNIT_PRICE AS GROSS_PACKAGE_PRICE,
            bp.DEFERRED_REVENUE AS NET_PACKAGE_PRICE,
            COALESCE(ut.TOTAL_GROSS_USED, 0) AS GROSS_EARNED,
            GREATEST(bp.UNIT_PRICE - COALESCE(ut.TOTAL_GROSS_USED, 0), 0) AS GROSS_BREAKAGE,
            GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0), 0) AS NET_BREAKAGE,
            pe.IS_IMPUTED AS EXPIRATION_IS_IMPUTED
        FROM PRICING_PER_VISIT_UNIQ bp
        JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
        LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
        JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
            ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
        WHERE bp.ITEM_TYPE = 'Pricing Option'
          AND rct.RECOGNITION_TYPE = 'visits-based'
          AND COALESCE(bp.IS_DEPOSIT, 0) = 0
          AND bp.PACKAGE_TYPE != 'Unlimited'
          AND pe.EXPIRATION_DATE >= '{start_date}' AND pe.EXPIRATION_DATE <= '{end_date}'
          AND (bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0)) > 0
        ORDER BY NET_BREAKAGE DESC
    """)
    print(f"    Breakage packages: {len(breakage_detail)}")

    # === 2. Breakage Duration Summary ===
    print("  Computing breakage duration stats...")
    breakage_duration = execute_query_df(conn, f"""
        WITH breakage_data AS (
            SELECT
                {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
                bp.REVENUE_CATEGORY,
                bp.SALE_DATE,
                pe.EXPIRATION_DATE,
                DATEDIFF(DAY, bp.SALE_DATE, pe.EXPIRATION_DATE) AS DAYS_TO_BREAKAGE,
                GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0), 0) AS NET_BREAKAGE
            FROM PRICING_PER_VISIT_UNIQ bp
            JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
            LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
            JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
                ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
            WHERE bp.ITEM_TYPE = 'Pricing Option'
              AND rct.RECOGNITION_TYPE = 'visits-based'
              AND COALESCE(bp.IS_DEPOSIT, 0) = 0
              AND bp.PACKAGE_TYPE != 'Unlimited'
              AND pe.EXPIRATION_DATE >= '{start_date}' AND pe.EXPIRATION_DATE <= '{end_date}'
              AND (bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0)) > 0
        )
        SELECT
            STUDIO,
            REVENUE_CATEGORY,
            COUNT(*) AS BREAKAGE_EVENTS,
            ROUND(SUM(NET_BREAKAGE), 2) AS TOTAL_NET_BREAKAGE,
            ROUND(AVG(NET_BREAKAGE), 2) AS AVG_NET_BREAKAGE,
            ROUND(AVG(DAYS_TO_BREAKAGE), 0) AS AVG_DAYS_TO_BREAKAGE,
            ROUND(MEDIAN(DAYS_TO_BREAKAGE), 0) AS MEDIAN_DAYS_TO_BREAKAGE,
            MIN(DAYS_TO_BREAKAGE) AS MIN_DAYS,
            MAX(DAYS_TO_BREAKAGE) AS MAX_DAYS
        FROM breakage_data
        GROUP BY STUDIO, REVENUE_CATEGORY
        ORDER BY TOTAL_NET_BREAKAGE DESC
    """)

    # === 3. Top Clients by Earned Revenue (per studio) ===
    print("  Loading top clients by earned revenue...")
    top_earned = execute_query_df(conn, f"""
        WITH client_earned AS (
            SELECT
                {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
                bp.GLOBAL_CLIENT_KEY,
                cx.FIRST_NAME,
                cx.LAST_NAME,
                SUM(COALESCE(ut.TOTAL_GROSS_USED, 0)) AS GROSS_EARNED_REVENUE,
                SUM(COALESCE(ut.TOTAL_NET_USED, 0)) AS NET_EARNED_REVENUE,
                SUM(COALESCE(ut.SESSIONS_USED_COUNT, 0)) AS TOTAL_SESSIONS,
                COUNT(DISTINCT bp.PACKAGE_ID) AS PACKAGES_PURCHASED
            FROM PRICING_PER_VISIT_UNIQ bp
            LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
            LEFT JOIN (
                SELECT cx2.GLOBAL_CLIENT_KEY,
                       MAX(v.FIRST_NAME) AS FIRST_NAME,
                       MAX(v.LAST_NAME) AS LAST_NAME
                FROM CLIENT_XWALK cx2
                JOIN PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
                  ON v.STUDIO_ID = cx2.STUDIO_ID AND v.CLIENT_ID = cx2.CLIENT_ID
                WHERE v.FIRST_NAME IS NOT NULL AND v.LAST_NAME IS NOT NULL
                GROUP BY cx2.GLOBAL_CLIENT_KEY
            ) cx ON cx.GLOBAL_CLIENT_KEY = bp.GLOBAL_CLIENT_KEY
            WHERE bp.ITEM_TYPE = 'Pricing Option'
              AND COALESCE(bp.IS_DEPOSIT, 0) = 0
              AND bp.SALE_DATE >= '{start_date}' AND bp.SALE_DATE <= '{end_date}'
            GROUP BY 1, 2, 3, 4
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY STUDIO ORDER BY GROSS_EARNED_REVENUE DESC) AS RANK
            FROM client_earned
            WHERE GROSS_EARNED_REVENUE > 0
        )
        SELECT STUDIO, RANK,
               COALESCE(FIRST_NAME, '') || ' ' || COALESCE(LAST_NAME, '') AS CLIENT_NAME,
               GROSS_EARNED_REVENUE, NET_EARNED_REVENUE,
               TOTAL_SESSIONS, PACKAGES_PURCHASED
        FROM ranked
        WHERE RANK <= 25
        ORDER BY STUDIO, RANK
    """)

    # === 4. Top Clients by Breakage (per studio) ===
    print("  Loading top clients by breakage...")
    top_breakage = execute_query_df(conn, f"""
        WITH client_breakage AS (
            SELECT
                {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
                bp.GLOBAL_CLIENT_KEY,
                cx.FIRST_NAME,
                cx.LAST_NAME,
                SUM(GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0), 0)) AS NET_BREAKAGE,
                SUM(GREATEST(bp.UNIT_PRICE - COALESCE(ut.TOTAL_GROSS_USED, 0), 0)) AS GROSS_BREAKAGE,
                COUNT(DISTINCT bp.PACKAGE_ID) AS PACKAGES_WITH_BREAKAGE,
                SUM(bp.PO_CAPACITY_COUNT) AS TOTAL_SESSIONS_PURCHASED,
                SUM(COALESCE(ut.SESSIONS_USED_COUNT, 0)) AS SESSIONS_USED
            FROM PRICING_PER_VISIT_UNIQ bp
            JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
            LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
            JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
                ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
            LEFT JOIN (
                SELECT cx2.GLOBAL_CLIENT_KEY,
                       MAX(v.FIRST_NAME) AS FIRST_NAME,
                       MAX(v.LAST_NAME) AS LAST_NAME
                FROM CLIENT_XWALK cx2
                JOIN PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
                  ON v.STUDIO_ID = cx2.STUDIO_ID AND v.CLIENT_ID = cx2.CLIENT_ID
                WHERE v.FIRST_NAME IS NOT NULL AND v.LAST_NAME IS NOT NULL
                GROUP BY cx2.GLOBAL_CLIENT_KEY
            ) cx ON cx.GLOBAL_CLIENT_KEY = bp.GLOBAL_CLIENT_KEY
            WHERE bp.ITEM_TYPE = 'Pricing Option'
              AND rct.RECOGNITION_TYPE = 'visits-based'
              AND COALESCE(bp.IS_DEPOSIT, 0) = 0
              AND bp.PACKAGE_TYPE != 'Unlimited'
              AND pe.EXPIRATION_DATE >= '{start_date}' AND pe.EXPIRATION_DATE <= '{end_date}'
              AND (bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0)) > 0
            GROUP BY 1, 2, 3, 4
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY STUDIO ORDER BY NET_BREAKAGE DESC) AS RANK
            FROM client_breakage
            WHERE NET_BREAKAGE > 0
        )
        SELECT STUDIO, RANK,
               COALESCE(FIRST_NAME, '') || ' ' || COALESCE(LAST_NAME, '') AS CLIENT_NAME,
               GROSS_BREAKAGE, NET_BREAKAGE,
               PACKAGES_WITH_BREAKAGE,
               TOTAL_SESSIONS_PURCHASED, SESSIONS_USED,
               CASE WHEN TOTAL_SESSIONS_PURCHASED > 0
                    THEN ROUND(SESSIONS_USED * 100.0 / TOTAL_SESSIONS_PURCHASED, 1)
                    ELSE 0 END AS UTILIZATION_PCT
        FROM ranked
        WHERE RANK <= 25
        ORDER BY STUDIO, RANK
    """)

    # === 5. Package Utilization ===
    print("  Loading package utilization...")
    utilization = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
            bp.REVENUE_CATEGORY,
            bp.PRODUCT_DESCRIPTION,
            COUNT(DISTINCT bp.PACKAGE_ID) AS PACKAGES,
            SUM(bp.PO_CAPACITY_COUNT) AS TOTAL_CAPACITY,
            SUM(COALESCE(ut.SESSIONS_USED_COUNT, 0)) AS TOTAL_USED,
            SUM(bp.PO_CAPACITY_COUNT) - SUM(COALESCE(ut.SESSIONS_USED_COUNT, 0)) AS TOTAL_UNUSED,
            CASE WHEN SUM(bp.PO_CAPACITY_COUNT) > 0
                 THEN ROUND(SUM(COALESCE(ut.SESSIONS_USED_COUNT, 0)) * 100.0 / SUM(bp.PO_CAPACITY_COUNT), 1)
                 ELSE 0 END AS UTILIZATION_PCT,
            ROUND(SUM(bp.DEFERRED_REVENUE), 2) AS TOTAL_NET_REVENUE,
            ROUND(SUM(COALESCE(ut.TOTAL_NET_USED, 0)), 2) AS TOTAL_NET_EARNED,
            ROUND(SUM(GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED, 0), 0)), 2) AS TOTAL_NET_BREAKAGE
        FROM PRICING_PER_VISIT_UNIQ bp
        JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
        LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
        JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
            ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
        WHERE bp.ITEM_TYPE = 'Pricing Option'
          AND rct.RECOGNITION_TYPE = 'visits-based'
          AND COALESCE(bp.IS_DEPOSIT, 0) = 0
          AND bp.PACKAGE_TYPE != 'Unlimited'
          AND bp.PO_CAPACITY_COUNT > 0
          AND pe.EXPIRATION_DATE >= '{start_date}' AND pe.EXPIRATION_DATE <= '{end_date}'
        GROUP BY 1, 2, 3
        ORDER BY TOTAL_NET_REVENUE DESC
    """)

    # === 6. Monthly Trends (trailing 12 months) ===
    print("  Loading monthly trends...")
    trends = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(EVENT_DATE, 'YYYY-MM') AS MONTH,
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
            SUM(CASE WHEN EVENT_TYPE IN ('Usage', 'Livestream Daily', 'Unlimited Daily')
                     THEN GROSS_EARNED_REVENUE ELSE 0 END) AS GROSS_EARNED_REVENUE,
            SUM(CASE WHEN EVENT_TYPE IN ('Usage', 'Livestream Daily', 'Unlimited Daily')
                     THEN NET_EARNED_REVENUE ELSE 0 END) AS NET_EARNED_REVENUE,
            SUM(GROSS_BREAKAGE_REVENUE) AS GROSS_BREAKAGE,
            SUM(NET_BREAKAGE_REVENUE) AS NET_BREAKAGE,
            SUM(CASE WHEN EVENT_TYPE = 'Purchase' AND ITEM_TYPE = 'Pricing Option'
                     THEN GROSS_TOTAL_SALES ELSE 0 END) AS GROSS_SESSION_SALES,
            SUM(SESSIONS_USED) AS SESSIONS_USED,
            SUM(SESSIONS_SOLD) AS SESSIONS_SOLD
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE EVENT_DATE >= DATEADD(MONTH, -12, '{end_date}')
          AND EVENT_DATE <= '{end_date}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)

    # Also get all-studios totals
    trends_total = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(EVENT_DATE, 'YYYY-MM') AS MONTH,
            'All Studios' AS STUDIO,
            SUM(CASE WHEN EVENT_TYPE IN ('Usage', 'Livestream Daily', 'Unlimited Daily')
                     THEN GROSS_EARNED_REVENUE ELSE 0 END) AS GROSS_EARNED_REVENUE,
            SUM(CASE WHEN EVENT_TYPE IN ('Usage', 'Livestream Daily', 'Unlimited Daily')
                     THEN NET_EARNED_REVENUE ELSE 0 END) AS NET_EARNED_REVENUE,
            SUM(GROSS_BREAKAGE_REVENUE) AS GROSS_BREAKAGE,
            SUM(NET_BREAKAGE_REVENUE) AS NET_BREAKAGE,
            SUM(CASE WHEN EVENT_TYPE = 'Purchase' AND ITEM_TYPE = 'Pricing Option'
                     THEN GROSS_TOTAL_SALES ELSE 0 END) AS GROSS_SESSION_SALES,
            SUM(SESSIONS_USED) AS SESSIONS_USED,
            SUM(SESSIONS_SOLD) AS SESSIONS_SOLD
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE EVENT_DATE >= DATEADD(MONTH, -12, '{end_date}')
          AND EVENT_DATE <= '{end_date}'
        GROUP BY 1
        ORDER BY 1
    """)
    trends_all = pd.concat([trends_total, trends], ignore_index=True)

    # === Build Excel ===
    print("  Building Excel workbook...")
    start_label = start_dt.strftime("%b%Y")
    end_label = end_dt.strftime("%b%Y")
    if start_label == end_label:
        period_label = start_label
    else:
        period_label = f"{start_label}-{end_label}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_DeepDive_{period_label}_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as w:
        wb = w.book
        money = wb.add_format({"num_format": "#,##0.00"})
        pct_fmt = wb.add_format({"num_format": "0.0%"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        title_fmt = wb.add_format({"bold": True, "font_size": 14})

        # Cover
        cover = [
            [f"MIGHTY PILATES — DEEP DIVE ANALYTICS"],
            [""],
            ["Report Period", f"{start_date} through {end_date}"],
            ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
            [""],
            ["Tab", "Description"],
            ["Breakage Detail", "Every package that broke in the period — product, purchase date, sessions, revenue"],
            ["Breakage Duration", "Average days from purchase to breakage by studio and category"],
            ["Top Clients Earned", "Top 25 clients by earned revenue per studio"],
            ["Top Clients Breakage", "Top 25 clients by breakage revenue per studio"],
            ["Package Utilization", "Session usage rates by product and studio"],
            ["Monthly Trends", "Trailing 12-month earned revenue, breakage, session counts"],
        ]
        pd.DataFrame(cover).to_excel(w, sheet_name="Cover", index=False, header=False)

        # Tab 1: Breakage Detail
        if not breakage_detail.empty:
            breakage_detail.to_excel(w, sheet_name="Breakage Detail", index=False)
            ws = w.sheets["Breakage Detail"]
            for i, col in enumerate(breakage_detail.columns):
                ws.write(0, i, col, header_fmt)
            ws.set_column(0, 0, 28)  # Studio
            ws.set_column(1, 1, 40)  # Product
            ws.set_column(2, 2, 20)  # Category
            ws.set_column(3, 4, 14)  # Dates
            ws.set_column(5, 5, 16)  # Days
            ws.set_column(6, 8, 14)  # Sessions
            ws.set_column(9, 9, 12)  # Util%
            ws.set_column(10, 15, 16, money)

        # Tab 2: Breakage Duration
        if not breakage_duration.empty:
            breakage_duration.to_excel(w, sheet_name="Breakage Duration", index=False)
            ws = w.sheets["Breakage Duration"]
            for i, col in enumerate(breakage_duration.columns):
                ws.write(0, i, col, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 1, 20)
            ws.set_column(2, 2, 14)
            ws.set_column(3, 4, 18, money)
            ws.set_column(5, 8, 14)

        # Tab 3: Top Clients Earned
        if not top_earned.empty:
            top_earned.to_excel(w, sheet_name="Top Clients Earned", index=False)
            ws = w.sheets["Top Clients Earned"]
            for i, col in enumerate(top_earned.columns):
                ws.write(0, i, col, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 1, 6)
            ws.set_column(2, 2, 25)
            ws.set_column(3, 4, 18, money)
            ws.set_column(5, 6, 14)

        # Tab 4: Top Clients Breakage
        if not top_breakage.empty:
            top_breakage.to_excel(w, sheet_name="Top Clients Breakage", index=False)
            ws = w.sheets["Top Clients Breakage"]
            for i, col in enumerate(top_breakage.columns):
                ws.write(0, i, col, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 1, 6)
            ws.set_column(2, 2, 25)
            ws.set_column(3, 4, 18, money)
            ws.set_column(5, 8, 14)

        # Tab 5: Package Utilization
        if not utilization.empty:
            utilization.to_excel(w, sheet_name="Package Utilization", index=False)
            ws = w.sheets["Package Utilization"]
            for i, col in enumerate(utilization.columns):
                ws.write(0, i, col, header_fmt)
            ws.set_column(0, 0, 28)
            ws.set_column(1, 1, 20)
            ws.set_column(2, 2, 40)
            ws.set_column(3, 7, 14)
            ws.set_column(8, 10, 18, money)

        # Tab 6: Monthly Trends (pivoted — one row per studio, columns per month)
        if not trends_all.empty:
            # Pivot for earned revenue
            earned_pvt = trends_all.pivot_table(
                index="STUDIO", columns="MONTH", values="GROSS_EARNED_REVENUE",
                aggfunc="sum", fill_value=0
            ).sort_index()
            earned_pvt["TOTAL"] = earned_pvt.sum(axis=1)
            earned_pvt.to_excel(w, sheet_name="Trends - Earned Rev")

            # Pivot for breakage
            brk_pvt = trends_all.pivot_table(
                index="STUDIO", columns="MONTH", values="GROSS_BREAKAGE",
                aggfunc="sum", fill_value=0
            ).sort_index()
            brk_pvt["TOTAL"] = brk_pvt.sum(axis=1)
            brk_pvt.to_excel(w, sheet_name="Trends - Breakage")

            # Pivot for sessions used
            sess_pvt = trends_all.pivot_table(
                index="STUDIO", columns="MONTH", values="SESSIONS_USED",
                aggfunc="sum", fill_value=0
            ).sort_index()
            sess_pvt["TOTAL"] = sess_pvt.sum(axis=1)
            sess_pvt.to_excel(w, sheet_name="Trends - Sessions")

            # Format trend tabs
            for tab_name in ["Trends - Earned Rev", "Trends - Breakage", "Trends - Sessions"]:
                ws = w.sheets[tab_name]
                ws.set_row(0, None, header_fmt)
                ws.set_column(0, 0, 28)
                ws.set_column(1, 20, 14, money)

        # Format cover
        ws_cover = w.sheets["Cover"]
        ws_cover.set_column(0, 0, 25)
        ws_cover.set_column(1, 1, 80)

    print(f"  Saved: {filepath}")
    return str(filepath)


def generate_prior_month_deep_dive(conn, output_dir: str = None) -> str:
    """Generate deep dive for the prior month."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_prior = first_of_month - timedelta(days=1)
    start = last_prior.replace(day=1)
    return generate_deep_dive(
        conn, start.strftime("%Y-%m-%d"), last_prior.strftime("%Y-%m-%d"), output_dir
    )
