"""
Cat-authoritative ClassPass actuals — override for the RESERVATIONS-derived figure.

ClassPass is immediate recognition (GL 401003) and Cat supplies authoritative
per-studio totals with her monthly cash-sales summary. The PLAYLIST_DATAMART
RESERVATIONS feed frequently lags at close time (for the July 2026 close it was
loaded only through 2026-07-26, ~$24-30K light), so both the GL and Saasant
exports substitute Cat's figures for any month present here. Because
`freeze_from_live` regenerates the Saasant export internally, the frozen GL
inherits the override automatically.

Keyed by MONTH_YM → {canonical studio name: amount}. Months not listed here fall
through to the live RESERVATIONS query unchanged.
"""
from __future__ import annotations
import calendar

import pandas as pd

# Canonical studio names must match CANON_STUDIO output used elsewhere in the GL.
CAT_CLASSPASS = {
    "2026-07": {   # Cat's July 2026 summary (2026-08-04); total $171,444
        "Mighty Pilates Presidio Heights": 19210,
        "Mighty Pilates Marin":            13483,
        "Mighty Pilates Santa Monica":     26558,
        "Mighty Pilates Lafayette":        10615,
        "Mighty Pilates Berkeley":         22681,
        "Mighty Pilates Westwood":         10720,
        "Mighty Pilates Russian Hill":     25557,
        "Mighty Pilates Ocean Park":       14609,
        "Mighty Pilates Danville":          4806,
        "Mighty Pilates Culver City":      16616,
        "Mighty Pilates West Portal":          0,
        "Mighty Pilates Santa Barbara":     6589,
    },
}


def classpass_override_df(start_date: str, end_date: str):
    """
    Return a ClassPass override DataFrame (columns MONTH_YM, STUDIO_NAME, AMOUNT,
    GL_CODE) when (start_date, end_date) is exactly one full calendar month that
    has a Cat-authoritative entry. Otherwise return None so the caller uses the
    live RESERVATIONS query. Zero-dollar studios are omitted (mirrors the
    RATE != 0 filter on the live path).
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.day != 1:
        return None
    if (start.year, start.month) != (end.year, end.month):
        return None
    if end.day != calendar.monthrange(start.year, start.month)[1]:
        return None
    month_ym = f"{start.year}-{start.month:02d}"
    studios = CAT_CLASSPASS.get(month_ym)
    if not studios:
        return None
    rows = [
        {"MONTH_YM": month_ym, "STUDIO_NAME": s, "AMOUNT": float(a), "GL_CODE": "401003"}
        for s, a in studios.items()
        if a
    ]
    return pd.DataFrame(rows)
