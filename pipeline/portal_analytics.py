"""Publish report analytics to tables the portal reads.

The reports in `reports/` build Excel and PDF for people. The portal needs the
same numbers on a screen. Rather than the portal querying the marts a second time
with its own definitions -- which is how two "instructor revenue" figures come to
exist and disagree -- the close publishes, and the portal reads. Same contract as
`portal_publish.py` for earned and breakage.

**The SQL here is lifted from the report modules, deliberately and with
attribution.** It is not an improvement on them and must not drift from them:

    instructor_summary   reports/instructor_performance.py, tab 1
    membership_summary   reports/membership_churn.py, tabs 1 and 3
    client_segments      reports/client_lifecycle.py, tab 4

Those reports still build their own workbooks from their own copies. That
duplication is real and is recorded in the backlog: the right end state is the
reports importing from here. Publishing first, refactoring the system of record
second, is the safer order -- the close runs on those reports every month.

Everything is written to ONE tidy table so a new metric needs no migration:
(metric, month, dimension_1, dimension_2, value_name, value).
"""

from datetime import date, datetime, timedelta

import pandas as pd

from pipeline.connection import execute_query_df, execute_sql

SCHEMA = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS"
TABLE = f"{SCHEMA}.PORTAL_ANALYTICS"
MB = "PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS"
CANON = f"{SCHEMA}.CANON_STUDIO"

# Every published row travels inside the CTAS statement text, so the set has to
# stay small. Past this, aggregate further rather than raising the ceiling.
MAX_ROWS = 6000


def _window(months: int) -> tuple[str, str]:
    end = date.today()
    start = (end.replace(day=1) - timedelta(days=31 * months)).replace(day=1)
    return start.isoformat(), end.isoformat()


# --- lifted from reports/instructor_performance.py, tab 1 -------------------
def instructor_summary(conn, start: str, end: str) -> pd.DataFrame:
    """Trailing-window totals per instructor, not a month-by-month grid.

    The portal shows who is teaching and how full their classes are. Publishing
    the full monthly cross-product is ~23,000 tidy rows, and this Snowflake
    account is a READER account where the only way to write is CTAS -- so every
    row travels inside the statement text. Aggregate first, publish second.
    """
    return execute_query_df(conn, f"""
        SELECT ''                                              AS MONTH,
               {CANON}(v.STUDIO_NAME)                          AS STUDIO,
               v.TRAINER_FULL_NAME                             AS INSTRUCTOR,
               SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
                        THEN 1 ELSE 0 END)                     AS COMPLETED,
               COUNT(*)                                        AS BOOKED,
               COUNT(DISTINCT v.CLIENT_ID)                     AS UNIQUE_CLIENTS,
               COUNT(DISTINCT v.CLASS_ID)                      AS CLASSES,
               ROUND(SUM(v.GROSS_REVENUE_ATTRIBUTION_LOCAL), 2) AS GROSS_REVENUE,
               ROUND(SUM(v.IS_CANCELLED + v.IS_MISSED) * 100.0
                     / NULLIF(COUNT(*), 0), 1)                 AS CANCEL_NOSHOW_RATE_PCT
        FROM {MB}.MART_VISITS v
        WHERE v.CLASS_DATE >= '{start}' AND v.CLASS_DATE <= '{end}'
          AND v.TRAINER_FULL_NAME IS NOT NULL
        GROUP BY 1, 2, 3
        HAVING SUM(CASE WHEN v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
                        THEN 1 ELSE 0 END) > 0
    """)


# --- lifted from reports/membership_churn.py, tabs 1 and 3 ------------------
def membership_summary(conn, start: str, end: str) -> pd.DataFrame:
    return execute_query_df(conn, f"""
        WITH daily AS (
            SELECT DATE, STUDIO_NAME, MEMBERSHIP_NAME,
                   IS_UNIQUE_ACTIVE_MEMBER, IS_UNIQUE_NEW_MEMBER,
                   IS_UNIQUE_CHURN_MEMBER, IS_UNIQUE_SUSPENDED_MEMBER,
                   IS_UNIQUE_REACTIVATED_MEMBER
            FROM {MB}.MART_MEMBERSHIP_DAILY_DETAILS
            WHERE DATE >= '{start}' AND DATE <= '{end}'
        ),
        eom AS (
            SELECT DATE_TRUNC('month', DATE)::DATE AS M, MAX(DATE) AS D
            FROM daily GROUP BY 1
        )
        SELECT TO_VARCHAR(DATE_TRUNC('month', d.DATE), 'YYYY-MM') AS MONTH,
               d.STUDIO_NAME                                      AS STUDIO,
               ''                                                 AS MEMBERSHIP,
               SUM(CASE WHEN d.DATE = e.D THEN d.IS_UNIQUE_ACTIVE_MEMBER ELSE 0 END)
                                                                  AS ACTIVE_EOM,
               SUM(CASE WHEN d.DATE = e.D THEN d.IS_UNIQUE_SUSPENDED_MEMBER ELSE 0 END)
                                                                  AS SUSPENDED_EOM,
               SUM(d.IS_UNIQUE_NEW_MEMBER)                        AS NEW_MEMBERS,
               SUM(d.IS_UNIQUE_CHURN_MEMBER)                      AS CHURNED,
               SUM(d.IS_UNIQUE_REACTIVATED_MEMBER)                AS REACTIVATED
        FROM daily d
        JOIN eom e ON e.M = DATE_TRUNC('month', d.DATE)::DATE
        GROUP BY 1, 2, 3
    """)


# --- lifted from reports/membership_churn.py, tab 4 ------------------------
def membership_mix(conn, start: str, end: str) -> pd.DataFrame:
    """Membership types at the latest month end only -- a mix, not a trend."""
    return execute_query_df(conn, f"""
        WITH latest AS (SELECT MAX(DATE) AS D FROM {MB}.MART_MEMBERSHIP_DAILY_DETAILS
                        WHERE DATE <= '{end}')
        SELECT TO_VARCHAR(l.D, 'YYYY-MM')                      AS MONTH,
               d.STUDIO_NAME                                   AS STUDIO,
               COALESCE(d.MEMBERSHIP_NAME, 'Unspecified')      AS MEMBERSHIP,
               SUM(d.IS_UNIQUE_ACTIVE_MEMBER)                  AS ACTIVE
        FROM {MB}.MART_MEMBERSHIP_DAILY_DETAILS d
        JOIN latest l ON d.DATE = l.D
        GROUP BY 1, 2, 3
        HAVING SUM(d.IS_UNIQUE_ACTIVE_MEMBER) > 0
    """)


# --- lifted from reports/client_lifecycle.py, tab 4 -------------------------
def client_segments(conn, start: str, end: str) -> pd.DataFrame:
    """Active / lapsed / dormant / lost, on days since the client's last visit."""
    return execute_query_df(conn, f"""
        WITH last_seen AS (
            SELECT {CANON}(STUDIO_NAME) AS STUDIO,
                   CLIENT_ID,
                   MAX(CLASS_DATE)::DATE AS LAST_VISIT
            FROM {MB}.MART_VISITS
            WHERE COALESCE(IS_MISSED_OR_CANCELLED, 0) = 0
              AND CLASS_DATE <= '{end}'
            GROUP BY 1, 2
        )
        SELECT TO_VARCHAR('{end}'::DATE, 'YYYY-MM')          AS MONTH,
               STUDIO,
               CASE WHEN DATEDIFF('day', LAST_VISIT, '{end}'::DATE) <= 30  THEN 'active'
                    WHEN DATEDIFF('day', LAST_VISIT, '{end}'::DATE) <= 90  THEN 'lapsed'
                    WHEN DATEDIFF('day', LAST_VISIT, '{end}'::DATE) <= 365 THEN 'dormant'
                    ELSE 'lost' END                          AS SEGMENT,
               COUNT(DISTINCT CLIENT_ID)                     AS CLIENTS
        FROM last_seen
        GROUP BY 1, 2, 3
    """)


PUBLISHERS = {
    "instructor_summary": (instructor_summary,
                           ["STUDIO", "INSTRUCTOR"],
                           ["COMPLETED", "BOOKED", "UNIQUE_CLIENTS", "CLASSES",
                            "GROSS_REVENUE", "CANCEL_NOSHOW_RATE_PCT"]),
    "membership_summary": (membership_summary,
                           ["STUDIO", "MEMBERSHIP"],
                           ["ACTIVE_EOM", "SUSPENDED_EOM", "NEW_MEMBERS",
                            "CHURNED", "REACTIVATED"]),
    "membership_mix": (membership_mix, ["STUDIO", "MEMBERSHIP"], ["ACTIVE"]),
    "client_segments": (client_segments,
                        ["STUDIO", "SEGMENT"],
                        ["CLIENTS"]),
}


def publish(conn, months: int = 13) -> dict:
    """Run every publisher and replace the table. Idempotent."""
    start, end = _window(months)
    rows: list[dict] = []
    counts: dict[str, int] = {}
    for metric, (fn, dims, values) in PUBLISHERS.items():
        df = fn(conn, start, end)
        counts[metric] = len(df)
        for _, r in df.iterrows():
            for value_name in values:
                v = r.get(value_name)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                rows.append({
                    "METRIC": metric,
                    "MONTH": str(r.get("MONTH") or "")[:7],
                    "DIM1": str(r.get(dims[0]) or "")[:120],
                    "DIM2": str(r.get(dims[1]) or "")[:120] if len(dims) > 1 else "",
                    "VALUE_NAME": value_name,
                    "VALUE": float(v),
                })

    if not rows:
        raise RuntimeError("nothing to publish")

    # CTAS, never INSERT. This Snowflake account is a READER account, and
    # `INSERT INTO` fails on it with "Operation is not supported in reader
    # account" -- which is why frozen_gl.py and portal_publish.py are both written
    # as CREATE OR REPLACE ... AS SELECT ... UNION ALL. That is a constraint of
    # the account, not a stylistic choice; do not "simplify" it to an INSERT.
    #
    # Rebuilt whole: these are trailing-window analytics, not frozen months, so
    # there is no closed period to protect and a partial replace would leave a
    # month half old and half new.
    # The FIRST select in a UNION carries the column names; `column1` aliasing
    # only works for a VALUES list, not a union of selects.
    def row_sql(r: dict, named: bool = False) -> str:
        a = (lambda n: f" AS {n}") if named else (lambda n: "")
        return (f"SELECT $${r['METRIC']}$$::VARCHAR{a('METRIC')}, "
                f"$${r['MONTH']}$$::VARCHAR{a('MONTH')}, "
                f"$${r['DIM1']}$$::VARCHAR{a('DIM1')}, "
                f"$${r['DIM2']}$$::VARCHAR{a('DIM2')}, "
                f"$${r['VALUE_NAME']}$$::VARCHAR{a('VALUE_NAME')}, "
                f"{r['VALUE']}::FLOAT{a('VALUE')}, "
                f"CURRENT_TIMESTAMP()::TIMESTAMP_LTZ{a('PUBLISHED_AT')}, "
                f"$${start}$$::VARCHAR{a('WINDOW_START')}, "
                f"$${end}$$::VARCHAR{a('WINDOW_END')}")

    # ONE statement. Appending chunk by chunk rewrites the whole table each time,
    # which is quadratic and took minutes; and every row has to travel inside the
    # SQL text anyway, since this account cannot INSERT. So keep the published
    # set small enough to send at once, and fail loudly rather than silently
    # publishing a truncated view.
    if len(rows) > MAX_ROWS:
        raise RuntimeError(
            f"{len(rows):,} rows to publish, over the {MAX_ROWS:,} ceiling. This "
            f"account can only write by CTAS, so the whole set travels in the "
            f"statement. Aggregate further rather than raising the limit.")

    body = " UNION ALL ".join(row_sql(r, named=(i == 0)) for i, r in enumerate(rows))
    execute_sql(conn, f"CREATE OR REPLACE TABLE {TABLE} AS {body}")

    return {"rows": len(rows), "metrics": counts, "start": start, "end": end}
