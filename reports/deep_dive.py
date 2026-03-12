"""
Usage & Breakage Analytics Report for Mighty Pilates.

Generates both Excel workbook and formatted PDF management report.

Tabs/Sections:
1. Breakage Detail — packages that expired with unused sessions, purchase date, revenue
2. Breakage Duration — average time from purchase to breakage by studio/category
3. Top Clients by Earned Revenue — per studio (top 25)
4. Top Clients by Breakage Revenue — per studio (top 25)
5. Package Utilization — session usage rates by product/studio
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def _query_deep_dive_data(conn, start_date: str, end_date: str) -> dict:
    """Run all deep dive queries and return dict of DataFrames."""

    print(f"Generating Deep Dive: {start_date} to {end_date}")

    # === 0. Studio Summary — sessions sold, earned, broken ===
    print("  Loading studio summary...")
    studio_summary = execute_query_df(conn, f"""
        WITH studio_activity AS (
            SELECT
                {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO,
                SUM(SESSIONS_SOLD) AS SESSIONS_SOLD,
                SUM(SESSIONS_USED) AS SESSIONS_EARNED,
                ROUND(SUM(GROSS_EARNED_REVENUE), 2) AS GROSS_EARNED_REV,
                ROUND(SUM(NET_EARNED_REVENUE), 2) AS NET_EARNED_REV,
                ROUND(SUM(GROSS_BREAKAGE_REVENUE), 2) AS GROSS_BREAKAGE_REV,
                ROUND(SUM(NET_BREAKAGE_REVENUE), 2) AS NET_BREAKAGE_REV
            FROM DAILY_REVENUE_AND_SALES_DETAIL
            WHERE EVENT_DATE >= '{start_date}' AND EVENT_DATE <= '{end_date}'
            GROUP BY 1
        ),
        breakage_sessions AS (
            SELECT
                {CANON_STUDIO_SQL}(bp.STUDIO_NAME) AS STUDIO,
                SUM(bp.PO_CAPACITY_COUNT - COALESCE(ut.SESSIONS_USED_COUNT, 0)) AS SESSIONS_BROKEN
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
            GROUP BY 1
        )
        SELECT
            s.STUDIO,
            s.SESSIONS_SOLD,
            s.SESSIONS_EARNED,
            COALESCE(b.SESSIONS_BROKEN, 0) AS SESSIONS_BROKEN,
            s.GROSS_EARNED_REV,
            s.NET_EARNED_REV,
            s.GROSS_BREAKAGE_REV,
            s.NET_BREAKAGE_REV
        FROM studio_activity s
        LEFT JOIN breakage_sessions b ON b.STUDIO = s.STUDIO
        ORDER BY s.NET_EARNED_REV DESC
    """)

    # Add totals row
    if not studio_summary.empty:
        for col in studio_summary.columns:
            if col != "STUDIO":
                studio_summary[col] = pd.to_numeric(studio_summary[col], errors="coerce")
        totals = studio_summary.select_dtypes(include="number").sum()
        totals_row = pd.DataFrame([["ALL STUDIOS"] + totals.tolist()], columns=studio_summary.columns)
        studio_summary = pd.concat([totals_row, studio_summary], ignore_index=True)

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

    return {
        "studio_summary": studio_summary,
        "breakage_detail": breakage_detail,
        "breakage_duration": breakage_duration,
        "top_earned": top_earned,
        "top_breakage": top_breakage,
        "utilization": utilization,
    }


def _build_excel(data: dict, start_date: str, end_date: str, output_dir: Path) -> str:
    """Build the Excel workbook."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    period_label = start_dt.strftime("%b%Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_UsageBreakage_{period_label}_{timestamp}.xlsx"
    filepath = output_dir / filename

    studio_summary = data["studio_summary"]
    breakage_detail = data["breakage_detail"]
    breakage_duration = data["breakage_duration"]
    top_earned = data["top_earned"]
    top_breakage = data["top_breakage"]
    utilization = data["utilization"]

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as w:
        wb = w.book
        money = wb.add_format({"num_format": "#,##0.00"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})

        # Cover
        cover = [
            [f"MIGHTY PILATES — USAGE & BREAKAGE ANALYTICS"],
            [""],
            ["Report Period", f"{start_date} through {end_date}"],
            ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
            [""],
            ["Tab", "Description"],
            ["Studio Summary", "Sessions sold, earned, and broken by studio for the period"],
            ["Breakage Detail", "Packages that expired with unused sessions — product, purchase date, revenue"],
            ["Breakage Duration", "Average days from purchase to breakage by studio and category"],
            ["Top Clients Earned", "Top 25 clients by earned revenue per studio"],
            ["Top Clients Breakage", "Top 25 clients by breakage revenue per studio"],
            ["Package Utilization", "Session usage rates by product and studio"],
        ]
        pd.DataFrame(cover).to_excel(w, sheet_name="Cover", index=False, header=False)

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

        _write_tab(studio_summary, "Studio Summary",
                   [28, 14, 14, 14, 18, 18, 18, 18],
                   money_cols={4, 5, 6, 7})

        _write_tab(breakage_detail, "Breakage Detail",
                   [28, 40, 20, 14, 14, 16, 14, 14, 14, 12, 16, 16, 16, 16, 16, 14],
                   money_cols={10, 11, 12, 13, 14})

        _write_tab(breakage_duration, "Breakage Duration",
                   [28, 20, 14, 18, 18, 14, 14, 10, 10],
                   money_cols={3, 4})

        _write_tab(top_earned, "Top Clients Earned",
                   [28, 6, 25, 18, 18, 14, 14],
                   money_cols={3, 4})

        _write_tab(top_breakage, "Top Clients Breakage",
                   [28, 6, 25, 18, 18, 14, 14, 14, 12],
                   money_cols={3, 4})

        _write_tab(utilization, "Package Utilization",
                   [28, 20, 40, 14, 14, 14, 14, 12, 18, 18, 18],
                   money_cols={8, 9, 10})

        # Format cover
        ws_cover = w.sheets["Cover"]
        ws_cover.set_column(0, 0, 25)
        ws_cover.set_column(1, 1, 80)

    print(f"  Excel saved: {filepath}")
    return str(filepath)


def _build_pdf(data: dict, start_date: str, end_date: str, output_dir: Path) -> str:
    """Build a formatted PDF management report."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        PageBreak, HRFlowable
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    period_label = start_dt.strftime("%B %Y")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_UsageBreakage_{start_dt.strftime('%b%Y')}_{timestamp}.pdf"
    filepath = output_dir / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        fontSize=22, spaceAfter=4, textColor=colors.HexColor("#1B2A4A"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"],
        fontSize=12, spaceAfter=20, textColor=colors.HexColor("#5A6B8A"),
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"],
        fontSize=14, spaceBefore=16, spaceAfter=8,
        textColor=colors.HexColor("#1B2A4A"),
        borderPadding=(0, 0, 4, 0),
    )
    body_style = ParagraphStyle(
        "BodyText", parent=styles["Normal"],
        fontSize=9, leading=12,
    )

    # Color palette
    HEADER_BG = colors.HexColor("#1B2A4A")
    HEADER_FG = colors.white
    ALT_ROW = colors.HexColor("#F4F6FA")
    ACCENT = colors.HexColor("#2E7D32")
    BORDER = colors.HexColor("#D0D5DD")

    elements = []

    def _fmt_money(val):
        try:
            v = float(val)
            return f"${v:,.2f}"
        except (ValueError, TypeError):
            return str(val)

    def _fmt_num(val):
        try:
            v = float(val)
            if v == int(v):
                return f"{int(v):,}"
            return f"{v:,.1f}"
        except (ValueError, TypeError):
            return str(val)

    def _fmt_pct(val):
        try:
            return f"{float(val):.1f}%"
        except (ValueError, TypeError):
            return str(val)

    def _make_table(df, col_labels, col_widths, formatters=None, max_rows=None):
        """Build a styled reportlab Table from a DataFrame."""
        if df.empty:
            return Paragraph("<i>No data available</i>", body_style)

        display_df = df.head(max_rows) if max_rows else df

        # Header row
        header = [Paragraph(f"<b>{c}</b>", ParagraphStyle(
            "TH", parent=body_style, fontSize=8, textColor=HEADER_FG, alignment=TA_CENTER
        )) for c in col_labels]

        rows = [header]
        for _, row in display_df.iterrows():
            cells = []
            for j, col in enumerate(df.columns[:len(col_labels)]):
                val = row[col]
                fmt = formatters.get(j, str) if formatters else str
                cell_text = fmt(val)
                align = TA_RIGHT if fmt in (_fmt_money, _fmt_num, _fmt_pct) else TA_LEFT
                cells.append(Paragraph(cell_text, ParagraphStyle(
                    "TD", parent=body_style, fontSize=8, alignment=align
                )))
            rows.append(cells)

        t = Table(rows, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        # Alternating row colors
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), ALT_ROW))
        t.setStyle(TableStyle(style_cmds))
        return t

    # ============================
    # PAGE 1: Title + Studio Summary + Breakage Duration
    # ============================
    elements.append(Paragraph("MIGHTY PILATES", title_style))
    elements.append(Paragraph(f"Usage & Breakage Analytics  |  {period_label}", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=2, color=HEADER_BG, spaceAfter=16))

    # Studio Summary table
    elements.append(Paragraph("Studio Summary", section_style))
    ss = data["studio_summary"]
    if not ss.empty:
        for col in ss.columns:
            if col != "STUDIO":
                ss[col] = pd.to_numeric(ss[col], errors="coerce")
    elements.append(_make_table(
        ss,
        col_labels=["Studio", "Sessions Sold", "Sessions Earned",
                     "Sessions Broken", "Gross Earned Rev", "Net Earned Rev",
                     "Gross Breakage Rev", "Net Breakage Rev"],
        col_widths=[2.0*inch, 1.0*inch, 1.0*inch, 1.0*inch,
                    1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch],
        formatters={1: _fmt_num, 2: _fmt_num, 3: _fmt_num,
                    4: _fmt_money, 5: _fmt_money, 6: _fmt_money, 7: _fmt_money},
    ))
    elements.append(Spacer(1, 16))

    # Breakage Duration summary
    elements.append(Paragraph("Breakage Duration by Studio & Category", section_style))
    dur = data["breakage_duration"]
    if not dur.empty:
        for col in ["TOTAL_NET_BREAKAGE", "AVG_NET_BREAKAGE", "AVG_DAYS_TO_BREAKAGE",
                     "MEDIAN_DAYS_TO_BREAKAGE", "MIN_DAYS", "MAX_DAYS", "BREAKAGE_EVENTS"]:
            if col in dur.columns:
                dur[col] = pd.to_numeric(dur[col], errors="coerce")
    elements.append(_make_table(
        dur,
        col_labels=["Studio", "Category", "Events", "Total Net Breakage",
                     "Avg Breakage", "Avg Days", "Median Days", "Min", "Max"],
        col_widths=[1.8*inch, 1.4*inch, 0.7*inch, 1.2*inch,
                    1.0*inch, 0.8*inch, 0.9*inch, 0.6*inch, 0.6*inch],
        formatters={2: _fmt_num, 3: _fmt_money, 4: _fmt_money,
                    5: _fmt_num, 6: _fmt_num, 7: _fmt_num, 8: _fmt_num},
    ))

    # ============================
    # PAGE 2: Top Clients — Earned Revenue
    # ============================
    elements.append(PageBreak())
    elements.append(Paragraph("MIGHTY PILATES", ParagraphStyle(
        "PageHeader", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#5A6B8A"), spaceAfter=4,
    )))
    elements.append(Paragraph(f"Top Clients by Earned Revenue  |  {period_label}", section_style))

    te_display = data["top_earned"]
    if not te_display.empty:
        for col in ["GROSS_EARNED_REVENUE", "NET_EARNED_REVENUE", "TOTAL_SESSIONS", "PACKAGES_PURCHASED"]:
            if col in te_display.columns:
                te_display[col] = pd.to_numeric(te_display[col], errors="coerce")
    elements.append(_make_table(
        te_display,
        col_labels=["Studio", "#", "Client", "Gross Earned", "Net Earned", "Sessions", "Packages"],
        col_widths=[1.8*inch, 0.4*inch, 2.0*inch, 1.3*inch, 1.3*inch, 0.9*inch, 0.9*inch],
        formatters={1: _fmt_num, 3: _fmt_money, 4: _fmt_money, 5: _fmt_num, 6: _fmt_num},
        max_rows=50,
    ))

    # ============================
    # PAGE 3: Top Clients — Breakage
    # ============================
    elements.append(PageBreak())
    elements.append(Paragraph("MIGHTY PILATES", ParagraphStyle(
        "PageHeader2", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#5A6B8A"), spaceAfter=4,
    )))
    elements.append(Paragraph(f"Top Clients by Breakage Revenue  |  {period_label}", section_style))

    tb_display = data["top_breakage"]
    if not tb_display.empty:
        for col in ["GROSS_BREAKAGE", "NET_BREAKAGE", "TOTAL_SESSIONS_PURCHASED",
                     "SESSIONS_USED", "UTILIZATION_PCT"]:
            if col in tb_display.columns:
                tb_display[col] = pd.to_numeric(tb_display[col], errors="coerce")
    elements.append(_make_table(
        tb_display,
        col_labels=["Studio", "#", "Client", "Gross Breakage", "Net Breakage",
                     "Pkgs", "Sessions Bought", "Used", "Util %"],
        col_widths=[1.6*inch, 0.35*inch, 1.7*inch, 1.1*inch, 1.1*inch,
                    0.55*inch, 1.0*inch, 0.6*inch, 0.6*inch],
        formatters={1: _fmt_num, 3: _fmt_money, 4: _fmt_money,
                    5: _fmt_num, 6: _fmt_num, 7: _fmt_num, 8: _fmt_pct},
        max_rows=50,
    ))

    # ============================
    # PAGE 4: Package Utilization
    # ============================
    elements.append(PageBreak())
    elements.append(Paragraph("MIGHTY PILATES", ParagraphStyle(
        "PageHeader3", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#5A6B8A"), spaceAfter=4,
    )))
    elements.append(Paragraph(f"Package Utilization  |  {period_label}", section_style))

    ut_display = data["utilization"]
    if not ut_display.empty:
        for col in ["PACKAGES", "TOTAL_CAPACITY", "TOTAL_USED", "TOTAL_UNUSED",
                     "UTILIZATION_PCT", "TOTAL_NET_REVENUE", "TOTAL_NET_EARNED", "TOTAL_NET_BREAKAGE"]:
            if col in ut_display.columns:
                ut_display[col] = pd.to_numeric(ut_display[col], errors="coerce")
    elements.append(_make_table(
        ut_display,
        col_labels=["Studio", "Category", "Product", "Pkgs", "Capacity",
                     "Used", "Unused", "Util %", "Net Revenue", "Net Earned", "Net Breakage"],
        col_widths=[1.3*inch, 1.0*inch, 1.8*inch, 0.5*inch, 0.6*inch,
                    0.5*inch, 0.6*inch, 0.6*inch, 0.9*inch, 0.9*inch, 0.9*inch],
        formatters={3: _fmt_num, 4: _fmt_num, 5: _fmt_num, 6: _fmt_num,
                    7: _fmt_pct, 8: _fmt_money, 9: _fmt_money, 10: _fmt_money},
        max_rows=80,
    ))

    # Footer on each page
    def _add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawString(
            0.5 * inch, 0.3 * inch,
            f"Mighty Pilates Usage & Breakage  |  {period_label}  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        canvas.drawRightString(
            landscape(letter)[0] - 0.5 * inch, 0.3 * inch,
            f"Page {doc.page}"
        )
        canvas.restoreState()

    doc.build(elements, onFirstPage=_add_footer, onLaterPages=_add_footer)
    print(f"  PDF saved: {filepath}")
    return str(filepath)


def generate_deep_dive(conn, start_date: str, end_date: str, output_dir: str = None) -> tuple:
    """
    Generate deep dive Excel workbook and PDF management report.

    Returns:
        Tuple of (excel_path, pdf_path).
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    data = _query_deep_dive_data(conn, start_date, end_date)

    print("  Building Excel workbook...")
    excel_path = _build_excel(data, start_date, end_date, output_dir)

    print("  Building PDF report...")
    pdf_path = _build_pdf(data, start_date, end_date, output_dir)

    return excel_path, pdf_path


def generate_prior_month_deep_dive(conn, output_dir: str = None) -> tuple:
    """Generate deep dive for the prior month."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_prior = first_of_month - timedelta(days=1)
    start = last_prior.replace(day=1)
    return generate_deep_dive(
        conn, start.strftime("%Y-%m-%d"), last_prior.strftime("%Y-%m-%d"), output_dir
    )
