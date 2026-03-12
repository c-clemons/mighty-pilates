"""Quick test to verify Snowflake connectivity."""

from pipeline.connection import get_connection, execute_query_df

print("Connecting to Snowflake...")
conn = get_connection()
print("Connected!\n")

# Test 1: Basic query
df = execute_query_df(conn, "SELECT CURRENT_USER() AS USER, CURRENT_ROLE() AS ROLE, CURRENT_WAREHOUSE() AS WH")
print("Session info:")
print(df.to_string(index=False))
print()

# Test 2: Verify we can read the revenue ledger
df2 = execute_query_df(conn, """
    SELECT COUNT(*) AS row_count,
           MIN(EVENT_DATE) AS earliest,
           MAX(EVENT_DATE) AS latest
    FROM DAILY_REVENUE_AND_SALES_DETAIL
""")
print("Revenue ledger:")
print(df2.to_string(index=False))
print()

# Test 3: Verify visit linking registry exists
df3 = execute_query_df(conn, """
    SELECT COUNT(*) AS frozen_visits,
           COUNT(DISTINCT FROZEN_THROUGH_DATE) AS months_frozen
    FROM VISIT_LINKING_REGISTRY
""")
print("Visit Linking Registry:")
print(df3.to_string(index=False))
print()

# Test 4: Check we're a reader account (INSERT should fail)
print("Account type check:")
try:
    conn.cursor().execute("CREATE TEMP TABLE _test_write_check (id INT)")
    conn.cursor().execute("DROP TABLE _test_write_check")
    print("  -> Full account (CREATE TABLE works)")
except Exception as e:
    if "reader" in str(e).lower():
        print("  -> Reader account (DML restricted, using CREATE OR REPLACE pattern)")
    else:
        print(f"  -> Other restriction: {e}")

conn.close()
print("\nConnection test passed!")
