"""
Instructor Performance Report.

Tabs:
1. Instructor Summary — visits, clients, revenue per instructor per studio
2. Instructor Trends — monthly visit counts per instructor (trailing 6 months)
3. Class Fill Rates — average attendance per class/instructor
4. No-Show & Cancel Rates — by instructor
5. Revenue per Visit — gross revenue attribution per completed visit
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def generate_instructor_report(conn, start_date: str = None, end_date: str = None,
                                output_dir: str = None) -> str:
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    # Default to prior month
    if start_date is None or end_date is None:
        today = datetime.now()
        first_of_month = today.replace(day=1)
        last_prior = first_of_month - timedelta(days=1)
        start_date = last_prior.replace(day=1).strftime("%Y-%m-%d")
        end_date = last_prior.strftime("%Y-%m-%d")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    print(f"Generating Instructor Performance Report: {start_date} to {end_date}")

    # === 1. Instructor Summary ===
    print("  Loading instructor summary...")
    summary = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(v.STUDIO_NAME) AS STUDIO,
            v.TRAINER_FULL_NAME AS INSTRUCTOR,
            COUNT(*) AS TOTAL_VISITS,
            SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END) AS COMPLETED,
            SUM(v.IS_CANCELLED) AS CANCELLED,
            SUM(v.IS_MISSED) AS NO_SHOWS,
            COUNT(DISTINCT v.CLIENT_ID) AS UNIQUE_CLIENTS,
            COUNT(DISTINCT v.CLASS_DATE) AS DAYS_WORKED,
            COUNT(DISTINCT v.CLASS_ID) AS UNIQUE_CLASSES,
            ROUND(SUM(v.GROSS_REVENUE_ATTRIBUTION_LOCAL), 2) AS GROSS_REVENUE,
            ROUND(SUM(v.NET_REVENUE_ATTRIBUTION_LOCAL), 2) AS NET_REVENUE,
            ROUND(
                SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
                         THEN v.GROSS_REVENUE_ATTRIBUTION_LOCAL ELSE 0 END)
                / NULLIF(SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END), 0),
            2) AS GROSS_REV_PER_COMPLETED_VISIT,
            ROUND(SUM(v.IS_CANCELLED + v.IS_MISSED) * 100.0 / NULLIF(COUNT(*), 0), 1) AS CANCEL_NOSHOW_RATE_PCT
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
        WHERE v.CLASS_DATE >= '{start_date}' AND v.CLASS_DATE <= '{end_date}'
          AND v.TRAINER_FULL_NAME IS NOT NULL
        GROUP BY 1, 2
        ORDER BY COMPLETED DESC
    """)

    # === 2. Monthly Trends (trailing 6 months, pivoted) ===
    print("  Loading instructor trends...")
    trends = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(v.STUDIO_NAME) AS STUDIO,
            v.TRAINER_FULL_NAME AS INSTRUCTOR,
            TO_VARCHAR(v.CLASS_DATE, 'YYYY-MM') AS MONTH,
            SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END) AS COMPLETED_VISITS,
            COUNT(DISTINCT v.CLIENT_ID) AS UNIQUE_CLIENTS,
            ROUND(SUM(v.GROSS_REVENUE_ATTRIBUTION_LOCAL), 2) AS GROSS_REVENUE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
        WHERE v.CLASS_DATE >= DATEADD(MONTH, -6, '{end_date}')
          AND v.CLASS_DATE <= '{end_date}'
          AND v.TRAINER_FULL_NAME IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """)

    # Pivot: visits by instructor/studio over months
    visits_pvt = pd.DataFrame()
    revenue_pvt = pd.DataFrame()
    if not trends.empty:
        trends["LABEL"] = trends["STUDIO"].str.replace("Mighty Pilates ", "") + " | " + trends["INSTRUCTOR"]
        visits_pvt = trends.pivot_table(
            index="LABEL", columns="MONTH", values="COMPLETED_VISITS",
            aggfunc="sum", fill_value=0
        ).sort_index()
        visits_pvt["TOTAL"] = visits_pvt.sum(axis=1)
        visits_pvt = visits_pvt.sort_values("TOTAL", ascending=False)

        revenue_pvt = trends.pivot_table(
            index="LABEL", columns="MONTH", values="GROSS_REVENUE",
            aggfunc="sum", fill_value=0
        ).sort_index()
        revenue_pvt["TOTAL"] = revenue_pvt.sum(axis=1)
        revenue_pvt = revenue_pvt.sort_values("TOTAL", ascending=False)

    # === 3. Class Fill Rates ===
    print("  Loading class fill rates...")
    fill_rates = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(v.STUDIO_NAME) AS STUDIO,
            v.TRAINER_FULL_NAME AS INSTRUCTOR,
            v.CLASS_NAME,
            COUNT(DISTINCT v.CLASS_INSTANCE_ID) AS CLASS_INSTANCES,
            SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END) AS COMPLETED_VISITS,
            ROUND(SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END)
                  * 1.0 / NULLIF(COUNT(DISTINCT v.CLASS_INSTANCE_ID), 0), 1) AS AVG_ATTENDANCE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
        WHERE v.CLASS_DATE >= '{start_date}' AND v.CLASS_DATE <= '{end_date}'
          AND v.TRAINER_FULL_NAME IS NOT NULL
          AND v.CLASS_INSTANCE_ID IS NOT NULL
        GROUP BY 1, 2, 3
        HAVING CLASS_INSTANCES >= 3
        ORDER BY AVG_ATTENDANCE DESC
    """)

    # === 4. No-Show & Cancel Detail by Instructor ===
    print("  Loading no-show/cancel rates...")
    noshow = execute_query_df(conn, f"""
        SELECT
            {CANON_STUDIO_SQL}(v.STUDIO_NAME) AS STUDIO,
            v.TRAINER_FULL_NAME AS INSTRUCTOR,
            COUNT(*) AS TOTAL_BOOKINGS,
            SUM(v.IS_CANCELLED) AS CANCELLATIONS,
            SUM(v.IS_MISSED) AS NO_SHOWS,
            SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0 THEN 1 ELSE 0 END) AS COMPLETED,
            ROUND(SUM(v.IS_CANCELLED) * 100.0 / NULLIF(COUNT(*), 0), 1) AS CANCEL_PCT,
            ROUND(SUM(v.IS_MISSED) * 100.0 / NULLIF(COUNT(*), 0), 1) AS NOSHOW_PCT,
            ROUND((SUM(v.IS_CANCELLED) + SUM(v.IS_MISSED)) * 100.0 / NULLIF(COUNT(*), 0), 1) AS COMBINED_PCT
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
        WHERE v.CLASS_DATE >= '{start_date}' AND v.CLASS_DATE <= '{end_date}'
          AND v.TRAINER_FULL_NAME IS NOT NULL
        GROUP BY 1, 2
        HAVING TOTAL_BOOKINGS >= 20
        ORDER BY COMBINED_PCT DESC
    """)

    # === Build Excel ===
    print("  Building Excel workbook...")
    period = start_dt.strftime("%b%Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_Instructor_Performance_{period}_{timestamp}.xlsx"
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

        _write_tab(summary, "Instructor Summary",
                   [28, 22, 12, 12, 10, 10, 14, 12, 14, 14, 14, 18, 16],
                   money_cols={9, 10, 11})

        if not visits_pvt.empty:
            visits_pvt.to_excel(w, sheet_name="Trends - Visits")
            ws = w.sheets["Trends - Visits"]
            ws.set_row(0, None, header_fmt)
            ws.set_column(0, 0, 35)
            ws.set_column(1, 10, 12)

        if not revenue_pvt.empty:
            revenue_pvt.to_excel(w, sheet_name="Trends - Revenue")
            ws = w.sheets["Trends - Revenue"]
            ws.set_row(0, None, header_fmt)
            ws.set_column(0, 0, 35)
            ws.set_column(1, 10, 14, money)

        _write_tab(fill_rates, "Class Fill Rates",
                   [28, 22, 30, 14, 16, 14])

        _write_tab(noshow, "No-Show & Cancel Rates",
                   [28, 22, 14, 14, 10, 12, 10, 10, 12])

    print(f"  Saved: {filepath}")
    return str(filepath)
