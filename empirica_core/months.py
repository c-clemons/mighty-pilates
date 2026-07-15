"""Month key/label helpers used by every Empirica dashboard.

The canonical month key is ``YYYY-MM`` (e.g. ``'2026-03'``). Parsers convert
free-form headers like ``'March 2026'`` or ``'Mar 2026'`` into this form so
downstream code only has to deal with one shape.
"""

from __future__ import annotations

import calendar
from typing import Optional

MONTHS: list[str] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


def month_key(year: int, month: int) -> str:
    """Return the canonical ``YYYY-MM`` key for a (year, month) pair."""
    return f"{year}-{month:02d}"


def month_display(key: str) -> str:
    """Convert a ``YYYY-MM`` key to a human label like ``'Mar 2026'``."""
    year, month = key.split("-")
    return f"{calendar.month_abbr[int(month)]} {year}"


def parse_accountant_month(col_name: str) -> Optional[str]:
    """Parse a column header like ``'February 2026'`` or ``'Feb 2026'`` into
    the canonical ``YYYY-MM`` form. Returns ``None`` if the input doesn't
    match the expected shape.
    """
    if not col_name:
        return None
    parts = col_name.strip().split()
    if len(parts) != 2:
        return None
    month_str, year_str = parts
    if not year_str.isdigit():
        return None
    m = MONTH_MAP.get(month_str.lower())
    if m is None:
        return None
    return f"{year_str}-{m:02d}"
