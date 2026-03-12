"""
Generate GL Export Excel workbook from Snowflake data.
Supports both prior-month and YTD modes.
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

# GL row definitions
GL_ROWS = [
    ("401001", "Machine"),
    ("401002", "Private Pilates"),
    ("401003", "Class Pass"),
    ("401004", "Mighty Teacher Training"),
    ("401005", "Livestream Classes"),
    ("403001", "Machine Breakage"),
    ("403002", "Mighty Teacher Training Breakage"),
    ("403003", "Private Pilates Breakage"),
    ("403004", "Other Breakage"),
    ("404000", "Retail Sales"),
    ("406000", "Refunds"),
    ("407000", "Discounts"),
    ("SALES_TAX", "Sales Tax"),
    ("GCL", "Gift Card Liability"),
    ("POA", "Payments on Account"),
    ("TOTAL_NET_SALES", "Total Net Sales"),
    ("NET_CASH", "Net Cash"),
]

GL_DF = pd.DataFrame(GL_ROWS, columns=["GL_CODE", "GL_NAME"])

# Service type to GL bucket mapping
SERVICE_TYPE_BUCKETS = {
    "Machine": "Machine", "Semi-Private": "Private Pilates", "Workshop": "Machine",
    "Private Class": "Private Pilates", "Trio": "Private Pilates",
    "Apprentice Session": "Machine", "New Teacher Private Special": "Machine",
    "ClassPass": "Class Pass", "Gympass Revenue": "EXCLUDED", "Unused Package": "Breakage Other",
    "Mighty Teacher Training": "Mighty Teacher Training",
    "Master Instructor Privates": "Private Pilates",
    "Contract Enrollment Fee": "EXCLUDED", "Pilates Pods": "Machine",
    "Master Private Pilates": "Private Pilates", "Cassandra LS Series": "Machine",
    "Mat Pilates - At Home": "Livestream Classes", "Rental": "Machine",
    "Apprentice Sessions": "Machine", "Fees": "Machine", "Dynamic Pricing": "Machine",
    "Mighty Core Bootcamp": "Machine", "Livestream": "Livestream Classes",
    "Privates": "Private Pilates", "MMP Member Pop Up": "Machine", "Workshops": "Machine",
    "Retail": "Retail", "Balance Workshop": "Machine", "Outdoor Mat Pilates": "Machine",
    "Unlimited": "Livestream Classes",
    "Pilates Instructor Certification": "Mighty Teacher Training",
    "New Client Special": "Machine", "Online Privates": "Private Pilates",
    "Private": "Private Pilates", "Pilates Teacher Training": "Mighty Teacher Training",
    "Apprentice Duet": "Machine", "10 - Day Health Challenge": "Machine",
    "Advanced Tower Workshop": "Machine", "Livestream Series": "Livestream Classes",
    "Gift Card": "Gift Card", "Account Payment": "EXCLUDED",
    "Online Classes": "Livestream Classes", "Outdoor Mat Classes": "Machine",
    "Apprentice Private Pilates": "Private Pilates", "Private Rental": "Machine",
    "Mighty Pilates Workshops": "Machine", "Mighty Workshops": "Machine",
}

BUCKET_TO_EARNED_GL = {
    "MACHINE": "401001", "PRIVATE PILATES": "401002", "CLASS PASS": "401003",
    "MIGHTY TEACHER TRAINING": "401004", "LIVESTREAM CLASSES": "401005",
}

BUCKET_TO_BREAKAGE_GL = {
    "MACHINE": "403001", "PRIVATE PILATES": "403003",
    "MIGHTY TEACHER TRAINING": "403002",
}

MARIN_CUTOFF = "2025-04-24"

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"


def generate_gl_export(conn, start_date: str, end_date: str, output_dir: str = None) -> str:
    """
    Generate GL Export Excel.

    Args:
        conn: Snowflake connection
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        output_dir: Where to save the file (defaults to outputs/)

    Returns:
        Path to the generated Excel file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    print(f"Generating GL Export: {start_date} to {end_date}")

    # --- Load ledger data ---
    ledger = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(EVENT_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO_NAME,
            SERVICE_TYPE, EVENT_TYPE, ITEM_TYPE, IS_OLD_MIGHTY,
            GROSS_EARNED_REVENUE, NET_EARNED_REVENUE,
            GROSS_BREAKAGE_REVENUE, NET_BREAKAGE_REVENUE,
            GROSS_RETAIL_SALES, NET_RETAIL_SALES,
            GROSS_TOTAL_SALES, TOTAL_DISCOUNTS, NET_TOTAL_SALES,
            GIFT_LIABILITY_CHANGE, IS_RETURN, NET_SESSION_SALES,
            DEFERRED_REVENUE_CHANGE
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE EVENT_DATE >= '{start_date}' AND EVENT_DATE <= '{end_date}'
    """)
    print(f"  Ledger rows: {len(ledger)}")

    # Map service types to buckets
    ledger["BUCKET"] = ledger["SERVICE_TYPE"].map(SERVICE_TYPE_BUCKETS).fillna(ledger["SERVICE_TYPE"])
    ledger["BUCKET_NORM"] = ledger["BUCKET"].str.upper().str.strip()

    gl_entries = []

    # Earned revenue (current + old mighty bucketed together)
    earned = ledger[
        (ledger["GROSS_EARNED_REVENUE"] != 0) &
        (ledger["BUCKET_NORM"] != "EXCLUDED")
    ].copy()
    earned["GL_CODE"] = earned["BUCKET_NORM"].map(BUCKET_TO_EARNED_GL).fillna("401001")
    earned["AMOUNT"] = earned["GROSS_EARNED_REVENUE"]
    gl_entries.append(earned[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # ClassPass revenue
    classpass = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(r.START_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(s.STUDIO_NAME) AS STUDIO_NAME,
            r.RATE_USD AS AMOUNT,
            '401003' AS GL_CODE
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
    """)
    print(f"  ClassPass rows: {len(classpass)}")
    gl_entries.append(classpass)

    # Breakage
    brk = ledger[ledger["GROSS_BREAKAGE_REVENUE"] != 0].copy()
    brk["GL_CODE"] = brk["BUCKET_NORM"].map(BUCKET_TO_BREAKAGE_GL).fillna("403004")
    brk["AMOUNT"] = brk["GROSS_BREAKAGE_REVENUE"]
    gl_entries.append(brk[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # Retail
    retail = ledger[
        (ledger["ITEM_TYPE"] == "Retail Product") & (ledger["GROSS_RETAIL_SALES"] != 0)
    ].copy()
    retail["GL_CODE"] = "404000"
    retail["AMOUNT"] = retail["GROSS_RETAIL_SALES"]
    gl_entries.append(retail[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # Discounts (negative in GL)
    disc = ledger[ledger["TOTAL_DISCOUNTS"] != 0].copy()
    disc["GL_CODE"] = "407000"
    disc["AMOUNT"] = -disc["TOTAL_DISCOUNTS"].abs()
    gl_entries.append(disc[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # Gift card liability
    gift = ledger[ledger["GIFT_LIABILITY_CHANGE"] != 0].copy()
    gift["GL_CODE"] = "GCL"
    gift["AMOUNT"] = -gift["GIFT_LIABILITY_CHANGE"]
    gl_entries.append(gift[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # MART_SALES_DETAILS queries (refunds, total net sales, net cash, POA, sales tax)
    _marin_filter = f"""
        AND NOT (STUDIO_NAME LIKE '%Marin%' AND SALE_DATE < '{MARIN_CUTOFF}'
                 AND EXISTS (
                     SELECT 1 FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS dup
                     WHERE dup.PAYMENT_REF_NO = m.PAYMENT_REF_NO
                       AND dup.CLIENT_ID = m.CLIENT_ID
                       AND dup.PRODUCT_ID = m.PRODUCT_ID
                       AND dup.SALE_DATE = m.SALE_DATE
                       AND dup.STUDIO_NAME LIKE '%Presidio%'
                 ))
    """

    # Refunds
    refunds = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            -1 * ABS(m.GROSS_UNIT_PRICE * m.QUANTITY) AS AMOUNT,
            '406000' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.IS_RETURN = 1
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          {_marin_filter}
          AND ABS(m.GROSS_UNIT_PRICE * m.QUANTITY) != 0
    """)
    gl_entries.append(refunds)

    # Total Net Sales
    tns = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            m.NET_PAYMENTAMT_LOCAL AS AMOUNT,
            'TOTAL_NET_SALES' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.SALES_ONLY_FLAG = 'TRUE'
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          {_marin_filter}
          AND m.NET_PAYMENTAMT_LOCAL != 0
    """)
    gl_entries.append(tns)

    # Net Cash (no Marin dedupe, just exclude pre-cutoff Marin)
    net_cash = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            (m.NET_CASH_ON_HAND + m.ITEMTAX_LOCAL) AS AMOUNT,
            'NET_CASH' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          AND NOT (m.STUDIO_NAME LIKE '%Marin%' AND m.SALE_DATE < '{MARIN_CUTOFF}')
          AND (m.NET_CASH_ON_HAND + m.ITEMTAX_LOCAL) != 0
    """)
    gl_entries.append(net_cash)

    # Payments on Account
    poa = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            m.NET_PAYMENTAMT_LOCAL AS AMOUNT,
            'POA' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.REVENUE_CATEGORY = 'Payments on Account'
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          {_marin_filter}
          AND m.NET_PAYMENTAMT_LOCAL != 0
    """)
    gl_entries.append(poa)

    # Sales Tax
    tax = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            m.ITEMTAX_LOCAL AS AMOUNT,
            'SALES_TAX' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          {_marin_filter}
          AND m.ITEMTAX_LOCAL != 0
    """)
    gl_entries.append(tax)

    # --- Combine and pivot ---
    all_entries = pd.concat(gl_entries, ignore_index=True)
    gl_month = all_entries.groupby(["MONTH_YM", "STUDIO_NAME", "GL_CODE"], as_index=False)["AMOUNT"].sum()
    gl_month = gl_month.merge(GL_DF, on="GL_CODE", how="left")

    # --- Build Excel ---
    print("  Building Excel workbook...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Determine filename
    if start_dt.month == end_dt.month and start_dt.year == end_dt.year:
        label = start_dt.strftime("%b%Y")
    else:
        label = f"YTD_{end_dt.strftime('%b%Y')}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Mighty_GL_{label}_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename

    combined = gl_month.groupby(["MONTH_YM", "GL_CODE", "GL_NAME"], as_index=False)["AMOUNT"].sum()
    combined_full, months = _ensure_full_grid(combined)
    combined_pvt = _pivot_sheet(combined_full)

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as w:
        # Cover
        cover = [
            [f"MIGHTY PILATES - GL EXPORT ({label})", ""],
            ["", ""],
            ["Report Information", ""],
            ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["Report Period", f"{start_date} through {end_date}"],
            ["Source", "DAILY_REVENUE_AND_SALES_DETAIL + CLASSPASS + MART_SALES_DETAILS"],
        ]
        pd.DataFrame(cover).to_excel(w, sheet_name="Cover", index=False, header=False)

        # All Studios
        combined_pvt.to_excel(w, sheet_name="All Studios")

        # Per-studio tabs
        for studio in sorted(gl_month["STUDIO_NAME"].dropna().unique()):
            sdf = gl_month.loc[gl_month["STUDIO_NAME"] == studio, ["MONTH_YM", "GL_CODE", "GL_NAME", "AMOUNT"]]
            full, _ = _ensure_full_grid(sdf)
            pvt = _pivot_sheet(full)
            tab = studio.replace("Mighty Pilates ", "")[:31]
            pvt.to_excel(w, sheet_name=tab)

        # Formatting
        wb = w.book
        money = wb.add_format({"num_format": "#,##0.00"})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2"})
        for name, ws in w.sheets.items():
            if name == "Cover":
                ws.set_column(0, 0, 22)
                ws.set_column(1, 1, 90)
            else:
                ws.set_row(0, None, header_fmt)
                ws.set_column(0, 0, 36)
                ws.set_column(1, 100, 14, money)

    print(f"  Saved: {filepath}")
    return str(filepath)


def generate_prior_month_gl(conn, output_dir: str = None) -> str:
    """Generate GL export for the prior month only."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_prior = first_of_month - timedelta(days=1)
    start = last_prior.replace(day=1)
    return generate_gl_export(conn, start.strftime("%Y-%m-%d"), last_prior.strftime("%Y-%m-%d"), output_dir)


def generate_ytd_gl(conn, output_dir: str = None) -> str:
    """Generate YTD GL export through prior month end."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_prior = first_of_month - timedelta(days=1)
    start = datetime(today.year, 1, 1)
    return generate_gl_export(conn, start.strftime("%Y-%m-%d"), last_prior.strftime("%Y-%m-%d"), output_dir)


def _ensure_full_grid(df: pd.DataFrame):
    if df.empty:
        return pd.DataFrame(columns=["GL_CODE", "GL_NAME", "MONTH_YM", "AMOUNT"]), []
    months = sorted(df["MONTH_YM"].unique())
    full = (
        GL_DF.assign(_k=1)
        .merge(pd.DataFrame({"MONTH_YM": months, "_k": [1] * len(months)}), on="_k")
        .drop(columns="_k")
        .merge(df, on=["GL_CODE", "GL_NAME", "MONTH_YM"], how="left")
    )
    full["AMOUNT"] = full["AMOUNT"].fillna(0.0)
    return full, months


def _pivot_sheet(df_full: pd.DataFrame):
    df_full = df_full.copy()
    df_full["ROW"] = df_full["GL_CODE"].astype(str) + " " + df_full["GL_NAME"].astype(str)
    cats = [f"{c} {n}" for c, n in GL_ROWS]
    df_full["ROW"] = pd.Categorical(df_full["ROW"], categories=cats, ordered=True)
    p = df_full.pivot_table(
        index="ROW", columns="MONTH_YM", values="AMOUNT", aggfunc="sum",
        fill_value=0.0, observed=False
    ).sort_index()
    p["TOTAL"] = p.sum(axis=1)
    return p
