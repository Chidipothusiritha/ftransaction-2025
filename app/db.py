# app/db.py

from __future__ import annotations

import os
from typing import List, Tuple, Sequence, Dict, Any

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

MAX_ROWS = int(os.getenv("MAX_ROWS", "500"))


def get_conn():
    """
    Establish a PostgreSQL connection using DATABASE_URL if present,
    otherwise individual PG* environment variables.
    Uses dict_row so rows behave like dicts.
    """
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5)

    return psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "frauddb"),
        user=os.getenv("PGUSER", os.getenv("USER")),
        password=os.getenv("PGPASSWORD"),
        row_factory=dict_row,
        connect_timeout=5,
    )


def run_query(sql: str, params: tuple = ()) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Convenience helper used by routes/services:
      - opens a connection
      - executes SQL with params
      - returns (column_names, rows_as_dicts)
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchmany(MAX_ROWS) if cur.description else []
        if rows:
            cols = list(rows[0].keys())
        else:
            cols = [d.name for d in cur.description] if cur.description else []
        return cols, rows


def table_exists(schema: str, table: str) -> bool:
    """
    Check information_schema.tables for given schema.table.
    """
    _, rows = run_query(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema=%s AND table_name=%s
        """,
        (schema, table),
    )
    return bool(rows)


def table_columns(schema: str, table: str) -> Sequence[str]:
    """
    List column names for schema.table in ordinal order.
    """
    _, rows = run_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [r["column_name"] for r in rows]
