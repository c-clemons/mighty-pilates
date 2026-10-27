"""Read-only Snowflake helper for the marketing/pricing analysis. Temp tables only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root; needs config/ (main checkout, not a worktree)
import pandas as pd
from pipeline.connection import get_connection, execute_query_df, execute_sql
pd.set_option("display.width", 320); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 400)
pd.set_option("display.max_colwidth", 60)
DM = "PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS"
ERA = "MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS"
def conn(): return get_connection()
def q(c, sql):
    df = execute_query_df(c, sql)
    return df
