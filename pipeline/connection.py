"""
Snowflake connection manager using key-pair authentication.
"""

import os
import yaml
import snowflake.connector
from cryptography.hazmat.primitives import serialization
from pathlib import Path


def _load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "snowflake_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _load_private_key(key_path: str) -> bytes:
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_connection(config_path: str = None) -> snowflake.connector.SnowflakeConnection:
    """
    Create a Snowflake connection using key-pair auth.
    Returns a snowflake.connector connection object.
    """
    cfg = _load_config(config_path)
    sf = cfg["snowflake"]

    # Resolve key path relative to project root
    key_path = sf["private_key_path"]
    if not os.path.isabs(key_path):
        key_path = Path(__file__).parent.parent / key_path

    private_key_der = _load_private_key(str(key_path))

    conn = snowflake.connector.connect(
        account=sf["account"],
        user=sf["user"],
        private_key=private_key_der,
        warehouse=sf["warehouse"],
        database=sf["database"],
        schema=sf["schema"],
        role=sf["role"],
    )
    return conn


def execute_sql(conn, sql: str, params: dict = None) -> list:
    """Execute a SQL statement and return results."""
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        if cur.description:
            return cur.fetchall()
        return []
    finally:
        cur.close()


def execute_sql_file(conn, filepath: str) -> list:
    """
    Execute a SQL file containing multiple statements.
    Returns results from the last statement that produced output.
    """
    with open(filepath) as f:
        sql_content = f.read()

    results = []
    cur = conn.cursor()
    try:
        for statement in _split_sql_statements(sql_content):
            statement = statement.strip()
            if not statement:
                continue
            cur.execute(statement)
            if cur.description:
                results = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
                print(f"  -> {cols}: {len(results)} rows")
    finally:
        cur.close()
    return results


def execute_query_df(conn, sql: str, params: dict = None):
    """Execute a query and return results as a pandas DataFrame."""
    import pandas as pd
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        if cur.description:
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            df = pd.DataFrame(rows, columns=cols)
            # Snowflake returns Decimal types which pandas stores as object dtype.
            # Convert columns containing Decimal values to float64 so they are
            # written as numbers (not text) in Excel exports.
            # Only convert if first non-null value is actually a Decimal,
            # NOT a string (e.g. GL codes like '401003' must stay as strings).
            from decimal import Decimal as _Decimal
            for col in df.columns:
                if df[col].dtype == object and len(df) > 0:
                    sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
                    if isinstance(sample, _Decimal):
                        df[col] = pd.to_numeric(df[col])
            return df
        return pd.DataFrame()
    finally:
        cur.close()


def _split_sql_statements(sql: str) -> list:
    """
    Split SQL into individual statements on semicolons,
    respecting string literals and comments.
    """
    statements = []
    current = []
    in_single_quote = False
    in_line_comment = False
    in_block_comment = False
    i = 0

    while i < len(sql):
        c = sql[i]

        if in_line_comment:
            current.append(c)
            if c == '\n':
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(c)
            if c == '*' and i + 1 < len(sql) and sql[i + 1] == '/':
                current.append('/')
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_single_quote:
            current.append(c)
            if c == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                current.append("'")
                i += 2
                continue
            if c == "'":
                in_single_quote = False
            i += 1
            continue

        # Check for comments
        if c == '-' and i + 1 < len(sql) and sql[i + 1] == '-':
            in_line_comment = True
            current.append(c)
            i += 1
            continue

        if c == '/' and i + 1 < len(sql) and sql[i + 1] == '*':
            in_block_comment = True
            current.append(c)
            i += 1
            continue

        if c == "'":
            in_single_quote = True
            current.append(c)
            i += 1
            continue

        if c == ';':
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    # Last statement (no trailing semicolon)
    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements
