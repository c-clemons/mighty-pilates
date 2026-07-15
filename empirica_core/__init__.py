"""Shared utilities for Empirica Analytics CFO dashboards.

The util layer (``formatting``, ``months``, ``qbo``, ``datastore``,
``github_sync``) is dependency-light. The Streamlit UI kit lives under
``empirica_core.portal`` and requires the ``portal`` extra
(``pip install empirica-core[portal]``) — it is intentionally NOT imported
here so importing the utils never pulls in Streamlit.
"""

__version__ = "0.2.0"

from empirica_core.datastore import BaseDataStore
from empirica_core.formatting import fmt_currency, fmt_pct
from empirica_core.months import (
    MONTH_MAP,
    MONTHS,
    month_display,
    month_key,
    parse_accountant_month,
)

__all__ = [
    "fmt_currency",
    "fmt_pct",
    "month_key",
    "month_display",
    "parse_accountant_month",
    "MONTH_MAP",
    "MONTHS",
    "BaseDataStore",
]
