"""
Lender Cohort & Retention Packet.

Built for the lender data request forwarded by Cat (2026-08-10). The workbook is
deliberately narrow: one tab per question the lender actually asked, in their
order, and nothing else.

Tabs:
 0. Summary                  — the lender's 10 asks, each with a direct answer
 1. Methodology              — definitions, filters, and caveats
 2. Demographics             — profile of the typical customer, with fill rates
 3. Cohort Retention         — % of each join-month cohort still active
 4. Customer Lifetime        — how long customers and members stay
 5. Churn and Retention      — monthly member churn since 2021
 6. Customer LTV             — cumulative net sales per cohort member
 7. Acquisition Channel      — where customers say they came from
 8. ClassPass Behavior       — do ClassPass customers ever buy directly
 9. Membership vs Package    — customer and sales mix
 10. Non-Member Repurchase   — how often package buyers come back

Deliberately NOT included:
  - CAC / LTV:CAC. Cat is producing these; marketing spend lives in the P&L,
    not the warehouse, and only a blended figure is derivable here anyway.
  - Trailing-twelve-month revenue totals. They do not tie to the P&L (aggregator
    revenue never reaches client-level sales), so publishing them next to the
    financials would invite a reconciliation question with no good answer.

"LTV" throughout means lifetime NET SALES — cash collected from the customer.
It is not recognized revenue and will not tie to the GL, which is deferral-based.

Client identity uses EARNED_REVENUE_ANALYTICS.CLIENT_XWALK.GLOBAL_CLIENT_KEY so
one person visiting multiple studios counts once. Studio-level CLIENT_ID would
overstate customer counts by ~16%.

Usage:
    python run.py cohorts                       # all available history (2021-01 on)
    python run.py cohorts --start 2022-01       # later cohort start
"""

import re
import pandas as pd
from datetime import datetime
from pathlib import Path

from pipeline.connection import execute_query_df, execute_sql

DATAMART = "PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS"
ERA = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS"
XWALK = f"{ERA}.CLIENT_XWALK"
CANON_STUDIO = f"{ERA}.CANON_STUDIO"

# Transaction history in the mart begins here. This is "all time" as far as the
# warehouse is concerned. Cohorts before this date would be left-censored, so
# anyone whose true first sale predates it is excluded.
DATA_START = "2021-01-01"

MAX_MONTH_INDEX = 36
MILESTONES = [3, 6, 12, 24]


# ---------------------------------------------------------------------------
# Base tables
# ---------------------------------------------------------------------------

def _build_base_tables(conn, start_month: str):
    """Create session-temp tables the rest of the report reads from.

    Filters are lifted from sql/revenue_recognition.sql so this workbook counts
    the same dollars the GL model does:
      - ClassPass passthrough lines: ClassPass pays those, not the customer.
      - Unpaid pricing options (no PAYMENT_REF_NO) are comps, not sales.
      - CATEGORY_ID in (-6, -64, -73) are internal/staff categories.

    Zero-value rows are dropped too. ClassPass and Gympass pricing options land
    in MART_SALES_DETAILS at $0 because the aggregator pays Mighty outside this
    table — 48.5k ClassPass and 5.6k Gympass rows in the trailing year alone.
    Leaving them in would count an aggregator visitor as a paying customer and
    roughly double the package segment.
    """
    print("  Building base tables...")

    # --- Identities that are not real customers ---
    # MindBody is an operational system: front-desk staff create placeholder
    # profiles for walk-ins and comps, and studios have their own logins. These
    # collapse many different people into one identity, which is harmless for a
    # revenue total but ruinous for per-customer metrics — 'walk-in|walk-in'
    # would appear as a single customer with hundreds of purchases.
    #
    # Rule (b) is the general catch: a name-only key means no email was ever
    # captured, and someone with no email at three or more separate studios is a
    # front-desk placeholder, not a person. It may drop a genuine customer or
    # two; leaving the placeholders in distorts far more.
    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_EXCLUDED_KEYS AS
        WITH fanout AS (
            SELECT GLOBAL_CLIENT_KEY AS GCK, COUNT(*) AS SRC_ROWS
            FROM {XWALK} GROUP BY 1
        )
        SELECT GCK,
               CASE
                 WHEN GCK ILIKE '%@mightypilates.com' OR GCK ILIKE '%@norbrook%'
                   THEN 'a. internal / studio account'
                 WHEN SRC_ROWS >= 3
                   THEN 'b. name-only identity reused across 3+ studios'
                 ELSE 'c. placeholder name pattern'
               END AS REASON
        FROM fanout
        WHERE GCK ILIKE '%@mightypilates.com'
           OR GCK ILIKE '%@norbrook%'
           -- Name-only keys only, matched on whole pipe-delimited tokens
           -- (first|last). Substring matching against an email address catches
           -- real people: 'charlottestrykerreed' and 'paigenicolettestclair'
           -- both contain 'test', and excluding them cost ~$26k of genuine sales.
           OR (GCK NOT LIKE '%@%' AND (
                 SRC_ROWS >= 3
                 OR ARRAYS_OVERLAP(
                      SPLIT(LOWER(GCK), '|'),
                      ARRAY_CONSTRUCT('walk-in', 'walk in', 'walkin', 'reserve',
                                      'online guest', 'guest', 'redacted', 'n/a',
                                      'na', 'unknown', 'test', 'house', 'comp'))))
    """)

    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_SALES AS
        SELECT
            x.GLOBAL_CLIENT_KEY                       AS GCK,
            s.SALE_DATE,
            DATE_TRUNC('MONTH', s.SALE_DATE)          AS SALE_MONTH,
            s.NET_PAYMENTAMT_LOCAL                    AS NET_SALES,
            s.IS_AUTOPAY,
            {CANON_STUDIO}(s.STUDIO_NAME)             AS STUDIO
        FROM {DATAMART}.MART_SALES_DETAILS s
        JOIN {XWALK} x
          ON x.STUDIO_ID = s.STUDIO_ID AND x.CLIENT_ID = s.CLIENT_ID
        WHERE s.SALE_DATE >= '{DATA_START}'
          AND s.SALE_DATE <= CURRENT_DATE()
          AND (s.PRODUCT_DESCRIPTION != 'ClassPass' OR s.PRODUCT_DESCRIPTION IS NULL)
          AND (s.ITEM_TYPE != 'Pricing Option' OR s.PAYMENT_REF_NO IS NOT NULL OR s.IS_RETURN = 1)
          AND s.CATEGORY_ID NOT IN (-6, -64, -73)
          AND COALESCE(s.NET_PAYMENTAMT_LOCAL, 0) <> 0
          AND x.GLOBAL_CLIENT_KEY NOT IN (SELECT GCK FROM COH_EXCLUDED_KEYS)
          -- Marin/Presidio duplicate rows. When Marin split off from Presidio
          -- Heights, sales before 2025-04-24 were written under both studios.
          -- 1,272 rows / $282k of double-counted sales. The GL model drops
          -- these (sql/revenue_recognition.sql); so must anything customer-level,
          -- or those customers show inflated lifetime value.
          AND NOT EXISTS (
              SELECT 1 FROM {DATAMART}.MART_SALES_DETAILS dup
              WHERE dup.PAYMENT_REF_NO = s.PAYMENT_REF_NO
                AND dup.CLIENT_ID = s.CLIENT_ID
                AND dup.PRODUCT_ID = s.PRODUCT_ID
                AND dup.SALE_DATE = s.SALE_DATE
                AND dup.STUDIO_NAME LIKE '%Presidio%'
                AND s.STUDIO_NAME LIKE '%Marin%'
                AND s.SALE_DATE < '2025-04-24'
          )
    """)

    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_VISITS AS
        SELECT
            x.GLOBAL_CLIENT_KEY                       AS GCK,
            v.CLASS_DATE,
            DATE_TRUNC('MONTH', v.CLASS_DATE)         AS VISIT_MONTH,
            v.CLASSPASS_SOURCE
        FROM {DATAMART}.MART_VISITS v
        JOIN {XWALK} x
          ON x.STUDIO_ID = v.STUDIO_ID AND x.CLIENT_ID = v.CLIENT_ID
        WHERE v.CLASS_DATE >= '{DATA_START}'
          AND v.CLASS_DATE <= CURRENT_DATE()
          AND COALESCE(v.IS_CANCELLED, 0) = 0
          AND COALESCE(v.IS_MISSED, 0) = 0
          AND x.GLOBAL_CLIENT_KEY NOT IN (SELECT GCK FROM COH_EXCLUDED_KEYS)
    """)

    # MART_CLIENTS has one row per (studio, client); collapse to one per person.
    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_CLIENTS AS
        SELECT
            x.GLOBAL_CLIENT_KEY                       AS GCK,
            MIN(c.FIRST_SALE_DATE)                    AS TRUE_FIRST_SALE_DATE,
            MAX(c.GENDER)                             AS GENDER,
            MAX(c.AGE_BUCKET)                         AS AGE_BUCKET,
            MAX(c.BIRTHDATE)                          AS BIRTHDATE,
            MAX(c.POSTALCODE)                         AS POSTALCODE,
            MAX(c.CITY)                               AS CITY,
            MAX(c.STATE)                              AS STATE,
            MAX(c.REFERRED_BY)                        AS REFERRED_BY,
            MAX(c.CLASSPASS_STATUS)                   AS CLASSPASS_STATUS
        FROM {DATAMART}.MART_CLIENTS c
        JOIN {XWALK} x
          ON x.STUDIO_ID = c.STUDIO_ID AND x.CLIENT_ID = c.CLIENT_ID
        WHERE x.GLOBAL_CLIENT_KEY NOT IN (SELECT GCK FROM COH_EXCLUDED_KEYS)
        GROUP BY 1
    """)

    # A customer belongs to the month of their first PAID purchase. Requiring the
    # true first sale to also fall in the window keeps long-tenured customers
    # from being miscounted as new when history begins.
    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_COHORT AS
        WITH first_paid AS (
            SELECT GCK, MIN(SALE_MONTH) AS COHORT_MONTH
            FROM COH_SALES WHERE NET_SALES > 0 GROUP BY 1
        )
        SELECT f.GCK, f.COHORT_MONTH, c.REFERRED_BY, c.CLASSPASS_STATUS
        FROM first_paid f
        JOIN COH_CLIENTS c ON c.GCK = f.GCK
        WHERE f.COHORT_MONTH >= '{start_month}-01'
          AND c.TRUE_FIRST_SALE_DATE >= '{DATA_START}'
    """)

    execute_sql(conn, f"""
        CREATE OR REPLACE TEMPORARY TABLE COH_MEMBERS AS
        SELECT x.GLOBAL_CLIENT_KEY AS GCK,
               MIN(m.FIRST_MEMBERSHIP_ACTIVATION_DATE) AS FIRST_ACTIVATION
        FROM {DATAMART}.MART_MEMBERSHIP_DAILY_DETAILS m
        JOIN {XWALK} x ON x.STUDIO_ID = m.STUDIO_ID AND x.CLIENT_ID = m.CLIENT_ID
        WHERE m.IS_ACTIVE_MEMBERSHIP = 1
          AND x.GLOBAL_CLIENT_KEY NOT IN (SELECT GCK FROM COH_EXCLUDED_KEYS)
        GROUP BY 1
    """)

    # Lifetime net sales per customer — reused by several tabs.
    execute_sql(conn, """
        CREATE OR REPLACE TEMPORARY TABLE COH_LTV AS
        SELECT GCK,
               SUM(NET_SALES)                                          AS LIFETIME_NET_SALES,
               COUNT(DISTINCT CASE WHEN NET_SALES > 0 THEN SALE_DATE END) AS PURCHASE_OCCASIONS,
               MIN(SALE_DATE)                                          AS FIRST_SALE,
               MAX(SALE_DATE)                                          AS LAST_SALE
        FROM COH_SALES GROUP BY 1
    """)

    excluded = execute_query_df(conn, """
        SELECT REASON, COUNT(*) AS KEYS FROM COH_EXCLUDED_KEYS GROUP BY 1 ORDER BY 1
    """)
    for _, e in excluded.iterrows():
        print(f"    excluded {int(e.KEYS):>3} identities — {e.REASON}")

    r = execute_query_df(conn, """
        SELECT (SELECT COUNT(*) FROM COH_SALES)   AS SALES_ROWS,
               (SELECT COUNT(*) FROM COH_COHORT)  AS COHORT_CLIENTS,
               (SELECT COUNT(*) FROM COH_MEMBERS) AS EVER_MEMBERS
    """).iloc[0]
    print(f"    sales={int(r.SALES_ROWS):,}  customers={int(r.COHORT_CLIENTS):,}  "
          f"ever-members={int(r.EVER_MEMBERS):,}")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

CHANNEL_RULES = [
    ("ClassPass",            r"class\s*pass"),
    ("Wellhub / Gympass",    r"wellhub|gympass"),
    ("Other aggregator",     r"zenrez|groupon|living\s*social|bloomspot|mindbody\s*app"),
    ("Word of mouth",        r"another\s*client|friend|referr|word\s*of\s*mouth|family"),
    ("Staff / instructor",   r"instructor|front\s*desk|staff|owner|teacher"),
    ("Walk-by / signage",    r"walk|drove|drive\s*by|signage|sign|window|flier|flyer|postcard"),
    ("Search / web",         r"google|yelp|web\s*search|internet|search|bing"),
    ("Social media",         r"instagram|facebook|tiktok|social|blog"),
    ("Email / newsletter",   r"email|newsletter|mailer"),
    ("Event / partnership",  r"event|corporate|partner|pop\s*up|popup"),
]

NOT_CAPTURED = "Not captured"
_BLANKISH = {"", "0", "-", "n/a", "na", "none", "null", "unknown", "."}


def _is_blank(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    return str(value).strip().lower() in _BLANKISH


def _normalize_channel(value) -> str:
    if _is_blank(value):
        return NOT_CAPTURED
    low = str(value).strip().lower()
    for label, pattern in CHANNEL_RULES:
        if re.search(pattern, low):
            return label
    return "Other"


# Cities arrive hand-typed at signup: "SAN FRANCISCO", "san francisco", and
# "San  Francisco" are all the same place. Normalize case and spacing, then fold
# the handful of known variants that casing alone will not merge.
CITY_ALIASES = {
    "Sf": "San Francisco",
    "S.f.": "San Francisco",
    "San Fransisco": "San Francisco",
    "San Franciso": "San Francisco",
    "La": "Los Angeles",
    "L.a.": "Los Angeles",
    "Santa Monica Ca": "Santa Monica",
    "Nyc": "New York",
    "New York City": "New York",
}


def _normalize_city(value) -> str:
    if _is_blank(value):
        return NOT_CAPTURED
    city = re.sub(r"\s+", " ", str(value).strip()).title()
    city = re.sub(r"[.,]+$", "", city).strip()
    return CITY_ALIASES.get(city, city)


def _normalize_state(value) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip().upper()[:2]


# ---------------------------------------------------------------------------
# Tab builders — one per lender question
# ---------------------------------------------------------------------------

def _demographics(conn) -> dict:
    # MindBody stores an unset gender as the literal string 'None', not SQL NULL,
    # so a naive COUNT treats it as populated and overstates coverage by ~26pts.
    blank = ("CASE WHEN TRIM(COALESCE({c}, '')) IN ('', 'None', 'none', 'NULL', '0') "
             "THEN NULL ELSE TRIM({c}) END")
    g = blank.format(c="GENDER")

    fill = execute_query_df(conn, f"""
        SELECT 'Gender' AS FIELD, ROUND(100.0 * COUNT({g}) / COUNT(*), 1) AS PCT_POPULATED
        FROM COH_CLIENTS WHERE GCK IN (SELECT GCK FROM COH_COHORT)
        UNION ALL SELECT 'Age (from birthdate)',
               ROUND(100.0 * COUNT(BIRTHDATE) / COUNT(*), 1)
        FROM COH_CLIENTS WHERE GCK IN (SELECT GCK FROM COH_COHORT)
        UNION ALL SELECT 'City / State',
               ROUND(100.0 * COUNT({blank.format(c='CITY')}) / COUNT(*), 1)
        FROM COH_CLIENTS WHERE GCK IN (SELECT GCK FROM COH_COHORT)
        UNION ALL SELECT 'Referral source',
               ROUND(100.0 * COUNT({blank.format(c='REFERRED_BY')}) / COUNT(*), 1)
        FROM COH_CLIENTS WHERE GCK IN (SELECT GCK FROM COH_COHORT)
    """)
    fill["PCT_POPULATED"] = pd.to_numeric(fill["PCT_POPULATED"]) / 100.0

    gender = execute_query_df(conn, f"""
        SELECT COALESCE({g}, '{NOT_CAPTURED}') AS GENDER, COUNT(*) AS CUSTOMERS
        FROM COH_CLIENTS WHERE GCK IN (SELECT GCK FROM COH_COHORT)
        GROUP BY 1 ORDER BY 2 DESC
    """)
    gender["CUSTOMERS"] = pd.to_numeric(gender["CUSTOMERS"])
    known = gender.loc[gender["GENDER"] != NOT_CAPTURED, "CUSTOMERS"].sum()
    gender["PCT_OF_KNOWN"] = gender.apply(
        lambda r: pd.NA if r["GENDER"] == NOT_CAPTURED else r["CUSTOMERS"] / known, axis=1)

    age = execute_query_df(conn, """
        SELECT CASE WHEN AGE_BUCKET IS NULL OR AGE_BUCKET = 'Other'
                    THEN 'Not captured' ELSE AGE_BUCKET END AS AGE_BAND,
               COUNT(*)                                     AS CUSTOMERS,
               ROUND(AVG(t.LIFETIME_NET_SALES), 2)          AS AVG_LIFETIME_NET_SALES
        FROM COH_CLIENTS c
        JOIN COH_COHORT k ON k.GCK = c.GCK
        LEFT JOIN COH_LTV t ON t.GCK = c.GCK
        GROUP BY 1
        ORDER BY CASE AGE_BAND WHEN 'Below 20' THEN 1 WHEN '21-30' THEN 2
                 WHEN '31-40' THEN 3 WHEN '41-50' THEN 4 WHEN '51-60' THEN 5
                 WHEN '60+' THEN 6 ELSE 7 END
    """)
    age["CUSTOMERS"] = pd.to_numeric(age["CUSTOMERS"])
    known_age = age.loc[age["AGE_BAND"] != NOT_CAPTURED, "CUSTOMERS"].sum()
    age["PCT_OF_KNOWN"] = age.apply(
        lambda r: pd.NA if r["AGE_BAND"] == NOT_CAPTURED else r["CUSTOMERS"] / known_age, axis=1)

    geo_raw = execute_query_df(conn, """
        SELECT c.CITY, c.STATE, COUNT(*) AS CUSTOMERS
        FROM COH_CLIENTS c JOIN COH_COHORT k ON k.GCK = c.GCK
        GROUP BY 1, 2
    """)
    geo_raw["CUSTOMERS"] = pd.to_numeric(geo_raw["CUSTOMERS"])
    geo_raw["CITY_N"] = geo_raw["CITY"].map(_normalize_city)
    geo_raw["STATE_N"] = geo_raw["STATE"].map(_normalize_state)
    # When the city is missing the state is not meaningful either — collapse to
    # a single "Not captured" row rather than one per stray state code.
    geo_raw.loc[geo_raw["CITY_N"] == NOT_CAPTURED, "STATE_N"] = ""
    geo = (geo_raw.groupby(["CITY_N", "STATE_N"], as_index=False)["CUSTOMERS"].sum()
                  .rename(columns={"CITY_N": "CITY", "STATE_N": "STATE"})
                  .sort_values("CUSTOMERS", ascending=False).reset_index(drop=True))

    total = geo["CUSTOMERS"].sum()
    top = geo.head(20).copy()
    remainder = total - top["CUSTOMERS"].sum()
    if remainder > 0:
        top = pd.concat([top, pd.DataFrame(
            [{"CITY": "All other cities", "STATE": "", "CUSTOMERS": remainder}])],
            ignore_index=True)
    top["PCT_OF_CUSTOMERS"] = top["CUSTOMERS"] / total

    return {"fill": fill, "gender": gender, "age": age, "geo": top}


def _cohort_triangles(conn) -> dict:
    sizes = execute_query_df(conn, """
        SELECT TO_VARCHAR(COHORT_MONTH, 'YYYY-MM') AS COHORT,
               COUNT(*) AS COHORT_SIZE,
               DATEDIFF(MONTH, COHORT_MONTH, DATE_TRUNC('MONTH', CURRENT_DATE())) AS MONTHS_MATURE
        FROM COH_COHORT GROUP BY COHORT_MONTH ORDER BY 1
    """)
    active = execute_query_df(conn, f"""
        SELECT TO_VARCHAR(k.COHORT_MONTH, 'YYYY-MM')             AS COHORT,
               DATEDIFF(MONTH, k.COHORT_MONTH, v.VISIT_MONTH)    AS MI,
               COUNT(DISTINCT v.GCK)                             AS ACTIVE_CUSTOMERS
        FROM COH_COHORT k JOIN COH_VISITS v ON v.GCK = k.GCK
        WHERE DATEDIFF(MONTH, k.COHORT_MONTH, v.VISIT_MONTH) BETWEEN 0 AND {MAX_MONTH_INDEX}
        GROUP BY 1, 2
    """)
    ltv = execute_query_df(conn, f"""
        WITH monthly AS (
            SELECT TO_VARCHAR(k.COHORT_MONTH, 'YYYY-MM')          AS COHORT,
                   DATEDIFF(MONTH, k.COHORT_MONTH, s.SALE_MONTH)  AS MI,
                   SUM(s.NET_SALES)                               AS SALES
            FROM COH_COHORT k JOIN COH_SALES s ON s.GCK = k.GCK
            WHERE DATEDIFF(MONTH, k.COHORT_MONTH, s.SALE_MONTH) BETWEEN 0 AND {MAX_MONTH_INDEX}
            GROUP BY 1, 2
        )
        SELECT COHORT, MI,
               SUM(SALES) OVER (PARTITION BY COHORT ORDER BY MI
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS CUM_SALES
        FROM monthly
    """)

    for df, col in ((sizes, "COHORT_SIZE"), (active, "ACTIVE_CUSTOMERS"), (ltv, "CUM_SALES")):
        df[col] = pd.to_numeric(df[col])
    sizes["MONTHS_MATURE"] = pd.to_numeric(sizes["MONTHS_MATURE"])

    size_map = sizes.set_index("COHORT")["COHORT_SIZE"]
    mature_map = sizes.set_index("COHORT")["MONTHS_MATURE"]

    def mask_immature(frame):
        """Blank cells the cohort has not lived long enough to fill.

        Without this a 3-month-old cohort shows 0% at month 12 and drags every
        average down — the classic cohort-triangle error.
        """
        out = frame.copy()
        for cohort in out.index:
            limit = int(mature_map.get(cohort, 0))
            for mi in out.columns:
                if mi > limit:
                    out.loc[cohort, mi] = pd.NA
        return out

    counts = (active.pivot(index="COHORT", columns="MI", values="ACTIVE_CUSTOMERS")
                    .reindex(index=sizes["COHORT"], columns=range(MAX_MONTH_INDEX + 1))
                    .fillna(0))
    retention = mask_immature(counts).div(size_map, axis=0)

    ltv_tri = (ltv.pivot(index="COHORT", columns="MI", values="CUM_SALES")
                  .reindex(index=sizes["COHORT"], columns=range(MAX_MONTH_INDEX + 1))
                  .ffill(axis=1))  # cumulative: a quiet month holds the prior total
    ltv_per_customer = mask_immature(ltv_tri).div(size_map, axis=0)

    def decorate(frame):
        out = frame.copy()
        out.columns = [f"M{c}" for c in out.columns]
        out.insert(0, "COHORT_SIZE", size_map.reindex(out.index).values)
        return out.reset_index()

    summary = sizes.copy()
    for m in MILESTONES:
        summary[f"RETAINED_M{m}"] = summary["COHORT"].map(
            lambda c, m=m: retention.loc[c, m] if m in retention.columns else pd.NA)
        summary[f"NET_SALES_M{m}"] = summary["COHORT"].map(
            lambda c, m=m: ltv_per_customer.loc[c, m] if m in ltv_per_customer.columns else pd.NA)

    return {
        "retention": decorate(retention),
        "ltv": decorate(ltv_per_customer),
        "summary": summary,
        "sizes": sizes,
    }


def _lifetime(conn) -> dict:
    customer = execute_query_df(conn, """
        WITH span AS (
            SELECT k.GCK,
                   DATEDIFF(MONTH, k.COHORT_MONTH, a.LAST_ACTIVE) + 1 AS LIFETIME_MONTHS,
                   CASE WHEN m.GCK IS NOT NULL THEN 'Member (ever)'
                        ELSE 'Non-member (package only)' END          AS SEGMENT
            FROM COH_COHORT k
            JOIN (SELECT GCK, MAX(VISIT_MONTH) AS LAST_ACTIVE FROM COH_VISITS GROUP BY 1) a
              ON a.GCK = k.GCK
            LEFT JOIN COH_MEMBERS m ON m.GCK = k.GCK
            -- Only customers with 24+ months of possible history, so the answer
            -- is not dominated by people who simply have not had time to churn.
            WHERE DATEDIFF(MONTH, k.COHORT_MONTH, CURRENT_DATE()) >= 24
        )
        SELECT SEGMENT,
               COUNT(*)                            AS CUSTOMERS,
               ROUND(AVG(LIFETIME_MONTHS), 1)      AS AVG_LIFETIME_MONTHS,
               ROUND(MEDIAN(LIFETIME_MONTHS), 1)   AS MEDIAN_LIFETIME_MONTHS
        FROM span GROUP BY 1
        UNION ALL
        SELECT 'All customers', COUNT(*), ROUND(AVG(LIFETIME_MONTHS), 1),
               ROUND(MEDIAN(LIFETIME_MONTHS), 1)
        FROM span
    """)

    member = execute_query_df(conn, f"""
        WITH member_span AS (
            SELECT x.GLOBAL_CLIENT_KEY AS GCK,
                   MIN(m.FIRST_MEMBERSHIP_ACTIVATION_DATE)                   AS ACTIVATION,
                   MAX(CASE WHEN m.IS_ACTIVE_MEMBERSHIP = 1 THEN m.DATE END) AS LAST_ACTIVE_DAY
            FROM {DATAMART}.MART_MEMBERSHIP_DAILY_DETAILS m
            JOIN {XWALK} x ON x.STUDIO_ID = m.STUDIO_ID AND x.CLIENT_ID = m.CLIENT_ID
            WHERE m.FIRST_MEMBERSHIP_ACTIVATION_DATE IS NOT NULL
            GROUP BY 1
            HAVING MIN(m.FIRST_MEMBERSHIP_ACTIVATION_DATE) >= '{DATA_START}'
        )
        SELECT TO_VARCHAR(DATE_TRUNC('MONTH', ACTIVATION), 'YYYY-MM')            AS JOIN_MONTH,
               COUNT(*)                                                          AS MEMBERS,
               SUM(CASE WHEN LAST_ACTIVE_DAY >= DATEADD(DAY, -7, CURRENT_DATE())
                        THEN 1 ELSE 0 END)                                       AS STILL_ACTIVE,
               ROUND(AVG(DATEDIFF(MONTH, ACTIVATION, LAST_ACTIVE_DAY)) + 1, 1)   AS AVG_TENURE_MONTHS,
               ROUND(MEDIAN(DATEDIFF(MONTH, ACTIVATION, LAST_ACTIVE_DAY)) + 1, 1) AS MEDIAN_TENURE_MONTHS
        FROM member_span GROUP BY 1 ORDER BY 1
    """)
    if not member.empty:
        for c in ("MEMBERS", "STILL_ACTIVE"):
            member[c] = pd.to_numeric(member[c])
        member["PCT_STILL_ACTIVE"] = member["STILL_ACTIVE"] / member["MEMBERS"]

    return {"customer": customer, "member": member}


def _churn(conn) -> dict:
    # Two traps here, both easy to get wrong:
    #
    # 1. IS_NEW/IS_CHURN/IS_REACTIVATED are daily EVENT flags and must be summed
    #    across every day of the month. IS_ACTIVE is a point-in-time STATE flag,
    #    read at month-end. Filtering the whole query to LAST_DAY(DATE) counts
    #    only churn landing on the final day and understates it roughly 2x —
    #    reports/membership_churn.py had exactly that bug (fixed in 9e60ce1).
    #
    # 2. IS_CHURN_MEMBERSHIP counts CONTRACTS; a person holding two memberships
    #    churns twice. IS_UNIQUE_CHURN_MEMBER counts PEOPLE, which is what a
    #    lender is underwriting.
    monthly = execute_query_df(conn, f"""
        SELECT TO_VARCHAR(DATE, 'YYYY-MM')                                        AS MONTH,
               SUM(IS_UNIQUE_NEW_MEMBER)                                          AS NEW_MEMBERS,
               SUM(IS_UNIQUE_REACTIVATED_MEMBER)                                  AS REACTIVATED,
               SUM(IS_UNIQUE_CHURN_MEMBER)                                        AS CHURNED,
               SUM(CASE WHEN DATE = LAST_DAY(DATE) THEN IS_UNIQUE_ACTIVE_MEMBER END) AS ACTIVE_EOM
        FROM {DATAMART}.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE >= '{DATA_START}' AND DATE <= CURRENT_DATE()
        GROUP BY 1 ORDER BY 1
    """)
    for c in monthly.columns:
        if c != "MONTH":
            monthly[c] = pd.to_numeric(monthly[c])

    monthly["ACTIVE_BOM"] = monthly["ACTIVE_EOM"].shift(1)
    monthly["NET_CHANGE"] = monthly["NEW_MEMBERS"] + monthly["REACTIVATED"] - monthly["CHURNED"]
    # Roughly a third of churned members reactivate within 45 days, so gross
    # churn overstates true attrition. Show both; net is what moves the base.
    monthly["GROSS_CHURN_RATE"] = monthly["CHURNED"] / monthly["ACTIVE_BOM"]
    monthly["NET_CHURN_RATE"] = ((monthly["CHURNED"] - monthly["REACTIVATED"])
                                 / monthly["ACTIVE_BOM"])
    monthly["NET_RETENTION_RATE"] = 1 - monthly["NET_CHURN_RATE"]
    monthly["ANNUAL_RETENTION"] = monthly["NET_RETENTION_RATE"] ** 12

    current_month = datetime.now().strftime("%Y-%m")
    monthly = monthly[monthly["MONTH"] < current_month].reset_index(drop=True)
    monthly = monthly[["MONTH", "ACTIVE_BOM", "NEW_MEMBERS", "REACTIVATED", "CHURNED",
                       "NET_CHANGE", "ACTIVE_EOM", "GROSS_CHURN_RATE", "NET_CHURN_RATE",
                       "NET_RETENTION_RATE", "ANNUAL_RETENTION"]]

    annual = monthly.copy()
    annual["YEAR"] = annual["MONTH"].str[:4]
    yearly = annual.groupby("YEAR", as_index=False).agg(
        NEW_MEMBERS=("NEW_MEMBERS", "sum"),
        CHURNED=("CHURNED", "sum"),
        REACTIVATED=("REACTIVATED", "sum"),
        AVG_GROSS_CHURN_RATE=("GROSS_CHURN_RATE", "mean"),
        AVG_NET_CHURN_RATE=("NET_CHURN_RATE", "mean"),
        ACTIVE_AT_YEAR_END=("ACTIVE_EOM", "last"))
    yearly["IMPLIED_ANNUAL_RETENTION"] = (1 - yearly["AVG_NET_CHURN_RATE"]) ** 12

    return {"monthly": monthly, "yearly": yearly}


def _ltv(conn) -> dict:
    # Mature cohorts only — a cohort four months old has not had time to earn a
    # 12-month LTV, and including it would drag the average down.
    by_segment = execute_query_df(conn, """
        WITH mature AS (
            SELECT k.GCK, k.COHORT_MONTH FROM COH_COHORT k
            WHERE DATEDIFF(MONTH, k.COHORT_MONTH, CURRENT_DATE()) >= 12
        ),
        rev AS (
            SELECT k.GCK,
                   SUM(CASE WHEN DATEDIFF(MONTH, k.COHORT_MONTH, s.SALE_MONTH) < 12
                            THEN s.NET_SALES ELSE 0 END) AS SALES_12M,
                   SUM(s.NET_SALES)                      AS SALES_ALL
            FROM COH_COHORT k JOIN COH_SALES s ON s.GCK = k.GCK GROUP BY 1
        )
        SELECT CASE WHEN mem.GCK IS NOT NULL THEN 'Member (ever)'
                    ELSE 'Non-member (package only)' END  AS SEGMENT,
               COUNT(*)                                   AS CUSTOMERS,
               ROUND(AVG(r.SALES_12M), 2)                 AS AVG_NET_SALES_12M,
               ROUND(MEDIAN(r.SALES_12M), 2)              AS MEDIAN_NET_SALES_12M,
               ROUND(AVG(r.SALES_ALL), 2)                 AS AVG_LIFETIME_NET_SALES,
               ROUND(MEDIAN(r.SALES_ALL), 2)              AS MEDIAN_LIFETIME_NET_SALES
        FROM mature m JOIN rev r ON r.GCK = m.GCK
        LEFT JOIN COH_MEMBERS mem ON mem.GCK = m.GCK
        GROUP BY 1
        UNION ALL
        SELECT 'All customers', COUNT(*), ROUND(AVG(r.SALES_12M), 2),
               ROUND(MEDIAN(r.SALES_12M), 2), ROUND(AVG(r.SALES_ALL), 2),
               ROUND(MEDIAN(r.SALES_ALL), 2)
        FROM mature m JOIN rev r ON r.GCK = m.GCK
    """)

    # Averages hide a very skewed distribution — show the shape too.
    distribution = execute_query_df(conn, """
        SELECT CASE
                 WHEN LIFETIME_NET_SALES <  100 THEN 'a. Under $100'
                 WHEN LIFETIME_NET_SALES <  250 THEN 'b. $100 - $250'
                 WHEN LIFETIME_NET_SALES <  500 THEN 'c. $250 - $500'
                 WHEN LIFETIME_NET_SALES < 1000 THEN 'd. $500 - $1,000'
                 WHEN LIFETIME_NET_SALES < 2500 THEN 'e. $1,000 - $2,500'
                 WHEN LIFETIME_NET_SALES < 5000 THEN 'f. $2,500 - $5,000'
                 ELSE 'g. $5,000+' END                   AS LIFETIME_NET_SALES_BAND,
               COUNT(*)                                  AS CUSTOMERS,
               ROUND(SUM(LIFETIME_NET_SALES), 2)         AS TOTAL_NET_SALES
        FROM COH_LTV t JOIN COH_COHORT k ON k.GCK = t.GCK
        GROUP BY 1 ORDER BY 1
    """)
    for c in ("CUSTOMERS", "TOTAL_NET_SALES"):
        distribution[c] = pd.to_numeric(distribution[c])
    distribution["PCT_OF_CUSTOMERS"] = distribution["CUSTOMERS"] / distribution["CUSTOMERS"].sum()
    distribution["PCT_OF_NET_SALES"] = (distribution["TOTAL_NET_SALES"]
                                        / distribution["TOTAL_NET_SALES"].sum())

    return {"by_segment": by_segment, "distribution": distribution}


def _acquisition(conn) -> dict:
    raw = execute_query_df(conn, """
        SELECT k.REFERRED_BY,
               TO_VARCHAR(k.COHORT_MONTH, 'YYYY')     AS COHORT_YEAR,
               COUNT(*)                               AS CUSTOMERS,
               ROUND(SUM(COALESCE(t.LIFETIME_NET_SALES, 0)), 2) AS TOTAL_NET_SALES
        FROM COH_COHORT k LEFT JOIN COH_LTV t ON t.GCK = k.GCK
        GROUP BY 1, 2
    """)
    raw["CHANNEL"] = raw["REFERRED_BY"].map(_normalize_channel)
    for c in ("CUSTOMERS", "TOTAL_NET_SALES"):
        raw[c] = pd.to_numeric(raw[c])

    summary = (raw.groupby("CHANNEL", as_index=False)
                  .agg(CUSTOMERS=("CUSTOMERS", "sum"),
                       TOTAL_NET_SALES=("TOTAL_NET_SALES", "sum")))
    # Two-thirds never answered the signup question and they hold most of the
    # sales, so share-of-everyone makes every channel look tiny. Give the share
    # of those who did answer, with the caveat that they are not a random sample.
    captured = summary.loc[summary["CHANNEL"] != NOT_CAPTURED, "CUSTOMERS"].sum()
    summary["PCT_OF_RESPONDENTS"] = summary.apply(
        lambda r: pd.NA if r["CHANNEL"] == NOT_CAPTURED else r["CUSTOMERS"] / captured, axis=1)
    summary["AVG_LIFETIME_NET_SALES"] = (
        summary["TOTAL_NET_SALES"] / summary["CUSTOMERS"]).round(2)
    summary = summary.sort_values("CUSTOMERS", ascending=False).reset_index(drop=True)

    by_year = raw.pivot_table(index="CHANNEL", columns="COHORT_YEAR",
                              values="CUSTOMERS", aggfunc="sum", fill_value=0)
    by_year["TOTAL"] = by_year.sum(axis=1)
    by_year = by_year.sort_values("TOTAL", ascending=False).reset_index()

    return {"summary": summary, "by_year": by_year}


def _classpass(conn) -> dict:
    status = execute_query_df(conn, f"""
        SELECT COALESCE(c.CLASSPASS_STATUS, 'Unknown')                   AS CLASSPASS_STATUS,
               COUNT(DISTINCT c.GCK)                                     AS CUSTOMERS,
               COUNT(DISTINCT CASE WHEN t.LIFETIME_NET_SALES > 0
                                   THEN c.GCK END)                       AS EVER_BOUGHT_DIRECT,
               ROUND(AVG(CASE WHEN t.LIFETIME_NET_SALES > 0
                              THEN t.LIFETIME_NET_SALES END), 2)         AS AVG_NET_SALES_OF_BUYERS,
               ROUND(AVG(CASE WHEN t.LIFETIME_NET_SALES > 0
                              THEN t.PURCHASE_OCCASIONS END), 1)         AS AVG_PURCHASES_OF_BUYERS
        FROM COH_CLIENTS c LEFT JOIN COH_LTV t ON t.GCK = c.GCK
        GROUP BY 1 ORDER BY 2 DESC
    """)
    for c in ("CUSTOMERS", "EVER_BOUGHT_DIRECT"):
        status[c] = pd.to_numeric(status[c])
    status["CONVERSION_RATE"] = status["EVER_BOUGHT_DIRECT"] / status["CUSTOMERS"]

    persistence = execute_query_df(conn, """
        WITH cp AS (SELECT DISTINCT GCK FROM COH_VISITS WHERE CLASSPASS_SOURCE = 1),
        buyers AS (
            SELECT t.GCK, t.PURCHASE_OCCASIONS, t.LIFETIME_NET_SALES,
                   DATEDIFF(MONTH, t.FIRST_SALE, t.LAST_SALE) + 1 AS SPAN_MONTHS
            FROM COH_LTV t WHERE t.LIFETIME_NET_SALES > 0
        )
        SELECT CASE WHEN cp.GCK IS NOT NULL THEN 'Came via ClassPass'
                    ELSE 'Direct (never ClassPass)' END       AS SEGMENT,
               COUNT(*)                                       AS PAYING_CUSTOMERS,
               SUM(CASE WHEN b.PURCHASE_OCCASIONS = 1 THEN 1 ELSE 0 END)  AS BOUGHT_ONCE_ONLY,
               SUM(CASE WHEN b.PURCHASE_OCCASIONS >= 3 THEN 1 ELSE 0 END) AS BOUGHT_3_PLUS,
               ROUND(AVG(b.PURCHASE_OCCASIONS), 1)            AS AVG_PURCHASES,
               ROUND(AVG(b.LIFETIME_NET_SALES), 2)            AS AVG_LIFETIME_NET_SALES,
               ROUND(AVG(b.SPAN_MONTHS), 1)                   AS AVG_PURCHASING_SPAN_MONTHS
        FROM buyers b LEFT JOIN cp ON cp.GCK = b.GCK
        GROUP BY 1 ORDER BY 2 DESC
    """)
    for c in ("PAYING_CUSTOMERS", "BOUGHT_ONCE_ONLY", "BOUGHT_3_PLUS"):
        persistence[c] = pd.to_numeric(persistence[c])
    persistence["PCT_BOUGHT_ONCE_ONLY"] = (persistence["BOUGHT_ONCE_ONLY"]
                                           / persistence["PAYING_CUSTOMERS"])
    persistence["PCT_BOUGHT_3_PLUS"] = (persistence["BOUGHT_3_PLUS"]
                                        / persistence["PAYING_CUSTOMERS"])

    timing = execute_query_df(conn, """
        WITH cp_first AS (
            SELECT GCK, MIN(CLASS_DATE) AS FIRST_CP_VISIT
            FROM COH_VISITS WHERE CLASSPASS_SOURCE = 1 GROUP BY 1
        ),
        direct_first AS (
            SELECT GCK, MIN(SALE_DATE) AS FIRST_DIRECT_SALE
            FROM COH_SALES WHERE NET_SALES > 0 GROUP BY 1
        ),
        j AS (
            SELECT f.GCK, f.FIRST_CP_VISIT, d.FIRST_DIRECT_SALE,
                   DATEDIFF(DAY, f.FIRST_CP_VISIT, d.FIRST_DIRECT_SALE) AS DAYS
            FROM cp_first f LEFT JOIN direct_first d ON d.GCK = f.GCK
        )
        SELECT COUNT(*)                                                     AS CLASSPASS_CUSTOMERS,
               SUM(CASE WHEN DAYS >= 0 THEN 1 ELSE 0 END)                   AS EVER_BOUGHT_DIRECT,
               SUM(CASE WHEN DAYS BETWEEN 0 AND 90 THEN 1 ELSE 0 END)       AS BOUGHT_WITHIN_90D,
               SUM(CASE WHEN DAYS BETWEEN 0 AND 365 THEN 1 ELSE 0 END)      AS BOUGHT_WITHIN_1YR,
               ROUND(MEDIAN(CASE WHEN DAYS >= 0 THEN DAYS END), 0)          AS MEDIAN_DAYS_TO_FIRST_PURCHASE
        FROM j
    """)
    if not timing.empty:
        for c in ("CLASSPASS_CUSTOMERS", "EVER_BOUGHT_DIRECT",
                  "BOUGHT_WITHIN_90D", "BOUGHT_WITHIN_1YR"):
            timing[c] = pd.to_numeric(timing[c])
        n = timing.loc[0, "CLASSPASS_CUSTOMERS"]
        timing["PCT_EVER_BOUGHT"] = timing["EVER_BOUGHT_DIRECT"] / n
        timing["PCT_WITHIN_90D"] = timing["BOUGHT_WITHIN_90D"] / n
        timing["PCT_WITHIN_1YR"] = timing["BOUGHT_WITHIN_1YR"] / n

    return {"status": status, "persistence": persistence, "timing": timing}


def _membership_vs_package(conn) -> dict:
    ttm = execute_query_df(conn, """
        WITH recent AS (
            SELECT s.GCK,
                   MAX(CASE WHEN s.IS_AUTOPAY = 1 THEN 1 ELSE 0 END) AS HAS_RECURRING,
                   SUM(s.NET_SALES)                                  AS NET_SALES,
                   COUNT(DISTINCT CASE WHEN s.NET_SALES > 0 THEN s.SALE_DATE END) AS OCCASIONS
            FROM COH_SALES s
            WHERE s.SALE_DATE >= DATEADD(MONTH, -12, CURRENT_DATE())
            GROUP BY 1
        )
        SELECT CASE WHEN HAS_RECURRING = 1 THEN 'Recurring membership'
                    ELSE 'Package / pass / one-time' END AS SEGMENT,
               COUNT(*)                       AS CUSTOMERS,
               ROUND(SUM(NET_SALES), 2)       AS NET_SALES,
               ROUND(AVG(NET_SALES), 2)       AS AVG_NET_SALES_PER_CUSTOMER,
               ROUND(MEDIAN(NET_SALES), 2)    AS MEDIAN_NET_SALES_PER_CUSTOMER,
               ROUND(AVG(OCCASIONS), 1)       AS AVG_PURCHASE_OCCASIONS
        FROM recent GROUP BY 1 ORDER BY 3 DESC
    """)
    for c in ("CUSTOMERS", "NET_SALES"):
        ttm[c] = pd.to_numeric(ttm[c])
    ttm["PCT_OF_CUSTOMERS"] = ttm["CUSTOMERS"] / ttm["CUSTOMERS"].sum()
    ttm["PCT_OF_NET_SALES"] = ttm["NET_SALES"] / ttm["NET_SALES"].sum()

    monthly = execute_query_df(conn, """
        SELECT TO_VARCHAR(SALE_MONTH, 'YYYY-MM') AS MONTH,
               COUNT(DISTINCT CASE WHEN IS_AUTOPAY = 1 THEN GCK END)  AS MEMBERSHIP_CUSTOMERS,
               COUNT(DISTINCT CASE WHEN IS_AUTOPAY = 0 THEN GCK END)  AS PACKAGE_CUSTOMERS,
               ROUND(SUM(CASE WHEN IS_AUTOPAY = 1 THEN NET_SALES ELSE 0 END), 2) AS MEMBERSHIP_NET_SALES,
               ROUND(SUM(CASE WHEN IS_AUTOPAY = 0 THEN NET_SALES ELSE 0 END), 2) AS PACKAGE_NET_SALES
        FROM COH_SALES GROUP BY 1 ORDER BY 1
    """)
    for c in monthly.columns:
        if c != "MONTH":
            monthly[c] = pd.to_numeric(monthly[c])
    monthly["PCT_NET_SALES_FROM_MEMBERSHIP"] = (
        monthly["MEMBERSHIP_NET_SALES"]
        / (monthly["MEMBERSHIP_NET_SALES"] + monthly["PACKAGE_NET_SALES"]))

    mix = execute_query_df(conn, f"""
        SELECT MEMBERSHIP_NAME, COUNT(DISTINCT CLIENT_ID) AS ACTIVE_MEMBERS
        FROM {DATAMART}.MART_MEMBERSHIP_DAILY_DETAILS
        WHERE DATE = (SELECT MAX(DATE) FROM {DATAMART}.MART_MEMBERSHIP_DAILY_DETAILS
                      WHERE DATE <= CURRENT_DATE())
          AND IS_ACTIVE_MEMBERSHIP = 1
        GROUP BY 1 ORDER BY 2 DESC
    """)
    mix["ACTIVE_MEMBERS"] = pd.to_numeric(mix["ACTIVE_MEMBERS"])
    mix["PCT_OF_MEMBERS"] = mix["ACTIVE_MEMBERS"] / mix["ACTIVE_MEMBERS"].sum()

    return {"ttm": ttm, "monthly": monthly, "mix": mix}


def _repurchase(conn) -> dict:
    gaps = execute_query_df(conn, """
        WITH purch AS (
            SELECT s.GCK, s.SALE_DATE,
                   LAG(s.SALE_DATE) OVER (PARTITION BY s.GCK ORDER BY s.SALE_DATE) AS PREV_DATE
            FROM (SELECT DISTINCT GCK, SALE_DATE FROM COH_SALES WHERE NET_SALES > 0) s
        )
        SELECT CASE WHEN m.GCK IS NOT NULL THEN 'Member (ever)'
                    ELSE 'Non-member (package only)' END           AS SEGMENT,
               COUNT(*)                                            AS REPURCHASE_EVENTS,
               ROUND(MEDIAN(DATEDIFF(DAY, p.PREV_DATE, p.SALE_DATE)), 0) AS MEDIAN_DAYS_BETWEEN,
               SUM(CASE WHEN DATEDIFF(DAY, p.PREV_DATE, p.SALE_DATE) <= 30 THEN 1 ELSE 0 END) AS W30,
               SUM(CASE WHEN DATEDIFF(DAY, p.PREV_DATE, p.SALE_DATE) <= 90 THEN 1 ELSE 0 END) AS W90,
               SUM(CASE WHEN DATEDIFF(DAY, p.PREV_DATE, p.SALE_DATE) <= 180 THEN 1 ELSE 0 END) AS W180
        FROM purch p LEFT JOIN COH_MEMBERS m ON m.GCK = p.GCK
        WHERE p.PREV_DATE IS NOT NULL GROUP BY 1 ORDER BY 1
    """)
    for c in ("REPURCHASE_EVENTS", "W30", "W90", "W180"):
        gaps[c] = pd.to_numeric(gaps[c])
    for d in (30, 90, 180):
        gaps[f"PCT_WITHIN_{d}D"] = gaps[f"W{d}"] / gaps["REPURCHASE_EVENTS"]
    gaps = gaps[["SEGMENT", "REPURCHASE_EVENTS", "MEDIAN_DAYS_BETWEEN",
                 "PCT_WITHIN_30D", "PCT_WITHIN_90D", "PCT_WITHIN_180D"]]

    nth = execute_query_df(conn, """
        WITH purch AS (
            SELECT s.GCK, ROW_NUMBER() OVER (PARTITION BY s.GCK ORDER BY s.SALE_DATE) AS N
            FROM (SELECT DISTINCT GCK, SALE_DATE FROM COH_SALES WHERE NET_SALES > 0) s
        )
        SELECT CASE WHEN m.GCK IS NOT NULL THEN 'Member (ever)'
                    ELSE 'Non-member (package only)' END AS SEGMENT,
               p.N AS PURCHASE_NO, COUNT(DISTINCT p.GCK) AS CUSTOMERS
        FROM purch p LEFT JOIN COH_MEMBERS m ON m.GCK = p.GCK
        WHERE p.N <= 8 GROUP BY 1, 2 ORDER BY 1, 2
    """)
    nth["CUSTOMERS"] = pd.to_numeric(nth["CUSTOMERS"])
    counts = nth.pivot(index="SEGMENT", columns="PURCHASE_NO", values="CUSTOMERS").fillna(0)
    rates = counts.div(counts[1], axis=0)
    counts.columns = [f"Reached purchase {c}" for c in counts.columns]
    rates.columns = [f"% reaching purchase {c}" for c in rates.columns]
    nth_out = counts.join(rates).reset_index()

    annual = execute_query_df(conn, """
        WITH nm AS (
            SELECT s.GCK, YEAR(s.SALE_DATE) AS YR
            FROM COH_SALES s LEFT JOIN COH_MEMBERS m ON m.GCK = s.GCK
            WHERE m.GCK IS NULL AND s.NET_SALES > 0
            GROUP BY 1, 2
        )
        SELECT y.YR AS YEAR, COUNT(DISTINCT y.GCK) AS PURCHASING_CUSTOMERS,
               COUNT(DISTINCT n.GCK)               AS BOUGHT_AGAIN_NEXT_YEAR
        FROM nm y LEFT JOIN nm n ON n.GCK = y.GCK AND n.YR = y.YR + 1
        GROUP BY 1 ORDER BY 1
    """)
    if not annual.empty:
        for c in ("PURCHASING_CUSTOMERS", "BOUGHT_AGAIN_NEXT_YEAR"):
            annual[c] = pd.to_numeric(annual[c])
        annual["REPEAT_RATE"] = annual["BOUGHT_AGAIN_NEXT_YEAR"] / annual["PURCHASING_CUSTOMERS"]
        # The current year has no following year, and the year before it is
        # measured against a partial year — flag both so neither reads as decline.
        cy = datetime.now().year
        annual["BASIS"] = annual["YEAR"].map(
            lambda y: "No following year yet" if y >= cy
            else (f"Partial — {cy} still in progress" if y == cy - 1 else "Complete"))
        annual.loc[annual["YEAR"] >= cy, ["BOUGHT_AGAIN_NEXT_YEAR", "REPEAT_RATE"]] = pd.NA

    return {"gaps": gaps, "nth": nth_out, "annual": annual}


# ---------------------------------------------------------------------------
# Summary — the lender's list, answered in their order
# ---------------------------------------------------------------------------

def _summary(conn, b: dict) -> pd.DataFrame:
    rows = []

    def add(num, request, answer, tab):
        rows.append({"#": num, "LENDER REQUEST": request,
                     "WHAT THE DATA SHOWS": answer, "TAB": tab})

    n = execute_query_df(conn, """
        SELECT (SELECT COUNT(*) FROM COH_COHORT) AS CUSTOMERS,
               (SELECT MIN(TO_VARCHAR(COHORT_MONTH, 'YYYY-MM')) FROM COH_COHORT) AS FIRST_COHORT
    """).iloc[0]

    gender = b["demographics"]["gender"]
    female = gender.loc[gender["GENDER"].str.lower() == "female", "PCT_OF_KNOWN"]
    age = b["demographics"]["age"]
    top_age = age.loc[age["AGE_BAND"] != NOT_CAPTURED].nlargest(1, "CUSTOMERS")
    add(1, "Customer / member demographics",
        f"{float(female.iloc[0]):.0%} female among customers who disclosed; largest age band "
        f"{top_age.iloc[0]['AGE_BAND']}. Gender captured for "
        f"{b['demographics']['fill'].iloc[0]['PCT_POPULATED']:.0%} of customers, age for "
        f"{b['demographics']['fill'].iloc[1]['PCT_POPULATED']:.0%} — treat as directional.",
        "2. Demographics")

    ret = b["cohorts"]["summary"]
    seasoned = ret[ret["MONTHS_MATURE"] >= 12]
    add(2, "Historical customer cohort / retention data",
        f"{int(n.CUSTOMERS):,} customers across {len(ret)} monthly cohorts from "
        f"{n.FIRST_COHORT} to date. Typical cohort retains "
        f"{seasoned['RETAINED_M3'].median():.0%} at month 3 and "
        f"{seasoned['RETAINED_M12'].median():.0%} at month 12.",
        "3. Cohort Retention")

    life = b["lifetime"]["customer"].set_index("SEGMENT")
    add(3, "Average customer / membership lifetime",
        f"All customers average {float(life.loc['All customers', 'AVG_LIFETIME_MONTHS']):.1f} "
        f"months (median {float(life.loc['All customers', 'MEDIAN_LIFETIME_MONTHS']):.0f}). "
        f"Members average "
        f"{float(life.loc['Member (ever)', 'AVG_LIFETIME_MONTHS']):.1f} months. "
        "Measured on customers with 24+ months of possible history.",
        "4. Customer Lifetime")

    ch = b["churn"]["monthly"].tail(12)
    add(4, "Customer churn / retention metrics",
        f"Member churn averages {ch['GROSS_CHURN_RATE'].mean():.1%} gross / "
        f"{ch['NET_CHURN_RATE'].mean():.1%} net of reactivations per month over the last 12 "
        f"months, implying {(1 - ch['NET_CHURN_RATE'].mean()) ** 12:.0%} annual retention. "
        f"Monthly detail back to 2021.",
        "5. Churn and Retention")

    ltv = b["ltv"]["by_segment"].set_index("SEGMENT")
    add(5, "Customer LTV",
        f"Lifetime net sales average "
        f"${float(ltv.loc['All customers', 'AVG_LIFETIME_NET_SALES']):,.0f} across all "
        f"customers but ${float(ltv.loc['Member (ever)', 'AVG_LIFETIME_NET_SALES']):,.0f} for "
        f"those who became members. Distribution is heavily skewed — see the tab.",
        "6. Customer LTV")

    add(6, "Customer acquisition cost (CAC) and LTV / CAC",
        "Not in this workbook. Marketing spend sits in the P&L, not the warehouse, and only a "
        "blended figure is derivable. Cat Martin is producing CAC separately.",
        "— (with Cat)")

    ac = b["acquisition"]["summary"]
    responded = ac[ac["CHANNEL"] != NOT_CAPTURED]
    top = responded.nlargest(2, "CUSTOMERS")
    not_cap = ac.loc[ac["CHANNEL"] == NOT_CAPTURED, "CUSTOMERS"].sum()
    add(7, "Customer acquisition channel breakdown",
        f"Among the {1 - not_cap / ac['CUSTOMERS'].sum():.0%} of customers who answered at "
        f"signup, {top.iloc[0]['PCT_OF_RESPONDENTS']:.0%} say {top.iloc[0]['CHANNEL']} and "
        f"{top.iloc[1]['PCT_OF_RESPONDENTS']:.0%} say {top.iloc[1]['CHANNEL']}. Self-reported, "
        "not tracked attribution — no paid-vs-organic split exists.",
        "7. Acquisition Channel")

    cp = b["classpass"]["persistence"].set_index("SEGMENT")
    t = b["classpass"]["timing"].iloc[0]
    add(8, "ClassPass customer retention / repeat purchase",
        f"{float(t['PCT_EVER_BOUGHT']):.0%} of ClassPass customers ever buy from Mighty "
        f"directly. Those who do average "
        f"${float(cp.loc['Came via ClassPass', 'AVG_LIFETIME_NET_SALES']):,.0f} lifetime vs "
        f"${float(cp.loc['Direct (never ClassPass)', 'AVG_LIFETIME_NET_SALES']):,.0f} for "
        f"direct customers, and "
        f"{float(cp.loc['Came via ClassPass', 'PCT_BOUGHT_ONCE_ONLY']):.0%} buy only once.",
        "8. ClassPass Behavior")

    mp = b["membership"]["ttm"].set_index("SEGMENT")
    add(9, "Membership vs package / pass customer breakdown",
        f"Recurring members are "
        f"{float(mp.loc['Recurring membership', 'PCT_OF_CUSTOMERS']):.0%} of purchasing "
        f"customers but "
        f"{float(mp.loc['Recurring membership', 'PCT_OF_NET_SALES']):.0%} of net sales over the "
        f"last 12 months. Package buyers are the volume; members are the value.",
        "9. Membership vs Package")

    g = b["repurchase"]["gaps"].set_index("SEGMENT")
    ann = b["repurchase"]["annual"]
    complete = ann[ann["BASIS"] == "Complete"]
    add(10, "Recurring purchase behavior for non-members",
        f"Non-members who repurchase do so a median "
        f"{float(g.loc['Non-member (package only)', 'MEDIAN_DAYS_BETWEEN']):.0f} days apart, "
        f"{float(g.loc['Non-member (package only)', 'PCT_WITHIN_90D']):.0%} within 90 days. "
        f"Year over year, {complete['REPEAT_RATE'].mean():.0%} of non-member customers buy "
        f"again the following year.",
        "10. Non-Member Repurchase")

    return pd.DataFrame(rows)


METHODOLOGY = [
    ("Period covered",
     "All available history. Mart transaction detail begins 2021-01-01, so cohorts start there. "
     "Customers whose first purchase predates that are excluded from cohort analysis entirely, "
     "because their early history is not in the warehouse and they would otherwise look like "
     "new customers in January 2021."),
    ("Source system",
     "MindBody (via the Playlist data mart), plus ClassPass reservation data. MindBody is an "
     "operational booking system, not an accounting system: most descriptive fields are entered "
     "by studio staff or self-reported by customers at signup, and records can be edited or "
     "back-dated after the fact. Transactional facts (what was sold, when, for how much; who "
     "attended which class) are reliable. Descriptive attributes (demographics, referral source) "
     "are only as good as what was typed in, and their coverage is stated wherever they appear."),
    ("Customer identity — method",
     "MindBody issues a CLIENT_ID per studio, so one person who visits three locations exists as "
     "three records. Identity is resolved via "
     "EARNED_REVENUE_ANALYTICS.CLIENT_XWALK.GLOBAL_CLIENT_KEY, which matches on email, then on "
     "name, then falls back to a studio-scoped key. Using raw CLIENT_ID would overstate distinct "
     "customers by roughly 16%. Of about 91,000 resolved identities, roughly 84% map to a single "
     "source record and 99.9% resolve by email rather than by name."),
    ("Customer identity — known limits",
     "The match is a heuristic and fails in two directions. A person who used different email "
     "addresses at different studios stays split, which overstates the customer count and "
     "understates their individual lifetime value. A household or couple sharing one email "
     "merges into a single customer, which does the reverse. Only 28 identities map to seven or "
     "more source records, so the aggregate effect is small, but no per-customer figure should be "
     "treated as exact at the individual level."),
    ("Non-customer identities removed",
     "Front-desk staff create placeholder profiles for walk-ins and comps ('walk-in', 'reserve', "
     "'online guest', 'free bird'), and each studio has its own login on the "
     "@mightypilates.com domain. Left in, these behave as single customers with hundreds of "
     "purchases and distort every per-customer metric. All such identities are excluded, along "
     "with any name-only identity reused across three or more studios — no email at three "
     "separate locations indicates a placeholder rather than a person. Roughly $99k of sales "
     "across about 24 identities is removed on this basis."),
    ("Duplicate sales records",
     "When Marin split off from Presidio Heights, sales before 2025-04-24 were written under both "
     "studios — 1,272 rows and about $282k of double-counted sales. These are excluded here, "
     "matching the treatment in the revenue recognition model that produces the GL. No other "
     "systematic duplication was found: every sales line carries a unique identifier, though a "
     "single transaction spans multiple lines, so 'purchase occasions' are counted as distinct "
     "purchase DATES. Two separate purchases on the same day count once."),
    ("Studio expansion affects cohort comparability",
     "Mighty Pilates grew from 2 studios to 12 during the period covered, with ten locations "
     "opening between 2022 and 2025. Depending on the year, 19-34% of a cohort made their first "
     "purchase at a studio less than twelve months old. New studios acquire heavily through intro "
     "offers and aggregators, so later cohorts are structurally weighted toward first-time "
     "trial customers. Part of the apparent decline in retention across cohorts is this change in "
     "business mix rather than a deterioration in how any one studio retains. Splitting cohorts "
     "by studio vintage would separate the two effects; that is not in this workbook."),
    ("'LTV' means net SALES, not revenue",
     "Every LTV and sales figure here is cash collected from the customer — "
     "MART_SALES_DETAILS.NET_PAYMENTAMT_LOCAL, net of refunds and discounts. It is NOT "
     "recognized revenue and will not tie to the P&L or the GL, which are deferral-based. "
     "Revenue totals are deliberately excluded from this workbook for that reason; use the "
     "financial statements for anything revenue-related."),
    ("Sales exclusions",
     "Same exclusions as the GL model: ClassPass passthrough lines, unpaid pricing options "
     "(comps), and internal category IDs -6/-64/-73. Zero-value rows are dropped as well — "
     "ClassPass and Gympass pricing options post at $0 because the aggregator pays Mighty "
     "outside this table, and counting them would turn every aggregator visitor into a "
     "'paying customer' and roughly double the package segment."),
    ("Cohort assignment",
     "A customer belongs to the calendar month of their first paid purchase."),
    ("Activity and retention",
     "A customer is 'active' in a month if they attended at least one visit that month "
     "(cancelled and missed visits excluded). Visits are a better signal than purchases because "
     "a package bought once is consumed over several months."),
    ("Cohort maturity",
     "Cells beyond a cohort's actual age are blank, not zero. A cohort three months old has no "
     "month-12 value, and filling it with zero would understate every average. For the same "
     "reason the most recent cohorts always look highly retained — compare like-aged cohorts "
     "only, and read seasoned cohorts for steady-state rates."),
    ("Membership churn",
     "IS_NEW / IS_CHURN / IS_REACTIVATED are daily EVENT flags, summed across every day of the "
     "month. IS_ACTIVE is a point-in-time STATE flag, read at month-end. Headline figures count "
     "PEOPLE (the IS_UNIQUE_*_MEMBER flags). Mighty's internal membership report counts "
     "CONTRACTS, which runs 8-26% higher month to month (median about 15%) because one person "
     "can hold two memberships. Both are correct on their own basis; if the two are ever shown "
     "side by side, say which basis each uses."),
    ("Gross vs net churn",
     "Roughly a third of churned members are active again within 45 days, so gross churn "
     "overstates true attrition. Both are shown: gross counts every exit, net subtracts "
     "reactivations and is what actually moves the member base. Denominator is the active count "
     "at the START of the month. Annual retention is (1 - net monthly churn) ^ 12, a survival "
     "calculation, not 12x the monthly rate."),
    ("Demographics",
     "Fill rates are stated on the tab and are thin. Two source quirks are corrected here: "
     "MindBody stores an unset gender as the literal string 'None' rather than NULL, which "
     "makes a naive count overstate coverage by ~26 points; and AGE_BUCKET = 'Other' means no "
     "birthdate on file, not an age band. City is normalized for case and spacing because it is "
     "hand-typed at signup. Percentages are of customers WITH the field populated, and those "
     "customers are not a random sample — treat the profile as directional."),
    ("Acquisition channel",
     "Self-reported at signup and captured for about a third of customers, so the mix is shown "
     "as a share of respondents. Respondents are not a random sample and non-respondents hold "
     "most of the sales. This is stated preference, not tracked attribution: there is no "
     "paid-vs-organic split and no ad-platform data in the warehouse. Raw values are normalized "
     "by pattern match (CHANNEL_RULES in reports/cohort_analysis.py) because the same channel "
     "appears under several spellings."),
    ("ClassPass",
     "ClassPass visits are identified by MART_VISITS.CLASSPASS_SOURCE = 1. ClassPass pays "
     "Mighty outside client-level sales, so 'bought directly' and the LTV figures measure only "
     "what the customer spent with Mighty itself — which is the question being asked."),
    ("Not included",
     "CAC and LTV/CAC (Cat is producing these; marketing spend is not in the warehouse and only "
     "a blended figure is derivable). Revenue totals (they do not tie to the P&L). "
     "Channel-level CAC is not derivable from any current data source."),
]


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

def _fmt_key(col: str) -> str:
    """Pick a number format from the column name.

    Checked in order — 'PCT_OF_NET_SALES' must resolve to percent, not money.
    """
    c = str(col).upper()
    if c.startswith("%") or any(k in c for k in ("PCT", "RATE", "RETAINED",
                                                 "RETENTION", "CONVERSION", "POPULATED")):
        return "pct"
    if any(k in c for k in ("SALES", "LTV", "REVENUE", "SPEND", "AMOUNT", "PRICE")):
        return "money"
    if any(k in c for k in ("MONTHS", "DAYS", "OCCASIONS", "AVG_PURCHASES")):
        return "num1"
    if any(k in c for k in ("CUSTOMER", "MEMBER", "CLIENT", "COUNT", "SIZE", "VISIT",
                            "CHURN", "PURCHASE", "EVENT", "REACHED", "W30", "W90")):
        return "int"
    return "num1"


def _write_workbook(blocks: dict, summary: pd.DataFrame, output_dir: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    filepath = output_dir / f"Mighty_Pilates_Cohort_Retention_Packet_{stamp}.xlsx"

    with pd.ExcelWriter(filepath, engine="xlsxwriter") as writer:
        wb = writer.book
        F = {
            "header": wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white",
                                     "border": 1, "text_wrap": True, "valign": "top"}),
            "title": wb.add_format({"bold": True, "font_size": 15}),
            "sub": wb.add_format({"italic": True, "font_color": "#595959", "text_wrap": True,
                                  "valign": "top"}),
            "note": wb.add_format({"italic": True, "font_color": "#7F7F7F", "text_wrap": True,
                                   "valign": "top"}),
            "blocktitle": wb.add_format({"bold": True, "font_size": 11,
                                         "font_color": "#1F3864"}),
            "pct": wb.add_format({"num_format": "0.0%"}),
            "money": wb.add_format({"num_format": "$#,##0"}),
            "int": wb.add_format({"num_format": "#,##0"}),
            "num1": wb.add_format({"num_format": "#,##0.0"}),
            "text": wb.add_format({"text_wrap": True, "valign": "top"}),
        }

        def sheet(name, widths, title=None, subtitle=None):
            ws = wb.add_worksheet(name)
            writer.sheets[name] = ws
            for i, w in enumerate(widths):
                ws.set_column(i, i, w)
            row = 0
            if title:
                ws.write(row, 0, title, F["title"]); row += 1
            if subtitle:
                ws.write(row, 0, subtitle, F["sub"]); row += 1
            return ws, row + (1 if title or subtitle else 0)

        def block(ws, df, row, label=None, note=None, col_formats=None):
            """Write a table with an explicit format on every cell.

            Per-cell rather than per-column: set_column formats get clobbered
            when two blocks share a sheet, which left percentages rendering as
            currency. col_formats overrides the name heuristic per column — the
            cohort triangles need it, since 'M0'..'M36' carry no clue whether
            they hold a percentage or a dollar amount.
            """
            if df is None or df.empty:
                return row
            overrides = col_formats or {}
            if label:
                ws.write(row, 0, label, F["blocktitle"]); row += 1
            for i, col in enumerate(df.columns):
                ws.write(row, i, str(col), F["header"])
            row += 1
            for _, r in df.iterrows():
                for i, col in enumerate(df.columns):
                    v = r[col]
                    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
                        ws.write_blank(row, i, None)
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        key = overrides.get(col) or _fmt_key(col)
                        ws.write_number(row, i, float(v), F[key])
                    else:
                        ws.write(row, i, str(v), F["text"] if len(str(v)) > 40 else None)
                row += 1
            if note:
                row += 1
                ws.write(row, 0, note, F["note"]); row += 1
            return row + 2

        def triangle_formats(df, key):
            """Month-index columns all take the same format; COHORT_SIZE stays a count."""
            return {c: key for c in df.columns if re.fullmatch(r"M\d+", str(c))}

        # --- 0. Summary ---
        ws, row = sheet(
            "0. Summary", [5, 44, 88, 26],
            "Mighty Pilates — Cohort & Retention Packet",
            f"Norbrook Lifestyle LLC · prepared by Empirica Analytics · "
            f"{datetime.now():%B %d, %Y}. All figures are customer net SALES (cash collected), "
            f"not recognized revenue — see Methodology before circulating.")
        block(ws, summary, row)

        # --- 1. Methodology ---
        ws, row = sheet("1. Methodology", [30, 112],
                        "Definitions, filters, and caveats")
        ws.write(row, 0, "TOPIC", F["header"])
        ws.write(row, 1, "DETAIL", F["header"])
        row += 1
        for topic, detail in METHODOLOGY:
            ws.write(row, 0, topic, F["text"])
            ws.write(row, 1, detail, F["text"])
            row += 1

        # --- 2. Demographics ---
        d = blocks["demographics"]
        ws, row = sheet("2. Demographics", [30, 16, 18, 24],
                        "Who the typical customer is",
                        "Percentages are of customers with the field populated. Coverage is "
                        "thin and self-reported — directional, not census-grade.")
        row = block(ws, d["fill"], row, "Data coverage")
        row = block(ws, d["gender"], row, "Gender")
        row = block(ws, d["age"], row, "Age band",
                    "'Not captured' means no birthdate on file.")
        block(ws, d["geo"], row, "Where customers live (top 20 cities)",
              "City is hand-typed at signup; case and spacing normalized, common "
              "variants merged.")

        # --- 3. Cohort Retention ---
        c = blocks["cohorts"]
        ws, row = sheet("3. Cohort Retention", [11, 13] + [8] * 37,
                        "Customer retention by join cohort",
                        "% of each cohort attending at least one visit in month N after their "
                        "first purchase. M0 is the join month. Blank = cohort not yet that old.")
        row = block(ws, c["retention"], row,
                    col_formats=triangle_formats(c["retention"], "pct"))
        block(ws, c["summary"], row, "Milestone summary",
              "Recent cohorts are not yet mature — compare like-aged cohorts only.")

        # --- 4. Customer Lifetime ---
        lf = blocks["lifetime"]
        ws, row = sheet("4. Customer Lifetime", [30, 16, 22, 24],
                        "How long customers stay",
                        "Customer lifetime measured on cohorts with 24+ months of possible "
                        "history, so the answer is not dominated by people who have not had "
                        "time to churn.")
        row = block(ws, lf["customer"], row, "Customer lifetime, by segment")
        block(ws, lf["member"], row, "Membership tenure by join month",
              "Recent months are right-censored — a member who joined last month cannot "
              "show long tenure.")

        # --- 5. Churn and Retention ---
        ch = blocks["churn"]
        ws, row = sheet("5. Churn and Retention", [10, 14, 14, 14, 12, 13, 13, 16, 15, 17, 16],
                        "Membership churn and retention",
                        "Person-level. Gross churn counts every exit; net subtracts "
                        "reactivations (about a third of exits return within 45 days) and is "
                        "what actually moves the member base.")
        row = block(ws, ch["yearly"], row, "By year")
        block(ws, ch["monthly"], row, "By month",
              "Current partial month excluded.")

        # --- 6. Customer LTV ---
        lt = blocks["ltv"]
        ws, row = sheet("6. Customer LTV", [30, 15, 20, 22, 24, 26],
                        "Customer lifetime value",
                        "LTV here is lifetime net SALES — cash collected from the customer, "
                        "net of refunds and discounts. Not recognized revenue.")
        row = block(ws, lt["by_segment"], row, "Average and median, by segment",
                    "Cohorts with at least 12 months of history.")
        row = block(ws, lt["distribution"], row, "Distribution of lifetime net sales",
                    "The average is pulled up by a small group — most customers buy an "
                    "intro offer and stop.")
        block(ws, blocks["cohorts"]["ltv"], row,
              "Cumulative net sales per cohort member, by month since joining",
              col_formats=triangle_formats(blocks["cohorts"]["ltv"], "money"))

        # --- 7. Acquisition Channel ---
        a = blocks["acquisition"]
        ws, row = sheet("7. Acquisition Channel", [26, 15, 20, 22, 26],
                        "Where customers say they came from",
                        "Self-reported at signup and captured for only about a third of "
                        "customers. Stated preference, not tracked attribution — there is no "
                        "paid-vs-organic split available.")
        row = block(ws, a["summary"], row, "All time",
                    "'Not captured' is a data gap, not a channel. Read PCT_OF_RESPONDENTS "
                    "for the mix.")
        block(ws, a["by_year"], row, "New customers by channel and cohort year")

        # --- 8. ClassPass Behavior ---
        cp = blocks["classpass"]
        ws, row = sheet("8. ClassPass Behavior", [28, 16, 20, 24, 24, 20, 18],
                        "Do ClassPass customers go on to buy directly?",
                        "'Direct' figures count only what the customer spent with Mighty "
                        "itself. ClassPass pays Mighty outside customer-level sales.")
        row = block(ws, cp["timing"], row, "Conversion from ClassPass to direct purchase")
        row = block(ws, cp["persistence"], row, "Purchasing behavior once they convert")
        block(ws, cp["status"], row, "By ClassPass status flag",
              "Source-system classification, shown for completeness.")

        # --- 9. Membership vs Package ---
        mp = blocks["membership"]
        ws, row = sheet("9. Membership vs Package", [30, 15, 18, 26, 28, 22, 20, 20],
                        "Recurring members vs package and pass buyers",
                        "Segmented on autopay. A customer who bought any autopay product in "
                        "the period counts as recurring.")
        row = block(ws, mp["ttm"], row, "Last 12 months")
        row = block(ws, mp["mix"], row, "Active memberships by type (current)")
        block(ws, mp["monthly"], row, "Monthly trend")

        # --- 10. Non-Member Repurchase ---
        rp = blocks["repurchase"]
        ws, row = sheet("10. Non-Member Repurchase", [30, 20, 22, 18, 18, 18, 32],
                        "How often package buyers come back",
                        "The behavior the lender flagged as important to underwriting.")
        row = block(ws, rp["gaps"], row, "Time between purchases")
        row = block(ws, rp["annual"], row, "Year-over-year repeat rate, non-members")
        block(ws, rp["nth"], row, "How far customers get down the purchase sequence")

    return str(filepath)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_cohort_workbook(conn, start_month: str = "2021-01",
                             output_dir: str = None) -> str:
    root = Path(__file__).parent.parent
    output_dir = Path(output_dir) if output_dir else root / "outputs"
    output_dir.mkdir(exist_ok=True)

    print("Generating Lender Cohort & Retention Packet...")
    _build_base_tables(conn, start_month)

    blocks = {}
    print("  Demographics...");        blocks["demographics"] = _demographics(conn)
    print("  Cohort triangles...");    blocks["cohorts"] = _cohort_triangles(conn)
    print("  Lifetime...");            blocks["lifetime"] = _lifetime(conn)
    print("  Churn...");               blocks["churn"] = _churn(conn)
    print("  LTV...");                 blocks["ltv"] = _ltv(conn)
    print("  Acquisition...");         blocks["acquisition"] = _acquisition(conn)
    print("  ClassPass...");           blocks["classpass"] = _classpass(conn)
    print("  Membership mix...");      blocks["membership"] = _membership_vs_package(conn)
    print("  Repurchase...");          blocks["repurchase"] = _repurchase(conn)

    print("  Building summary...")
    summary = _summary(conn, blocks)

    print("  Writing workbook...")
    path = _write_workbook(blocks, summary, output_dir)
    print(f"  Saved: {path}")
    return path
