"""
Static lookups for the Mighty Pilates dashboard.
Studio lists, GL codes, expense categories, cash flow line items.
"""

from collections import OrderedDict

# ---------------------------------------------------------------------------
# Studios
# ---------------------------------------------------------------------------
ACTIVE_STUDIOS = OrderedDict([
    ("BK", "Berkeley"),
    ("CC", "Culver City"),
    ("DN", "Danville"),
    ("LF", "Lafayette"),
    ("MR", "Marin"),
    ("OP", "Ocean Park"),
    ("PH", "Presidio Heights"),
    ("RH", "Russian Hill"),
    ("SB", "Santa Barbara"),
    ("SM", "Santa Monica"),
    ("WW", "Westwood"),
])

DEVELOPMENT_STUDIOS = OrderedDict([
    ("CDM", "Corona Del Mar"),
    ("PS", "Pasadena"),
    ("WP", "West Portal"),
])

OVERHEAD = {"HO": "Head Office"}

PIPELINE_STUDIOS = OrderedDict([
    ("NP", "Napa"),
    ("SMR", "San Marino"),
    ("PM", "Piedmont"),
    ("BA", "Burlington Arcade"),
    ("LF2", "Los Feliz"),
    ("BK2", "Berkeley #2"),
    ("LG", "Los Gatos"),
])

ALL_STUDIOS = OrderedDict(
    list(ACTIVE_STUDIOS.items())
    + list(DEVELOPMENT_STUDIOS.items())
    + list(OVERHEAD.items())
    + list(PIPELINE_STUDIOS.items())
)

# Studio tiers and types for new studio templates
STUDIO_TIERS = ["Tier 1", "Tier 2"]
STUDIO_TYPES = ["Single Studio Hot", "Single Studio Warm", "Single Studio Cool", "Double Studio"]

# ---------------------------------------------------------------------------
# GL codes — Revenue
# ---------------------------------------------------------------------------
REVENUE_GL = OrderedDict([
    ("401001", "Machine"),
    ("401002", "Private Pilates"),
    ("401003", "Class Pass"),
    ("401004", "Mighty Teacher Training"),
    ("401005", "Livestream Classes"),
    ("401006", "Wellhub"),
    ("402000", "Revenue from Old Mighty"),
    ("403001", "Machine Breakage"),
    ("403002", "MTT Breakage"),
    ("403003", "Private Pilates Breakage"),
    ("403004", "Other Breakage"),
    ("404000", "Retail Sales"),
    ("406000", "Refunds"),
    ("407000", "Discounts"),
])

# Groupings for cash flow display
SESSIONS_GL = ["401001", "401002", "401003", "401004", "401005", "401006"]
BREAKAGE_GL = ["403001", "403002", "403003", "403004"]
OLD_MIGHTY_GL = ["402000"]
RETAIL_GL = ["404000"]
REFUNDS_GL = ["406000"]
DISCOUNTS_GL = ["407000"]

# Accountant P&L row labels → GL groupings (for parsing actuals)
PL_LABEL_MAP = {
    "Total for 401000 Sessions": "sessions",
    "Total for 403000 Breakage Revenue": "breakage",
    "404000 Retail Sales": "retail",
    "406000 Refunds": "refunds",
    "407000 Discounts": "discounts",
    "402000 Revenue from Old Mighty": "old_mighty",
    "Total for Income": "total_income",
    "Total for Cost of Goods Sold": "total_cogs",
    "Gross Profit": "gross_profit",
    "Total for 601000 Sales & Marketing": "marketing",
    "Total for 602000 Payroll": "payroll",
    "603000 Software & Web Services": "software",
    "Total for 604000 Professional Fees": "professional_fees",
    "605000 Travel (Airfare/hotel/ground trans/etc)": "travel",
    "606000 Meals": "meals",
    "607000 Entertainment": "entertainment",
    "608000 Insurance": "insurance",
    "609000 Business licenses": "licenses",
    "610000 Office Supplies & General Expense": "office_supplies",
    "610100 Furniture & Equipment": "furniture_equip",
    "611000 Shipping & postage": "shipping",
    "613000 Bank fees & Service Charges": "bank_fees",
    "615000 Parking Lot Rental": "parking",
    "Total for 616000 Utilities": "utilities",
    "630000 Studio Start Up Costs": "startup_costs",
    "Total for 700000 Property Costs": "property_costs",
    "Total for Expenses": "total_expenses",
    "Net Operating Income": "net_operating_income",
    "810000 Depreciation": "depreciation",
    "901000 Interest Expense/(Income)": "interest",
    "902000 Taxes Paid": "taxes",
    "903000 Property taxes": "property_taxes",
    "Net Income": "net_income",
}

# Studio P&L uses "Total Income" instead of "Total for Income"
STUDIO_PL_LABEL_MAP = {
    "Total 401000 Sessions": "sessions",
    "Total 403000 Breakage Revenue": "breakage",
    **{k: v for k, v in PL_LABEL_MAP.items()
       if k not in ("Total for 401000 Sessions", "Total for 403000 Breakage Revenue")},
}

# ---------------------------------------------------------------------------
# Operating expense categories (for the cash flow forecast)
# ---------------------------------------------------------------------------
OPEX_CATEGORIES = OrderedDict([
    ("property", "Property Costs"),
    ("staff", "Staff Costs"),
    ("utilities", "Utilities"),
    ("marketing", "Marketing & Promotion"),
    ("admin", "Administrative & G&A"),
    ("professional_fees", "Professional Fees"),
    ("travel", "Travel & Meals"),
    ("finance", "Merchant Fees & COGS"),
    ("startup", "Studio Start Up Costs"),
])

# Map P&L labels to opex categories for forecasting
PL_TO_OPEX_CATEGORY = {
    "property_costs": "property",
    "payroll": "staff",
    "utilities": "utilities",
    "marketing": "marketing",
    "software": "admin",
    "insurance": "admin",
    "licenses": "admin",
    "office_supplies": "admin",
    "furniture_equip": "admin",
    "shipping": "admin",
    "bank_fees": "admin",
    "parking": "admin",
    "professional_fees": "professional_fees",
    "travel": "travel",
    "meals": "travel",
    "entertainment": "travel",
    "startup_costs": "startup",
}

# ---------------------------------------------------------------------------
# Cash flow statement structure
# ---------------------------------------------------------------------------
CF_OPERATIONS_INFLOW = [
    ("sessions", "Sessions Revenue"),
    ("breakage", "Breakage Revenue"),
    ("retail", "Retail Sales"),
    ("old_mighty", "Revenue from Old Mighty"),
    ("refunds", "Refunds"),
    ("discounts", "Discounts"),
]

CF_OPERATIONS_OUTFLOW = [
    ("property", "Property Costs"),
    ("staff", "Staff Costs"),
    ("utilities", "Utilities"),
    ("marketing", "Marketing & Promotion"),
    ("admin", "Administrative & G&A"),
    ("professional_fees", "Professional Fees"),
    ("travel", "Travel & Meals"),
    ("finance", "Merchant Fees & COGS"),
    ("startup", "Studio Start Up Costs"),
    ("taxes", "Taxes"),
]

CF_INVESTING = [
    ("equipment", "Equipment & Furniture"),
    ("leasehold", "Leasehold Improvements"),
    ("deposits", "Security Deposits"),
    ("depreciation", "Depreciation (non-cash add-back)"),
]

CF_FINANCING = [
    ("loan_proceeds", "Loan Proceeds"),
    ("loan_repayments", "Loan Repayments"),
    ("intercompany", "Intercompany / Owner"),
]

# ---------------------------------------------------------------------------
# Forecast settings
# ---------------------------------------------------------------------------
FORECAST_MONTHS = 24  # 2-year forward horizon

# Month display format
def month_key(year: int, month: int) -> str:
    """Standard month key: '2026-03'."""
    return f"{year}-{month:02d}"


def month_display(key: str) -> str:
    """Convert '2026-03' to 'Mar 2026'."""
    import calendar
    parts = key.split("-")
    return f"{calendar.month_abbr[int(parts[1])]} {parts[0]}"


def parse_accountant_month(col_name: str) -> str:
    """Convert 'February 2026' or 'Feb 2026' to '2026-02'."""
    import calendar
    parts = col_name.strip().split()
    if len(parts) != 2:
        return None
    month_str, year_str = parts
    # Try full month name first, then abbreviation
    for i, name in enumerate(calendar.month_name):
        if name and month_str.lower().startswith(name[:3].lower()):
            return f"{year_str}-{i:02d}"
    return None
