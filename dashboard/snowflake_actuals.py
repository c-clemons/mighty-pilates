"""
Snowflake data access for pulling real-time actuals.
Imports from pipeline/connection.py without modifying it.
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.constants import month_key, ACTIVE_STUDIOS

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def pull_monthly_revenue_by_studio(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Pull monthly revenue by studio from the rev rec model.
    Returns DataFrame: index=studio_name, columns=month_keys, values=net earned revenue.
    """
    from pipeline.connection import get_connection, execute_query_df

    conn = get_connection()
    df = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(EVENT_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
            ROUND(SUM(GROSS_EARNED_REVENUE), 2) AS EARNED_REVENUE,
            ROUND(SUM(GROSS_BREAKAGE_REVENUE), 2) AS BREAKAGE,
            ROUND(SUM(GROSS_RETAIL_SALES), 2) AS RETAIL,
            ROUND(SUM(TOTAL_DISCOUNTS), 2) AS DISCOUNTS,
            COUNT(*) AS TRANSACTIONS
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE EVENT_DATE >= '{start_date}' AND EVENT_DATE <= '{end_date}'
        GROUP BY MONTH_YM, STUDIO
        ORDER BY MONTH_YM, STUDIO
    """)
    conn.close()
    return df


def pull_classpass_revenue(start_date: str, end_date: str) -> pd.DataFrame:
    """Pull ClassPass revenue by studio and month."""
    from pipeline.connection import get_connection, execute_query_df

    conn = get_connection()
    df = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(r.START_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(s.STUDIO_NAME) AS STUDIO,
            ROUND(SUM(r.RATE_USD), 2) AS CLASSPASS_REVENUE,
            COUNT(*) AS RESERVATIONS
        FROM PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS r
        LEFT JOIN (
            SELECT STUDIO_ID::VARCHAR AS STUDIO_ID, MAX(STUDIO_NAME) AS STUDIO_NAME
            FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS
            WHERE STUDIO_ID IS NOT NULL AND STUDIO_NAME IS NOT NULL
            GROUP BY STUDIO_ID::VARCHAR
        ) s ON s.STUDIO_ID = r.STUDIO_ID::VARCHAR
        WHERE r.START_DATE >= '{start_date}' AND r.START_DATE <= '{end_date}'
          AND r.IS_PAID_RESERVATION = TRUE
          AND r.RATE_USD IS NOT NULL AND r.RATE_USD != 0
        GROUP BY MONTH_YM, STUDIO
        ORDER BY MONTH_YM, STUDIO
    """)
    conn.close()
    return df


def pull_mindbody_net_sales(start_date: str, end_date: str) -> pd.DataFrame:
    """Pull MinBody net sales (cash register) by studio and month."""
    from pipeline.connection import get_connection, execute_query_df

    conn = get_connection()
    df = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO,
            ROUND(SUM(m.NET_PAYMENTAMT_LOCAL), 2) AS NET_SALES,
            COUNT(*) AS TRANSACTIONS
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.SALES_ONLY_FLAG = 'TRUE'
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          AND m.NET_PAYMENTAMT_LOCAL != 0
        GROUP BY MONTH_YM, STUDIO
        ORDER BY MONTH_YM, STUDIO
    """)
    conn.close()
    return df


def pull_refunds(start_date: str, end_date: str) -> pd.DataFrame:
    """Pull refund totals by studio and month."""
    from pipeline.connection import get_connection, execute_query_df

    conn = get_connection()
    df = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO,
            ROUND(-1 * SUM(ABS(m.GROSS_UNIT_PRICE * m.QUANTITY)), 2) AS REFUNDS,
            COUNT(*) AS REFUND_COUNT
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.IS_RETURN = 1
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          AND ABS(m.GROSS_UNIT_PRICE * m.QUANTITY) != 0
        GROUP BY MONTH_YM, STUDIO
        ORDER BY MONTH_YM, STUDIO
    """)
    conn.close()
    return df


def pull_current_month_summary() -> dict:
    """
    Pull current-month-to-date revenue summary.
    Returns dict with revenue by studio and totals.
    """
    today = datetime.now()
    start = f"{today.year}-{today.month:02d}-01"
    end = today.strftime("%Y-%m-%d")
    current_mk = month_key(today.year, today.month)

    rev = pull_monthly_revenue_by_studio(start, end)
    cp = pull_classpass_revenue(start, end)

    summary = {
        "month": current_mk,
        "as_of": end,
        "days_elapsed": today.day,
        "days_in_month": (today.replace(month=today.month % 12 + 1, day=1) if today.month < 12
                          else today.replace(year=today.year + 1, month=1, day=1)).day,
        "studios": {},
        "total_earned": 0,
        "total_classpass": 0,
    }

    # Aggregate rev rec by studio
    if not rev.empty:
        for _, row in rev.iterrows():
            studio = row["STUDIO"]
            earned = float(row.get("EARNED_REVENUE", 0))
            breakage = float(row.get("BREAKAGE", 0))
            retail = float(row.get("RETAIL", 0))
            summary["studios"][studio] = {
                "earned": earned, "breakage": breakage, "retail": retail,
            }
            summary["total_earned"] += earned + breakage + retail

    # Add ClassPass
    if not cp.empty:
        for _, row in cp.iterrows():
            studio = row["STUDIO"]
            cp_rev = float(row.get("CLASSPASS_REVENUE", 0))
            if studio in summary["studios"]:
                summary["studios"][studio]["classpass"] = cp_rev
            else:
                summary["studios"][studio] = {"classpass": cp_rev}
            summary["total_classpass"] += cp_rev

    return summary
