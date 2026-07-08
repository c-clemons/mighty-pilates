"""
Execute the revenue recognition model and manage the visit linking registry.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.connection import get_connection, execute_sql, execute_sql_file, execute_query_df


SQL_DIR = Path(__file__).parent.parent / "sql"


def run_revenue_model(conn, cutoff_date: str = None, pipeline_version: str = "v1"):
    """
    Run the full revenue recognition model.

    Args:
        conn: Snowflake connection
        cutoff_date: Optional YYYY-MM-DD to filter visits (for isolated month runs).
                     If None, runs with all data.
        pipeline_version: 'v1' (default, sql/revenue_recognition.sql) or
                         'v2' (sql/v2/revenue_recognition_v2.sql — uses
                         MindBody-provided PRICING_OPTION_EXPIRATION_DATE,
                         IS_RETURN_OR_RETURNED, and visit expiration filter).
    """
    if pipeline_version == "v2":
        sql_path = SQL_DIR / "v2" / "revenue_recognition_v2.sql"
    else:
        sql_path = SQL_DIR / "revenue_recognition.sql"
    print(f"Running revenue recognition model [{pipeline_version}] from {sql_path}...")

    # v2 (2026-07-08 restructure per Fable F4): load Cat's authoritative durations
    # into a session-scoped temp table BEFORE the main SQL runs. The main SQL
    # references CAT_APPROVED_DURATIONS as if it exists (which it now does).
    if pipeline_version == "v2":
        cat_sql_path = SQL_DIR / "v2" / "cat_approved_durations.sql"
        print(f"  Loading Cat approved durations from {cat_sql_path.name}...")
        cat_sql = cat_sql_path.read_text()
        cur = conn.cursor()
        try:
            cur.execute(cat_sql)
            cur.execute("SELECT COUNT(*) FROM CAT_APPROVED_DURATIONS")
            n = cur.fetchone()[0]
            print(f"    Loaded {n} Cat-approved product durations.")
        finally:
            cur.close()

    with open(sql_path) as f:
        sql_content = f.read()

    # Inject cutoff if specified
    if cutoff_date:
        print(f"  Cutoff filter active: visits through {cutoff_date}")
        # Add SET and filter after USE SCHEMA line
        inject = f"\nSET MODEL_CUTOFF_DATE = '{cutoff_date}';\n"
        sql_content = sql_content.replace(
            "USE SCHEMA EARNED_REVENUE_ANALYTICS;",
            f"USE SCHEMA EARNED_REVENUE_ANALYTICS;\n{inject}",
        )
        # Add filter to VISITS_ENRICHED
        sql_content = sql_content.replace(
            "WHERE v.CLASS_DATE IS NOT NULL",
            "WHERE v.CLASS_DATE IS NOT NULL\n    AND v.CLASS_DATE <= $MODEL_CUTOFF_DATE",
            1,  # Only first occurrence (VISITS_ENRICHED)
        )

    from pipeline.connection import _split_sql_statements

    # v2 rewrite (2026-07-08 per Fable F5): split SQL execution at the
    # "-- SPLIT: check hard-fail here" marker. Between the two halves we
    # query PACKAGES_NEEDING_DURATION and abort the run if any product Cat
    # hasn't ruled on has open deferred or recent-year sales — so §4D
    # never writes wrong durations into the persistent registry.
    SPLIT_MARKER = "-- SPLIT: check hard-fail here"

    if pipeline_version == "v2" and SPLIT_MARKER in sql_content:
        pre_marker, post_marker = sql_content.split(SPLIT_MARKER, 1)
        pre_statements = _split_sql_statements(pre_marker)
        post_statements = _split_sql_statements(post_marker)
    else:
        pre_statements = _split_sql_statements(sql_content)
        post_statements = []

    cur = conn.cursor()
    total = len(pre_statements) + len(post_statements)

    def _run_batch(stmts, start_i):
        for i, stmt in enumerate(stmts, start_i):
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.upper().startswith(("CREATE", "SELECT")):
                preview = stmt[:80].replace("\n", " ")
                print(f"  [{i}/{total}] {preview}...")
            cur.execute(stmt)
            if cur.description and stmt.upper().startswith("SELECT"):
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                for row in rows[:3]:
                    print(f"    {dict(zip(cols, row))}")

    try:
        _run_batch(pre_statements, 1)

        # v2 hard-fail check between §4C diagnostic build and §4D registry write.
        # Blocks the close ONLY for new packs Cat hasn't ruled on that were sold
        # in the last 90 days (i.e., relevant to this close and potentially
        # future ones). Ancient dormant products go into a separate warning list
        # (`LEGACY_UNRULED_PRODUCTS`) for a separate Cat-audit workflow — the
        # deferred on those packs is already-recognized by frozen months and
        # doesn't affect current-period rev rec.
        if pipeline_version == "v2" and post_statements:
            cur.execute("""
                SELECT pnd.PRODUCT_ID, MAX(pnd.PRODUCT_DESCRIPTION), MAX(pnd.REVENUE_CATEGORY),
                       COUNT(*) AS N_NEW_PACKS,
                       SUM(pv.NET_PACKAGE_PRICE) AS NEW_PACK_DOLLARS,
                       MIN(pv.SALE_DATE) AS FIRST_NEW, MAX(pv.SALE_DATE) AS LAST_NEW
                FROM PACKAGES_NEEDING_DURATION pnd
                JOIN PRICING_PER_VISIT_UNIQ pv ON pv.PRODUCT_ID = pnd.PRODUCT_ID
                LEFT JOIN PACKAGE_EXPIRATION_REGISTRY per ON per.PACKAGE_ID = pv.PACKAGE_ID
                WHERE per.PACKAGE_ID IS NULL  -- pack would be newly added
                  AND pv.SALE_DATE >= DATEADD(DAY, -90, CURRENT_DATE)
                GROUP BY pnd.PRODUCT_ID
                HAVING COUNT(*) > 0
                ORDER BY NEW_PACK_DOLLARS DESC NULLS LAST
            """)
            rows = cur.fetchall()

            # Also surface a warning for legacy unruled products (>90d old,
            # any dollars): sold-then-forgotten products that will eventually
            # need Cat's ruling but don't block THIS close.
            cur.execute("""
                CREATE OR REPLACE TABLE LEGACY_UNRULED_PRODUCTS AS
                SELECT pnd.PRODUCT_ID, MAX(pnd.PRODUCT_DESCRIPTION) AS PRODUCT_DESCRIPTION,
                       MAX(pnd.REVENUE_CATEGORY) AS REVENUE_CATEGORY,
                       COUNT(*) AS N_NEW_PACKS,
                       SUM(pv.NET_PACKAGE_PRICE) AS NEW_PACK_DOLLARS,
                       MIN(pv.SALE_DATE) AS FIRST_NEW, MAX(pv.SALE_DATE) AS LAST_NEW
                FROM PACKAGES_NEEDING_DURATION pnd
                JOIN PRICING_PER_VISIT_UNIQ pv ON pv.PRODUCT_ID = pnd.PRODUCT_ID
                LEFT JOIN PACKAGE_EXPIRATION_REGISTRY per ON per.PACKAGE_ID = pv.PACKAGE_ID
                WHERE per.PACKAGE_ID IS NULL
                  AND pv.SALE_DATE < DATEADD(DAY, -90, CURRENT_DATE)
                GROUP BY pnd.PRODUCT_ID
            """)
            cur.execute("SELECT COUNT(*), COALESCE(SUM(NEW_PACK_DOLLARS),0) FROM LEGACY_UNRULED_PRODUCTS")
            n_legacy, dollars_legacy = cur.fetchone()
            if n_legacy > 0:
                print(f"\n[WARNING] LEGACY_UNRULED_PRODUCTS: {int(n_legacy)} products, ${float(dollars_legacy):,.0f}")
                print("          Products with sales older than 90 days that Cat hasn't ruled on.")
                print("          These do not block the current close but need Cat-audit follow-up.")
            if rows:
                print("\n" + "=" * 78)
                print("STRICT POLICY ABORT: NEW packs would be inserted for products not on Cat's list")
                print("=" * 78)
                total_dollars = 0
                for pid, desc, cat, n, dollars, first, last in rows:
                    d = float(dollars or 0)
                    total_dollars += d
                    print(f"  {(desc or '?')[:60]:<60}  ({(cat or '?')[:20]:<20}, {int(n)} new pkgs, ${d:>10,.0f})")
                raise RuntimeError(
                    f"{len(rows)} product(s) not on Cat's approved list have new packs "
                    f"pending registry insert (${total_dollars:,.0f} sales). Add them to "
                    "sql/v2/cat_approved_durations.sql after Cat sign-off, then re-run. "
                    "Registry NOT written."
                )
            print(f"\n[HARD-FAIL CHECK] PACKAGES_NEEDING_DURATION clean for new packs; proceeding to registry write.")

        _run_batch(post_statements, len(pre_statements) + 1)
    finally:
        cur.close()

    print("Revenue recognition model complete.")


def freeze_month(conn, month_end: str):
    """
    Freeze visit-to-package assignments through a given month-end date.
    Uses CREATE OR REPLACE pattern (compatible with reader accounts).

    Args:
        conn: Snowflake connection
        month_end: YYYY-MM-DD (e.g., '2026-02-28')
    """
    # Derive month start from month_end
    from datetime import datetime as _dt
    _end = _dt.strptime(month_end, "%Y-%m-%d")
    month_start = _end.replace(day=1).strftime("%Y-%m-%d")

    print(f"Freezing visit assignments for {month_start} to {month_end}...")

    # Check if this month is already frozen — never overwrite a closed month
    already_frozen = execute_query_df(conn, f"""
        SELECT COUNT(*) AS CNT
        FROM VISIT_LINKING_REGISTRY
        WHERE FROZEN_THROUGH_DATE = '{month_end}'
    """)
    if already_frozen.iloc[0]['CNT'] > 0:
        print(f"  Month {month_end} is already frozen ({already_frozen.iloc[0]['CNT']} visits). Skipping.")
        return

    # Preview — only visits WITHIN the target month
    preview = execute_query_df(conn, f"""
        SELECT
            COUNT(*) AS visit_count,
            COUNT(DISTINCT UNIQUE_PACKAGE_ID_LNK) AS packages_affected
        FROM VISITS_LINKED vl
        WHERE vl.VISIT_DATE >= '{month_start}' AND vl.VISIT_DATE <= '{month_end}'
          AND vl.UNIQUE_VISIT_REF_NO NOT IN (
            SELECT VISIT_ID FROM VISIT_LINKING_REGISTRY
          )
    """)
    print(f"  New visits to freeze: {preview.iloc[0]['VISIT_COUNT']}")
    print(f"  Packages affected: {preview.iloc[0]['PACKAGES_AFFECTED']}")

    # Rebuild registry: preserve ALL prior months + add this month's visits only
    execute_sql(conn, f"""
        CREATE OR REPLACE TABLE VISIT_LINKING_REGISTRY AS

        SELECT VISIT_ID, PACKAGE_ID, LINK_TYPE, LINK_RANK,
               VISIT_DATE, SERVICE_TYPE, STUDIO_ID, STUDIO_NAME,
               LOCATION_ID, LOCATION_NAME, CLIENT_ID, GLOBAL_CLIENT_KEY,
               PAYMENT_KEY, PAYMENT_REF_NO, FROZEN_THROUGH_DATE, FROZEN_AT
        FROM VISIT_LINKING_REGISTRY

        UNION ALL

        SELECT
            vl.UNIQUE_VISIT_REF_NO AS VISIT_ID,
            vl.UNIQUE_PACKAGE_ID_LNK AS PACKAGE_ID,
            vl.LINK_TYPE, vl.LINK_RANK,
            vl.VISIT_DATE, vl.SERVICE_TYPE,
            vl.STUDIO_ID, vl.STUDIO_NAME,
            vl.LOCATION_ID, vl.LOCATION_NAME,
            vl.CLIENT_ID, vl.GLOBAL_CLIENT_KEY,
            vl.PAYMENT_KEY, vl.PAYMENT_REF_NO,
            '{month_end}' AS FROZEN_THROUGH_DATE,
            CURRENT_TIMESTAMP() AS FROZEN_AT
        FROM VISITS_LINKED vl
        WHERE vl.VISIT_DATE >= '{month_start}' AND vl.VISIT_DATE <= '{month_end}'
          AND vl.UNIQUE_VISIT_REF_NO NOT IN (
            SELECT VISIT_ID FROM VISIT_LINKING_REGISTRY
          )
    """)

    # Verify
    result = execute_query_df(conn, """
        SELECT FROZEN_THROUGH_DATE, LINK_TYPE, COUNT(*) AS VISIT_COUNT
        FROM VISIT_LINKING_REGISTRY
        GROUP BY FROZEN_THROUGH_DATE, LINK_TYPE
        ORDER BY FROZEN_THROUGH_DATE, LINK_TYPE
    """)
    print("  Registry status:")
    print(result.to_string(index=False))
    print("  Freeze complete.")


def close_month(conn, year: int, month: int):
    """
    Full month-end close process:
    1. Run model with all data
    2. Freeze visit-to-package assignments for the month
    3. Run model again (frozen visits now locked)
    4. Freeze monthly GL totals from live Saasant output (bit-exact reproducibility for future runs)
    """
    from pipeline.frozen_gl import freeze_from_live, is_month_frozen

    import calendar
    last_day = calendar.monthrange(year, month)[1]
    month_end = f"{year}-{month:02d}-{last_day:02d}"
    month_ym = f"{year}-{month:02d}"

    print(f"\n{'='*60}")
    print(f"MONTH-END CLOSE: {year}-{month:02d}")
    print(f"{'='*60}\n")

    print("Step 1: Running model with all data...")
    run_revenue_model(conn)

    print(f"\nStep 2: Freezing visit assignments through {month_end}...")
    freeze_month(conn, month_end)

    print("\nStep 3: Re-running model (frozen visits now locked)...")
    run_revenue_model(conn)

    print(f"\nStep 4: Freezing monthly GL totals for {month_ym}...")
    if is_month_frozen(conn, month_ym):
        print(f"  {month_ym} GL already frozen. Skipping (use 'freeze-gl --month {month_ym} --force' to re-freeze).")
    else:
        result = freeze_from_live(conn, year, month)
        print(f"  Generated: {result['saasant_path']}")
        print(f"  Froze {result['rows_frozen']} GL rows for {month_ym}")

    print(f"\nMonth-end close complete for {year}-{month:02d}.")
