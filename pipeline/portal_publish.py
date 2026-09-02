"""Publish revenue recognition to a table the portal reads.

The portal must not reimplement revenue recognition. Two implementations of the
same model is how they silently disagree, and the one on a screen in front of the
client is the one nobody re-derives. So the close publishes, and the portal
reads.

Two tables serve two different questions:

  FROZEN_MONTHLY_GL       already published by `freeze-gl`. Earned and breakage
                          by GL account, studio and month, tied to the Saasant
                          journal entry. This is the AUTHORITY on magnitude.

  PORTAL_REVENUE_VINTAGE  published here. The same month's recognised revenue
                          split by the month the package was PURCHASED, which is
                          what "of a month's sales, how much is eventually used
                          versus expired" needs and the GL cannot answer.

**The two do not tie, and that is recorded rather than hidden.** The vintage
detail (`DAILY_REVENUE_AND_SALES_DETAIL`) runs roughly 6% below the frozen GL on
earned revenue. So every published row carries the frozen total for its month and
the ratio between them: the portal shows the MIX from this table and the LEVEL
from the frozen GL, and can say by how much the detail under-runs. Presenting the
vintage totals as though they were the recognised revenue would put two
disagreeing numbers on one page.
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd

from pipeline.connection import execute_query_df, execute_sql

SCHEMA = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS"
TABLE = f"{SCHEMA}.PORTAL_REVENUE_VINTAGE"
SOURCE_TABLE = f"{SCHEMA}.DAILY_REVENUE_AND_SALES_DETAIL"
FROZEN = f"{SCHEMA}.FROZEN_MONTHLY_GL"

# The vintage detail is a different population from the JE and runs below it.
# Beyond this the gap is no longer the known basis difference and the publish
# should be looked at rather than trusted.
MAX_UNDERRUN = 0.15


def _month_bounds(month_ym: str) -> tuple[str, str]:
    y, m = map(int, month_ym.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1)
    return start.isoformat(), (end - timedelta(days=1)).isoformat()


def source_loaded_through(conn, month_ym: str) -> Optional[str]:
    """Last EVENT_DATE actually present, ignoring future-dated junk.

    The mart carries rows dated into 2029 from future-dated sales, so a bare
    max() reports the feed as years ahead of itself.
    """
    _, end = _month_bounds(month_ym)
    df = execute_query_df(conn, f"""
        SELECT MAX(EVENT_DATE)::DATE AS D
        FROM {SOURCE_TABLE}
        WHERE EVENT_DATE <= CURRENT_DATE()
    """)
    v = df.iloc[0]["D"]
    return None if pd.isna(v) else str(v)[:10]


def frozen_totals(conn, month_ym: str) -> dict:
    """Earned and breakage for the month from the frozen GL, in GL convention."""
    df = execute_query_df(conn, f"""
        SELECT
          SUM(CASE WHEN LEFT(GL_CODE,3)='401' AND GL_CODE<>'401003' THEN AMOUNT ELSE 0 END) AS EARNED,
          SUM(CASE WHEN LEFT(GL_CODE,3)='403' THEN AMOUNT ELSE 0 END) AS BREAKAGE,
          SUM(CASE WHEN GL_CODE='401003' THEN AMOUNT ELSE 0 END) AS CLASSPASS
        FROM {FROZEN} WHERE MONTH_YM = '{month_ym}'
    """)
    if df.empty:
        return {}
    r = df.iloc[0]
    return {k: (0.0 if pd.isna(r[k]) else float(r[k]))
            for k in ("EARNED", "BREAKAGE", "CLASSPASS")}


def pull_vintage(conn, month_ym: str) -> pd.DataFrame:
    """Recognised revenue in the month, by studio and purchase month."""
    start, end = _month_bounds(month_ym)
    return execute_query_df(conn, f"""
        SELECT STUDIO_NAME,
               TO_CHAR(DATE_TRUNC('month', PURCHASE_DATE), 'YYYY-MM') AS PURCHASE_MONTH,
               SUM(NET_EARNED_REVENUE)   AS NET_EARNED,
               SUM(NET_BREAKAGE_REVENUE) AS NET_BREAKAGE
        FROM {SOURCE_TABLE}
        WHERE EVENT_DATE BETWEEN '{start}' AND '{end}'
          AND PURCHASE_DATE IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def publish_month(conn, month_ym: str, force: bool = False) -> dict:
    """Publish one month's vintage split. Idempotent: republishing replaces it."""
    frozen = frozen_totals(conn, month_ym)
    if not frozen or (frozen["EARNED"] == 0 and frozen["BREAKAGE"] == 0):
        raise RuntimeError(
            f"{month_ym} is not in FROZEN_MONTHLY_GL. The close publishes the GL "
            f"first — run `freeze-gl --month {month_ym}` before publishing to the "
            f"portal, so the vintage split has an authority to be stated against.")

    loaded = source_loaded_through(conn, month_ym)
    _, end = _month_bounds(month_ym)
    if loaded is not None and loaded < end and not force:
        raise RuntimeError(
            f"{SOURCE_TABLE.split('.')[-1]} is loaded only through {loaded}, but "
            f"{month_ym} ends {end}. Publishing now would ship a part-month as a "
            f"whole one. Wait for the load, or pass force=True knowingly.")

    df = pull_vintage(conn, month_ym)
    if df.empty:
        raise RuntimeError(f"no vintage rows for {month_ym}")

    detail_earned = float(df["NET_EARNED"].sum())
    detail_breakage = float(df["NET_BREAKAGE"].sum())
    ratio_e = (detail_earned / frozen["EARNED"]) if frozen["EARNED"] else None
    ratio_b = (detail_breakage / frozen["BREAKAGE"]) if frozen["BREAKAGE"] else None

    for label, ratio in (("earned", ratio_e), ("breakage", ratio_b)):
        if ratio is not None and abs(1 - ratio) > MAX_UNDERRUN and not force:
            raise RuntimeError(
                f"{month_ym} {label}: the vintage detail is {(1-ratio)*100:+.1f}% "
                f"from the frozen GL, beyond the {MAX_UNDERRUN*100:.0f}% band. "
                f"That is no longer the known basis difference — check the source "
                f"before publishing, or pass force=True.")

    parts = []
    for _, r in df.iterrows():
        studio = str(r["STUDIO_NAME"]).replace("$", "")
        parts.append(
            f"SELECT '{month_ym}', $${studio}$$, '{r['PURCHASE_MONTH']}', "
            f"{float(r['NET_EARNED'])}, {float(r['NET_BREAKAGE'])}, "
            f"{frozen['EARNED']}, {frozen['BREAKAGE']}, CURRENT_TIMESTAMP(), "
            f"$${SOURCE_TABLE}$$")
    values = " UNION ALL ".join(parts)

    execute_sql(conn, f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            MONTH_YM VARCHAR, STUDIO_NAME VARCHAR, PURCHASE_MONTH VARCHAR,
            NET_EARNED NUMBER(38,4), NET_BREAKAGE NUMBER(38,4),
            FROZEN_EARNED NUMBER(38,4), FROZEN_BREAKAGE NUMBER(38,4),
            PUBLISHED_AT TIMESTAMP_LTZ, SOURCE VARCHAR)
    """)
    # Same shape as the frozen-GL rebuild: everything but this month, plus this
    # month. Republishing a month replaces it and touches nothing else.
    execute_sql(conn, f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT MONTH_YM, STUDIO_NAME, PURCHASE_MONTH, NET_EARNED, NET_BREAKAGE,
               FROZEN_EARNED, FROZEN_BREAKAGE, PUBLISHED_AT, SOURCE
        FROM {TABLE} WHERE MONTH_YM != '{month_ym}'
        UNION ALL
        {values}
    """)

    return {
        "month": month_ym, "rows": len(df),
        "studios": int(df["STUDIO_NAME"].nunique()),
        "vintages": int(df["PURCHASE_MONTH"].nunique()),
        "detail_earned": detail_earned, "detail_breakage": detail_breakage,
        "frozen_earned": frozen["EARNED"], "frozen_breakage": frozen["BREAKAGE"],
        "ratio_earned": ratio_e, "ratio_breakage": ratio_b,
        "source_loaded_through": loaded,
    }
