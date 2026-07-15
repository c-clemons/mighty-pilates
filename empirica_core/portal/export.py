"""Client-facing export helpers — download the board package as Excel.

PDF export stays per-client (layouts differ; see each dashboard's
``pages/export_pdf.py``), but a multi-sheet Excel export is identical
everywhere, so it lives here.
"""
from __future__ import annotations

import io
from typing import Mapping


def export_excel(sheets: Mapping[str, "Any"]) -> bytes:  # noqa: F821 - pandas DataFrame
    """Return an ``.xlsx`` byte string with one sheet per ``{name: DataFrame}``.

    Sheet names are truncated to Excel's 31-char limit.
    """
    import pandas as pd  # noqa: F401 - imported for its ExcelWriter

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=str(name)[:31])
    return buf.getvalue()


def download_excel_button(label: str, sheets: Mapping[str, "Any"],  # noqa: F821
                          file_name: str) -> None:
    """Render an ``st.download_button`` that emits the multi-sheet workbook."""
    import streamlit as st

    st.download_button(
        label=label,
        data=export_excel(sheets),
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


__all__ = ["export_excel", "download_excel_button"]
