import os
from typing import Any, Dict, List, Tuple, Optional
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    """
    Establish a PostgreSQL connection using environment variables or defaults.
    """
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "frauddb"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )


def get_customer_id_for_account(account_id: int) -> int:
    """
    Given an account_id, return the corresponding customer_id.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM accounts WHERE id = %s;", (account_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Account {account_id} not found")
        return row[0]


def get_or_create_device(customer_id: int, fingerprint: str, label: Optional[str] = None) -> int:
    """
    Ensure a device exists for the given (customer_id, fingerprint).
    Tries SQL helper 'get_or_create_device' first; falls back to inline upsert.
    """
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Try calling helper SQL function (if defined in DB)
            cur.execute("SELECT get_or_create_device(%s, %s, %s);", (customer_id, fingerprint, label))
            device_id = cur.fetchone()[0]
            return device_id
        except Exception:
            conn.rollback()
            # Manual fallback logic
            cur.execute(
                "SELECT id FROM devices WHERE customer_id = %s AND fingerprint = %s;",
                (customer_id, fingerprint),
            )
            row = cur.fetchone()
            if row:
                device_id = row[0]
                cur.execute("UPDATE devices SET last_seen_ts = NOW() WHERE id = %s;", (device_id,))
                return device_id

            cur.execute(
                """
                INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
                VALUES (%s, %s, %s, NOW(), NOW())
                RETURNING id;
                """,
                (customer_id, fingerprint, label),
            )
            return cur.fetchone()[0]


def add_transaction(
    account_id: int,
    merchant_id: int,
    amount: float,
    currency: str = "USD",
    status: str = "approved",
    fingerprint: Optional[str] = None,
    device_label: Optional[str] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Insert a transaction, optionally link a device, then run rules.
    Returns (transaction_id, alerts_rows)
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        # Link device if provided
        device_id = None
        if fingerprint:
            customer_id = get_customer_id_for_account(account_id)
            device_id = get_or_create_device(customer_id, fingerprint, device_label)

        # Insert transaction
        cur.execute(
            """
            INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (account_id, merchant_id, amount, currency, status, device_id),
        )
        txn_id = cur.fetchone()["id"]

        # Run rules
        cur.execute("SELECT rule_amount_spike(%s);", (txn_id,))
        try:
            cur.execute("SELECT rule_new_device(%s);", (txn_id,))
        except Exception:
            # If rule_new_device not yet created, ignore and continue
            conn.rollback()
            conn.commit()
        
        try:
            cur.execute("SELECT rule_velocity_3in2min(%s);", (txn_id,))
        except Exception:
            conn.rollback()
            conn.commit()
            
        # Fetch alerts
        cur.execute(
            """
            SELECT id, rule_code, severity, status, created_ts, details
            FROM alerts
            WHERE transaction_id = %s
            ORDER BY created_ts DESC;
            """,
            (txn_id,),
        )
        alerts = cur.fetchall()

        return txn_id, alerts


def list_alerts(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Retrieve recent alerts joined with transaction details.
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
                   t.amount, t.account_id, t.merchant_id, t.device_id
            FROM alerts a
            JOIN transactions t ON t.id = a.transaction_id
            ORDER BY a.created_ts DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()


def list_transactions(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Retrieve recent transactions with core details.
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, account_id, merchant_id, device_id, amount, currency, status, ts
            FROM transactions
            ORDER BY ts DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()


def list_devices(customer_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Retrieve devices (optionally filtered by customer_id).
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        if customer_id:
            cur.execute(
                """
                SELECT id, customer_id, fingerprint, label, first_seen_ts, last_seen_ts
                FROM devices
                WHERE customer_id = %s
                ORDER BY last_seen_ts DESC
                LIMIT %s;
                """,
                (customer_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, customer_id, fingerprint, label, first_seen_ts, last_seen_ts
                FROM devices
                ORDER BY last_seen_ts DESC NULLS LAST
                LIMIT %s;
                """,
                (limit,),
            )
        return cur.fetchall()
