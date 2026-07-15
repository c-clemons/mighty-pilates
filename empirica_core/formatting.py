"""Currency and percentage display helpers."""

from __future__ import annotations


def fmt_currency(val: float | int | None, decimals: int = 0) -> str:
    """Format a number as USD with thousands separators.

    Negative values use a leading minus, not parentheses, to match the
    convention already used across CNS/MP/Alma Mater dashboards.

    ``None`` and NaN are rendered as an empty string so callers can safely
    pass missing data through to Streamlit tables.
    """
    if val is None:
        return ""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if v != v:  # NaN
        return ""
    if v < 0:
        return f"-${abs(v):,.{decimals}f}"
    return f"${v:,.{decimals}f}"


def fmt_pct(val: float | int | None, decimals: int = 1) -> str:
    """Format a fraction (0.123 -> '12.3%') with the given decimal places.

    Pass ``None`` or NaN to get an empty string.
    """
    if val is None:
        return ""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if v != v:
        return ""
    return f"{v * 100:.{decimals}f}%"
