"""
Generate Saasant journal entry Excel for QuickBooks upload.
Prior month only.
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import execute_query_df

CANON_STUDIO_SQL = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS.CANON_STUDIO"
MARIN_CUTOFF = "2025-04-24"

STUDIO_CODES = {
    "Mighty Pilates Berkeley": "BK",
    "Mighty Pilates Culver City": "CC",
    "Mighty Pilates Danville": "DV",
    "Mighty Pilates Lafayette": "LF",
    "Mighty Pilates Marin": "MN",
    "Mighty Pilates Ocean Park": "OP",
    "Mighty Pilates Presidio Heights": "PH",
    "Mighty Pilates Russian Hill": "RH",
    "Mighty Pilates Santa Barbara": "SB",
    "Mighty Pilates Santa Monica": "SM",
    "Mighty Pilates Westwood": "WW",
}

STUDIO_LOCATIONS = {
    "Mighty Pilates Berkeley": "Berkeley",
    "Mighty Pilates Culver City": "Culver City",
    "Mighty Pilates Danville": "Danville",
    "Mighty Pilates Lafayette": "Lafayette",
    "Mighty Pilates Marin": "Marin",
    "Mighty Pilates Ocean Park": "Ocean Park",
    "Mighty Pilates Presidio Heights": "Presidio Heights",
    "Mighty Pilates Russian Hill": "Russian Hill",
    "Mighty Pilates Santa Barbara": "Santa Barbara",
    "Mighty Pilates Santa Monica": "Santa Monica",
    "Mighty Pilates Westwood": "Westwood",
}

SAASANT_ACCOUNTS = {
    "401001": "Machine",
    "401002": "Private Pilates",
    "401003": "Class Pass",
    "401004": "Mighty Teacher Training",
    "401005": "Livestream Classes",
    "403001": "Machine Breakage",
    "403002": "Mighty Teacher Training Breakage",
    "403003": "Private Pilates Breakage",
    "403004": "Other Breakage",
    "404000": "Retail Sales",
    "406000": "Refunds",
    "407000": "Discounts",
}

ACCOUNT_ORDER = [
    "Machine", "Private Pilates", "Class Pass", "Mighty Teacher Training", "Livestream Classes",
    "Machine Breakage", "Mighty Teacher Training Breakage", "Private Pilates Breakage", "Other Breakage",
    "Retail Sales", "Refunds", "Discounts",
]

DEBIT_ACCOUNTS = {"Refunds", "Discounts"}

# Bucket mappings (same as GL export)
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


def generate_saasant_export(conn, start_date: str, end_date: str, output_dir: str = None) -> str:
    """
    Generate Saasant journal entry Excel for QuickBooks upload.

    Returns path to generated file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "outputs"
    Path(output_dir).mkdir(exist_ok=True)

    print(f"Generating Saasant Export: {start_date} to {end_date}")

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    month_label = start_dt.strftime("%b")
    year_label = start_dt.strftime("%Y")
    yymm = end_dt.strftime("%y.%m")

    # Load ledger
    ledger = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(EVENT_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(STUDIO_NAME) AS STUDIO_NAME,
            SERVICE_TYPE, EVENT_TYPE, ITEM_TYPE, IS_OLD_MIGHTY,
            GROSS_EARNED_REVENUE, NET_EARNED_REVENUE,
            GROSS_BREAKAGE_REVENUE, NET_BREAKAGE_REVENUE,
            GROSS_RETAIL_SALES, TOTAL_DISCOUNTS,
            GIFT_LIABILITY_CHANGE, IS_RETURN, DEFERRED_REVENUE_CHANGE
        FROM DAILY_REVENUE_AND_SALES_DETAIL
        WHERE EVENT_DATE >= '{start_date}' AND EVENT_DATE <= '{end_date}'
    """)
    print(f"  Ledger rows: {len(ledger)}")

    ledger["BUCKET"] = ledger["SERVICE_TYPE"].map(SERVICE_TYPE_BUCKETS).fillna(ledger["SERVICE_TYPE"])
    ledger["BUCKET_NORM"] = ledger["BUCKET"].str.upper().str.strip()

    gl_entries = []

    # Earned revenue
    earned = ledger[
        (ledger["GROSS_EARNED_REVENUE"] != 0) & (ledger["BUCKET_NORM"] != "EXCLUDED")
    ].copy()
    earned["GL_CODE"] = earned["BUCKET_NORM"].map(BUCKET_TO_EARNED_GL).fillna("401001")
    earned["AMOUNT"] = earned["GROSS_EARNED_REVENUE"]
    gl_entries.append(earned[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # ClassPass
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

    # Discounts (absolute value — sign handled in journal entry logic)
    disc = ledger[ledger["TOTAL_DISCOUNTS"] != 0].copy()
    disc["GL_CODE"] = "407000"
    disc["AMOUNT"] = disc["TOTAL_DISCOUNTS"].abs()
    gl_entries.append(disc[["MONTH_YM", "STUDIO_NAME", "AMOUNT", "GL_CODE"]])

    # Refunds
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
    refunds = execute_query_df(conn, f"""
        SELECT
            TO_VARCHAR(m.SALE_DATE, 'YYYY-MM') AS MONTH_YM,
            {CANON_STUDIO_SQL}(m.STUDIO_NAME) AS STUDIO_NAME,
            ABS(m.GROSS_UNIT_PRICE * m.QUANTITY) AS AMOUNT,
            '406000' AS GL_CODE
        FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS m
        WHERE m.IS_RETURN = 1
          AND m.SALE_DATE >= '{start_date}' AND m.SALE_DATE <= '{end_date}'
          {_marin_filter}
          AND ABS(m.GROSS_UNIT_PRICE * m.QUANTITY) != 0
    """)
    gl_entries.append(refunds)

    # Combine
    all_entries = pd.concat(gl_entries, ignore_index=True)
    # Snowflake returns Decimal types → pandas object dtype; convert to float
    all_entries["AMOUNT"] = pd.to_numeric(all_entries["AMOUNT"], errors="coerce").astype(float)
    gl_month = all_entries.groupby(["STUDIO_NAME", "GL_CODE"], as_index=False)["AMOUNT"].sum()
    gl_month["ACCOUNT"] = gl_month["GL_CODE"].map(SAASANT_ACCOUNTS)

    # Deferred revenue per studio (for balancing entry)
    ledger["DEFERRED_REVENUE_CHANGE"] = pd.to_numeric(ledger["DEFERRED_REVENUE_CHANGE"], errors="coerce").astype(float)
    deferred = ledger.groupby("STUDIO_NAME", as_index=False)["DEFERRED_REVENUE_CHANGE"].sum()
    deferred.rename(columns={"DEFERRED_REVENUE_CHANGE": "DEFERRED_TOTAL"}, inplace=True)

    # Build journal entries with Excel SUM formula for deferred revenue balancing
    rows = []
    excel_row = 2  # Row 1 is header

    for studio_name in sorted(gl_month["STUDIO_NAME"].dropna().unique()):
        code = STUDIO_CODES.get(studio_name, "XX")
        location = STUDIO_LOCATIONS.get(studio_name, studio_name.replace("Mighty Pilates ", ""))
        journal_no = f"MB Rev {code} {yymm}"
        description = f"Mindbody Earned Revenue {code} - {yymm}"

        studio_data = gl_month[gl_month["STUDIO_NAME"] == studio_name].copy()
        studio_data["ACCOUNT"] = studio_data["ACCOUNT"].fillna("Other")

        # Sort by account order
        account_order_map = {a: i for i, a in enumerate(ACCOUNT_ORDER)}
        studio_data["sort_key"] = studio_data["ACCOUNT"].map(account_order_map).fillna(999)
        studio_data = studio_data.sort_values("sort_key")

        first_row_num = excel_row
        first_entry = True

        for _, row in studio_data.iterrows():
            account = row["ACCOUNT"]
            amount = row["AMOUNT"]
            if abs(amount) < 0.005:
                continue

            # Sign convention: credits negative, debits positive
            if account in DEBIT_ACCOUNTS:
                signed_amount = amount
            else:
                signed_amount = -amount

            entry = {
                "Journal No": journal_no if first_entry else f"=A{first_row_num}",
                "Journal Date": end_dt.strftime("%Y-%m-%d") if first_entry else None,
                "Memo": None,
                " Account ": account,
                " Amount": round(signed_amount, 2),
                " Description": description if first_entry else f"=F{first_row_num}",
                "Name": None,
                "Location": location,
                "Class ": None,
                "Currency Code": None,
                "Exchange Rate": None,
                "Is Adjustment": None,
            }
            rows.append(entry)
            first_entry = False
            excel_row += 1

        # Deferred Revenue balancing entry — uses SUM formula to force balance
        last_detail_row = excel_row - 1
        rows.append({
            "Journal No": f"=A{first_row_num}",
            "Journal Date": None,
            "Memo": None,
            " Account ": "Deferred  Revenue",
            " Amount": f"=-SUM(E{first_row_num}:E{last_detail_row})",
            " Description": f"=F{first_row_num}",
            "Name": None,
            "Location": location,
            "Class ": None,
            "Currency Code": None,
            "Exchange Rate": None,
            "Is Adjustment": None,
        })
        excel_row += 1

    result_df = pd.DataFrame(rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Saasant_Upload_{month_label}_{year_label}_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename

    # Write with xlsxwriter to preserve formulas
    with pd.ExcelWriter(filepath, engine="xlsxwriter") as writer:
        result_df.to_excel(writer, index=False, sheet_name="Journal Entries")
        wb = writer.book
        ws = writer.sheets["Journal Entries"]
        money_fmt = wb.add_format({"num_format": "#,##0.00"})
        date_fmt = wb.add_format({"num_format": "mm/dd/yyyy"})
        ws.set_column("A:A", 18)
        ws.set_column("B:B", 12, date_fmt)
        ws.set_column("D:D", 30)
        ws.set_column("E:E", 16, money_fmt)
        ws.set_column("F:F", 40)
        ws.set_column("H:H", 20)

    print(f"  Journal entries: {len(result_df)}")
    print(f"  Studios: {result_df['Journal No'].nunique()}")
    print(f"  Saved: {filepath}")
    return str(filepath)


def generate_prior_month_saasant(conn, output_dir: str = None) -> str:
    """Generate Saasant export for the prior month only."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_prior = first_of_month - timedelta(days=1)
    start = last_prior.replace(day=1)
    return generate_saasant_export(
        conn, start.strftime("%Y-%m-%d"), last_prior.strftime("%Y-%m-%d"), output_dir
    )
