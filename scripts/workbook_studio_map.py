"""
Row map between the external workbook's studio P&L tabs and committed_actuals.

The studio tabs roll several QBO accounts into one presentation row (e.g.
"602001 Wages (incl 1099 & Bonus)" = 602001 + 602002 + 602003). This module
holds that mapping and a validator that proves it, by recomputing an
already-populated actuals month from committed_actuals.json and diffing against
the values sitting in the workbook.

Never edit the map without re-running the validator:

    python scripts/refresh_external_workbook.py --validate --month "Jun 2026"
"""
from __future__ import annotations

# Normalized studio-tab row label -> list of committed_actuals account keys.
# NEGATE marks rows the workbook shows QBO-native-negative while the per-studio
# JSON tree stores them positive (see pipeline/dashboard_update.py).
STUDIO_ROW_MAP: dict[str, list[str]] = {
    # --- Revenue -------------------------------------------------------
    # 401007 Off-Site is a Crew-added account ($150/mo at SB since May 2026).
    # The studio tabs have no row for it and inserting one would shift every
    # row number that the cross-tab formulas depend on, so it is folded into
    # Machine here — matching how the Jun 2026 workbook was built by hand, and
    # keeping each studio's subtotals tied to consolidated. QBO Actuals carries
    # it on its own row (r92) so the accountant mirror stays faithful.
    "401001 Machine": ["401001 Machine", "401007 Off-Site"],
    "401002 Private Pilates": ["401002 Private Pilates"],
    "401003 Class Pass": ["401003 Class Pass"],
    "401004 Mighty Teacher Training": ["401004 Mighty Teacher Training"],
    "401005 Livestream Classes": ["401005 Livestream Classes"],
    "401006 Wellhub": ["401006 Wellhub"],
    "Revenue from Old Mighty": ["402000 Revenue from Old Mighty"],
    "403001 Machine Breakage": ["403001 Machine Breakage"],
    "403003 Private Pilates Breakage": ["403003 Private Pilates Breakage"],
    "403004 Other Breakage (incl MTT Breakage)": [
        "403004 Other Breakage",
        "403002 Mighty Teacher Training Breakage",
    ],
    "404000 Retail Sales": ["404000 Retail Sales"],
    "406000 Refunds": ["406000 Refunds"],
    "407000 Discounts": ["407000 Discounts"],
    # --- COGS ----------------------------------------------------------
    "501000 Product Cost (incl Inventory Shrinkage)": [
        "501000 Product Cost",
        "Inventory Shrinkage",
    ],
    "506000 Merchant Account Fees": ["506000 Merchant Account Fees"],
    # --- Marketing -----------------------------------------------------
    "601001 Paid Ads": ["601001 Paid Ads"],
    "601005 Content Creation": ["601005 Content Creation"],
    "601006 General Marketing (incl Affiliate, PR, Trade Shows)": [
        "601006 General Marketing",
        "601011 Trade Shows/Events",
        "601009 Public Relations",
    ],
    "601007 Contractors/Agencies": ["601007 Marketing Contractors/Agencies"],
    "601010 Website Development": ["601010 Website Development"],
    # --- Payroll -------------------------------------------------------
    "602001 Wages (incl 1099 & Bonus)": [
        "602001 Wages",
        "602002 1099 Compensation",
        "602003 Bonus",
    ],
    "602004 Payroll Taxes": ["602004 Payroll Taxes"],
    "602005 Employee Benefits (incl Workers Comp)": [
        "602005 Employee Benefits",
        "602006 Worker's Comp Ins",
    ],
    "602010 Payroll Processing Fees": ["602010 Payroll Processing Fees"],
    # --- Software & admin ----------------------------------------------
    "603000 Software & Web Services": ["603000 Software & Web Services"],
    "608000 Insurance": ["608000 Insurance"],
    "610000 Office Supplies & GE (incl Licenses, Furniture, Shipping, Bank Fees, Start-Up Costs)": [
        "610000 Office Supplies & General Expense",
        "609000 Business licenses",
        "610100 Furniture & Equipment",
        "611000 Shipping & postage",
        "613000 Bank fees & Service Charges",
        "630000 Studio Start Up Costs",
    ],
    # --- Professional fees ---------------------------------------------
    "604100 Legal Fees": ["604100 Legal Fees"],
    "604200 Accounting": ["604200 Accounting"],
    "604300 Recruiting": ["604300 Recruiting"],
    "604400 Other Professional Fees": ["604400 Other Professional Fees"],
    # --- Travel & meals -------------------------------------------------
    "605000 Travel": ["605000 Travel (Airfare/hotel/ground trans/etc)"],
    "606000 Meals (incl Entertainment)": ["606000 Meals", "607000 Entertainment"],
    # --- Utilities ------------------------------------------------------
    "616001 Electricity": ["616001 Electricity"],
    "616002 Internet & TV": ["616002 Internet & TV services"],
    "616003 Phone service": ["616003 Phone service"],
    "616004 Water & sewer": ["616004 Water & sewer"],
    "616005 Disposal Services": ["616005 Disposal Services"],
    # --- Property -------------------------------------------------------
    "701000 Rent": ["701000 Rent"],
    "702000 Security": ["702000 Security"],
    "703000 Cleaning": ["703000 Cleaning"],
    "705000 Property Maintenance (incl Repairs & Parking)": [
        "705000 Property Maintenance",
        "704000 Studio Repairs",
        "615000 Parking Lot Rental",
    ],
    # --- Below the line --------------------------------------------------
    "810000 Depreciation": ["810000 Depreciation"],
    "901000 Interest Expense (incl Other Exp/Inc)": [
        "901000 Interest Expense/(Income)",
        "900000 Other Expense/(Income)",
    ],
    "902000 Taxes Paid": ["902000 Taxes Paid"],
    "903000 Property taxes": ["903000 Property taxes"],
}

# Rows the workbook carries QBO-native-negative.
NEGATE = {"406000 Refunds", "407000 Discounts"}

# Section headers and formula-driven subtotal rows. These are never written as
# values — subtotals are left as the workbook's own formulas.
SKIP_LABELS = {
    "INCOME",
    "COST OF GOODS SOLD",
    "OPERATING EXPENSES",
    "OTHER",
    "Total Sessions",
    "Total Breakage Revenue",
    "TOTAL REVENUE",
    "Total Cost of Goods Sold",
    "GROSS PROFIT",
    "Total Marketing",
    "Total Payroll",
    "Total Software & Admin",
    "Total Professional Fees",
    "Total Travel & Meals",
    "Total Utilities",
    "Total Property Costs",
    "TOTAL OPERATING EXPENSES",
    "NET OPERATING INCOME (EBITDA)",
    "Total Other Expenses",
    "NET INCOME",
}


def normalize(label: object) -> str:
    """Collapse a workbook row label to its map key."""
    return " ".join(str(label).split()) if label is not None else ""


def studio_row_value(month_data: dict, label: str) -> float | None:
    """Resolve one studio-tab row label to a value for the given month.

    Returns None when the label is a header/subtotal (caller should skip it).
    """
    key = normalize(label)
    if key in SKIP_LABELS:
        return None
    accounts = STUDIO_ROW_MAP.get(key)
    if accounts is None:
        raise KeyError(key)
    total = sum(month_data.get(a, 0.0) or 0.0 for a in accounts)
    return round(-total if key in NEGATE else total, 2)


# ---------------------------------------------------------------- HO P&L ---
# Head Office is overhead-only and uses its own row labels, different
# aggregations, and — at r33 / r39 — the SAME label ("902000 Taxes
# (Franchise/State)") on two different rows: an unused slot in the operating
# block and the real one below the line. Label keys can't disambiguate that, so
# HO is mapped by row number. The layout is fixed; the validator will catch it
# if that ever stops being true.
HO_ROW_MAP: dict[int, list[str]] = {
    7: ["601001 Paid Ads"],
    8: ["601005 Content Creation"],
    9: ["601006 General Marketing", "601009 Public Relations",
        "601011 Trade Shows/Events"],
    10: ["601007 Marketing Contractors/Agencies"],
    11: ["601010 Website Development"],
    13: ["602001 Wages", "602002 1099 Compensation", "602003 Bonus"],
    14: ["602004 Payroll Taxes"],
    15: ["602005 Employee Benefits", "602006 Worker's Comp Ins"],
    16: ["602010 Payroll Processing Fees"],
    18: ["603000 Software & Web Services"],
    19: ["608000 Insurance"],
    20: ["610000 Office Supplies & General Expense", "610100 Furniture & Equipment",
         "611000 Shipping & postage", "609000 Business licenses",
         "630000 Studio Start Up Costs",
         "616001 Electricity", "616002 Internet & TV services",
         "616003 Phone service", "616004 Water & sewer",
         "616005 Disposal Services"],
    21: ["613000 Bank fees & Service Charges"],
    23: ["604100 Legal Fees"],
    24: ["604200 Accounting"],
    25: ["604300 Recruiting"],
    26: ["604400 Other Professional Fees"],
    28: ["605000 Travel (Airfare/hotel/ground trans/etc)"],
    29: ["606000 Meals", "607000 Entertainment"],
    31: ["701000 Rent", "703000 Cleaning", "704000 Studio Repairs",
         "705000 Property Maintenance", "702000 Security",
         "615000 Parking Lot Rental"],
    33: [],                                   # unused slot; keep at 0
    38: ["810000 Depreciation"],
    39: ["902000 Taxes Paid"],                # the real taxes row
    40: ["901000 Interest Expense/(Income)"],
    41: ["900000 Other Expense/(Income)"],
}


def ho_row_value(month_data: dict, row: int) -> float | None:
    """Resolve one HO P&L row to a value. None => leave the row alone."""
    accounts = HO_ROW_MAP.get(row)
    if accounts is None:
        return None
    return round(sum(month_data.get(a, 0.0) or 0.0 for a in accounts), 2)


# ------------------------------------------------------- manual adjustments ---
# Deliberate model adjustments layered on top of the accountant's numbers. These
# are NOT in committed_actuals.json — they were entered by hand in the workbook
# and must be carried forward, or the model silently changes meaning.
#
# HO P&L r40 (901000 Interest Expense): +$1,666.67/month, present in every
# column from Mar 2026 onward ($20K/yr). Jan-Feb 2026 tie to the accountant
# exactly, so this began deliberately in March. Most likely accrued interest the
# accountant is not booking.
#
# CONFIRMED KEEP — Chandler, 2026-08-24. Carry it forward every month. It is
# applied on top of the accountant's figure, so HO "Total Other Expenses" and
# "NET INCOME" will always sit $1,666.67 above Crew's package. That is expected;
# do not "fix" it. To retire it, delete the entry and the workbook will fall
# straight back to the accountant's numbers.
MANUAL_ADJUSTMENTS: dict[tuple[str, int], float] = {
    ("HO P&L", 40): 1_666.67,
}


def manual_adjustment(tab: str, row: int) -> float:
    return MANUAL_ADJUSTMENTS.get((tab, row), 0.0)
