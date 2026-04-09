"""
One-time script to update PACKAGE_EXPIRATION_REGISTRY with client-approved durations.
Uses CREATE OR REPLACE (reader account can't use UPDATE).
"""

import sys
sys.path.insert(0, '.')
from pipeline.connection import get_connection, execute_query_df


def main():
    conn = get_connection()
    cur = conn.cursor()

    # Build the override CASE expressions
    # Each entry: (LIKE pattern, new_expiration_expr, new_duration_expr, median_value)
    month_overrides = [
        # pattern, months
        ("1 Machine Class", 6),
        ("3 Machine Classes", 6),
        ("6 Machine Classes", 6),
        ("10 Machine Classes", 6),
        ("New Staff 10 machine classes", 6),
        ("MMP 20", 6),
        ("Staff Drop In Class - $5", 6),
        ("Mighty Pilates Workshops", 6),
        ("Non-Member", 6),
        ("Apprentice - Series of 5 Privates", 6),
        ("Apprentice Duet", 6),
        ("Single Livestream Class", 6),
        ("Series of 5 Livestream Classes", 6),
        ("5 Mat Pilates - At home", 6),
        ("5 Mat Pilates - At Home", 6),
        ("5  Mat Classes - At home", 6),
        ("1 Mat Pilates - At Home Class", 6),
        ("1 Mat Pilates - At home", 6),
        ("1  Mat Class - At home", 6),
        ("1 Mat Class - At home", 6),
        ("20 Pack Live Stream Pilates Private", 6),
        ("Live Stream Pilates Private", 6),
        ("Private Room Rental", 6),
        ("Private Rental Marin", 1),
        ("Mighty Mixer: 1 Room (Non Prime)", 1),
        ("Pilates and Sound Bath", 1),
        ("Dynamic Pricing", 12),
    ]

    like_overrides = [
        # LIKE pattern, months
        ("Ready, Set, Spring!%", 6),
        ("Ready Set Spring%", 6),
        ("Bloom In Strength Flash Sale%", 6),
        ("Tinsel & Tone Flash Sale%", 6),
        ("Align & Shine Summer Flash Sale%", 6),
        ("Spooky Strength Flash Sale%", 6),
        ("Core & Cupid Flash Sale%", 6),
        ("6 Week Series%", 6),
        ("Post Baby Strength & Pelvic Floor Connection%", 6),
        ("Friends On The Frontlines%", 6),
        ("Welcome Back Offer%", 2),
        ("Welcome Back:%", 2),
        ("ClassPass Special%", 2),
        ("Classpass Special%", 2),
        ("1-Time Special Offer%", 2),
        ("New Private Client Special - 3 sessions%", 2),
        ("New Private Client Special - 3 Sessions%", 2),
        ("Next Stop: Russian Hill!%", 2),
    ]

    exact_2mo = [
        "New Private Client Special: 3 Privates for $225",
        "New Client Duet Special 3 for $145",
    ]

    day_overrides = [
        # pattern, days
        ("Voyager Pass", 10),
        ("Gympass", 15),
        ("Mighty Monthly 20 Pass", 1),
        ("Private Class Buyout", 1),
        ("MMP Member Pop Up", 1),
        ("MMP member Pop Up", 1),
        ("MMP Workshop", 1),
        ("Donation Class", 1),
    ]

    # Build CASE WHEN expression for EXPIRATION_DATE
    exp_cases = []
    dur_cases = []
    med_cases = []

    for pattern, months in month_overrides:
        safe = pattern.replace("'", "''")
        exp_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN DATEADD(MONTH, {months}, START_DATE)")
        dur_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN DATEDIFF(DAY, START_DATE, DATEADD(MONTH, {months}, START_DATE))")
        med_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN {months}")

    for pattern, months in like_overrides:
        safe = pattern.replace("'", "''")
        exp_cases.append(f"WHEN PRODUCT_DESCRIPTION LIKE '{safe}' THEN DATEADD(MONTH, {months}, START_DATE)")
        dur_cases.append(f"WHEN PRODUCT_DESCRIPTION LIKE '{safe}' THEN DATEDIFF(DAY, START_DATE, DATEADD(MONTH, {months}, START_DATE))")
        med_cases.append(f"WHEN PRODUCT_DESCRIPTION LIKE '{safe}' THEN {months}")

    for pattern in exact_2mo:
        safe = pattern.replace("'", "''")
        exp_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN DATEADD(MONTH, 2, START_DATE)")
        dur_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN DATEDIFF(DAY, START_DATE, DATEADD(MONTH, 2, START_DATE))")
        med_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN 2")

    for pattern, days in day_overrides:
        safe = pattern.replace("'", "''")
        exp_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN DATEADD(DAY, {days}, START_DATE)")
        dur_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN {days}")
        med_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN NULL")

    exp_sql = "\n        ".join(exp_cases)
    dur_sql = "\n        ".join(dur_cases)
    med_sql = "\n        ".join(med_cases)

    # Count before
    before = execute_query_df(conn, """
        SELECT COUNT(*) as total FROM PACKAGE_EXPIRATION_REGISTRY
    """)
    print(f"Registry entries before: {before.iloc[0, 0]}")

    sql = f"""
    CREATE OR REPLACE TABLE PACKAGE_EXPIRATION_REGISTRY AS
    SELECT
        PACKAGE_ID,
        START_DATE,
        CASE
            {exp_sql}
            ELSE EXPIRATION_DATE
        END AS EXPIRATION_DATE,
        CASE
            {dur_sql}
            ELSE PACKAGE_DURATION_DAYS
        END AS PACKAGE_DURATION_DAYS,
        EXPIRATION_SOURCE,
        ASSIGNED_ON,
        CASE
            {med_sql}
            ELSE MEDIAN_USED
        END AS MEDIAN_USED,
        PRODUCT_DESCRIPTION,
        REVENUE_CATEGORY,
        CASE
            WHEN (
                {exp_sql.replace('THEN DATEADD(MONTH', 'THEN 1').replace('THEN DATEADD(DAY', 'THEN 1').replace('DATEADD(MONTH', '1').replace('DATEADD(DAY', '1').replace(', START_DATE)', '').replace('THEN DATEDIFF(DAY, START_DATE, 1)', 'THEN 1')}
            ) IS NOT NULL
            THEN 'Duration corrected per client approval 2026-04-08'
            ELSE NOTES
        END AS NOTES
    FROM PACKAGE_EXPIRATION_REGISTRY
    """

    # The NOTES case is getting complex. Simpler approach: just build a flag
    # Actually let's simplify — just update notes for all matching patterns
    note_cases = []
    for pattern, _ in month_overrides:
        safe = pattern.replace("'", "''")
        note_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN 'Duration corrected per client approval 2026-04-08'")
    for pattern, _ in like_overrides:
        safe = pattern.replace("'", "''")
        note_cases.append(f"WHEN PRODUCT_DESCRIPTION LIKE '{safe}' THEN 'Duration corrected per client approval 2026-04-08'")
    for pattern in exact_2mo:
        safe = pattern.replace("'", "''")
        note_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN 'Duration corrected per client approval 2026-04-08'")
    for pattern, _ in day_overrides:
        safe = pattern.replace("'", "''")
        note_cases.append(f"WHEN PRODUCT_DESCRIPTION = '{safe}' THEN 'Duration corrected per client approval 2026-04-08'")

    note_sql = "\n        ".join(note_cases)

    sql = f"""
    CREATE OR REPLACE TABLE PACKAGE_EXPIRATION_REGISTRY AS
    SELECT
        PACKAGE_ID,
        START_DATE,
        CASE
            {exp_sql}
            ELSE EXPIRATION_DATE
        END AS EXPIRATION_DATE,
        CASE
            {dur_sql}
            ELSE PACKAGE_DURATION_DAYS
        END AS PACKAGE_DURATION_DAYS,
        EXPIRATION_SOURCE,
        ASSIGNED_ON,
        CASE
            {med_sql}
            ELSE MEDIAN_USED
        END AS MEDIAN_USED,
        PRODUCT_DESCRIPTION,
        REVENUE_CATEGORY,
        CASE
            {note_sql}
            ELSE NOTES
        END AS NOTES
    FROM PACKAGE_EXPIRATION_REGISTRY
    """

    print("Executing registry rebuild...")
    cur.execute(sql)

    # Count after and verify
    after = execute_query_df(conn, """
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN NOTES LIKE '%2026-04-08%' THEN 1 END) as updated
        FROM PACKAGE_EXPIRATION_REGISTRY
    """)
    print(f"Registry entries after: {after.iloc[0, 0]}, updated: {after.iloc[0, 1]}")

    # Duration distribution
    dist = execute_query_df(conn, """
        SELECT
            CASE
                WHEN PACKAGE_DURATION_DAYS <= 1 THEN '1 day (immediate)'
                WHEN PACKAGE_DURATION_DAYS <= 15 THEN '2-15 days'
                WHEN PACKAGE_DURATION_DAYS <= 35 THEN '~1 month'
                WHEN PACKAGE_DURATION_DAYS <= 65 THEN '~2 months'
                WHEN PACKAGE_DURATION_DAYS <= 195 THEN '~6 months'
                WHEN PACKAGE_DURATION_DAYS <= 370 THEN '~12 months'
                ELSE '12+ months'
            END AS duration_bucket,
            COUNT(*) as packages,
            COUNT(CASE WHEN NOTES LIKE '%2026-04-08%' THEN 1 END) as changed_today
        FROM PACKAGE_EXPIRATION_REGISTRY
        GROUP BY duration_bucket
        ORDER BY MIN(PACKAGE_DURATION_DAYS)
    """)
    print("\nDuration distribution after update:")
    print(dist.to_string(index=False))

    conn.close()
    print("\nDone. Now run: python run.py model && python run.py export")


if __name__ == "__main__":
    main()
