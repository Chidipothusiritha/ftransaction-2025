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
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg.connect(dsn, connect_timeout=5)
    return psycopg.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "frauddb"),
        user=os.getenv("PGUSER", os.getenv("USER")),
        password=os.getenv("PGPASSWORD"),
        connect_timeout=5,
    )


def get_customer_id_for_account(account_id: int) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM accounts WHERE id = %s;", (account_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Account {account_id} not found")
        return row[0]


def get_or_create_device(customer_id: int, fingerprint: str, label: Optional[str] = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT get_or_create_device(%s, %s, %s);", (customer_id, fingerprint, label))
            return cur.fetchone()[0]
        except Exception:
            conn.rollback()
            cur.execute(
                "SELECT id FROM devices WHERE customer_id = %s AND fingerprint = %s;",
                (customer_id, fingerprint),
            )
            row = cur.fetchone()
            if row:
                device_id = row[0]
                cur.execute("UPDATE devices SET last_seen_ts = NOW() WHERE id = %s;", (device_id,))
                conn.commit()
                return device_id
            cur.execute(
                """
                INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
                VALUES (%s, %s, %s, NOW(), NOW())
                RETURNING id;
                """,
                (customer_id, fingerprint, label),
            )
            device_id = cur.fetchone()[0]
            conn.commit()
            return device_id


def add_transaction(
    account_id: int,
    merchant_id: int,
    amount: float,
    currency: str = "USD",
    status: str = "approved",
    fingerprint: Optional[str] = None,
    device_label: Optional[str] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        device_id = None
        if fingerprint:
            customer_id = get_customer_id_for_account(account_id)
            device_id = get_or_create_device(customer_id, fingerprint, device_label)

        cur.execute(
            """
            INSERT INTO transactions (account_id, merchant_id, amount, currency, status, device_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (account_id, merchant_id, amount, currency, status, device_id),
        )
        txn_id = cur.fetchone()["id"]

        # Best-effort rules (safe if missing)
        for fn in ("rule_amount_spike", "rule_new_device", "rule_velocity_3in2min"):
            try:
                cur.execute(f"SELECT {fn}(%s);", (txn_id,))
            except Exception:
                conn.rollback()

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
        conn.commit()
        return txn_id, alerts


def list_alerts(limit: int = 20) -> List[Dict[str, Any]]:
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


# ---------- Helpers for the web UI ----------

def list_txns_joined(limit: int = 50,
                     q: str = "",
                     merchant: str = "",
                     tstatus: str = "",
                     start_ts: str = None,
                     end_ts: str = None) -> List[Dict[str, Any]]:
    wh = ["1=1"]
    args: Dict[str, Any] = {}
    if q:
        wh.append("(LOWER(c.email) LIKE %(q)s OR LOWER(c.name) LIKE %(q)s OR LOWER(m.name) LIKE %(q)s OR CAST(t.id AS TEXT) = %(qeq)s)")
        args["q"] = f"%{q.lower()}%"
        args["qeq"] = q.lower()
    if merchant:
        wh.append("LOWER(m.name) = %(merchant)s")
        args["merchant"] = merchant.lower()
    if tstatus:
        wh.append("t.status = %(tstatus)s")
        args["tstatus"] = tstatus
    if start_ts and end_ts:
        wh.append("t.ts BETWEEN %(start)s AND %(end)s")
        args["start"] = start_ts; args["end"] = end_ts

    sql = f"""
      SELECT t.id, t.amount, t.currency, t.status, t.ts,
             c.name AS customer_name,
             m.name AS merchant_name,
             d.label AS device_label
      FROM transactions t
      JOIN accounts a   ON a.id = t.account_id
      JOIN customers c  ON c.id = a.customer_id
      JOIN merchants m  ON m.id = t.merchant_id
      LEFT JOIN devices d ON d.id = t.device_id
      WHERE {" AND ".join(wh)}
      ORDER BY t.ts DESC
      LIMIT %(limit)s;
    """
    args["limit"] = limit
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def list_alerts_joined(limit: int = 50,
                       q: str = "",
                       severity: str = "",
                       status: str = "",
                       start_ts: str = None,
                       end_ts: str = None) -> List[Dict[str, Any]]:
    wh = ["1=1"]
    args: Dict[str, Any] = {}
    if severity:
        wh.append("a.severity = %(sev)s"); args["sev"] = severity
    if status:
        wh.append("a.status = %(st)s"); args["st"] = status
    if start_ts and end_ts:
        wh.append("a.created_ts BETWEEN %(start)s AND %(end)s")
        args["start"] = start_ts; args["end"] = end_ts
    if q:
        wh.append("(LOWER(c.email) LIKE %(q)s OR LOWER(c.name) LIKE %(q)s OR CAST(a.transaction_id AS TEXT) = %(qeq)s)")
        args["q"] = f"%{q.lower()}%"; args["qeq"] = q.lower()

    sql = f"""
      SELECT a.id, a.rule_code, a.severity, a.status, a.created_ts, a.transaction_id,
             c.name AS customer_name,
             t.amount
      FROM alerts a
      JOIN transactions t ON t.id = a.transaction_id
      JOIN accounts acc   ON acc.id = t.account_id
      JOIN customers c    ON c.id = acc.customer_id
      WHERE {" AND ".join(wh)}
      ORDER BY a.created_ts DESC
      LIMIT %(limit)s;
    """
    args["limit"] = limit
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def list_devices_joined(limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
      SELECT d.id, d.label, d.fingerprint, d.last_seen_ts, c.name AS customer_name
      FROM devices d
      JOIN customers c ON c.id = d.customer_id
      ORDER BY d.last_seen_ts DESC NULLS LAST
      LIMIT %s;
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return cur.fetchall()


def get_transaction_detail(txn_id: int) -> Dict[str, Any]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
          SELECT t.*, c.id AS customer_id, c.name AS customer_name, c.email,
                 a.id AS account_id, a.account_type,
                 m.id AS merchant_id, m.name AS merchant_name,
                 d.id AS device_id, d.label AS device_label
          FROM transactions t
          JOIN accounts a   ON a.id = t.account_id
          JOIN customers c  ON c.id = a.customer_id
          JOIN merchants m  ON m.id = t.merchant_id
          LEFT JOIN devices d ON d.id = t.device_id
          WHERE t.id = %s;
        """, (txn_id,))
        txn = cur.fetchone()
        if not txn:
            return {}
        cur.execute("""
          SELECT id, rule_code, severity, status, details, created_ts
          FROM alerts
          WHERE transaction_id = %s
          ORDER BY created_ts DESC;
        """, (txn_id,))
        alerts = cur.fetchall()
        txn["alerts"] = alerts
        return txn


def update_alert_status(alert_id: int, new_status: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE alerts SET status=%s WHERE id=%s;", (new_status, alert_id))
        conn.commit()


# Directory helpers (IDs lists) ----------------------------------------------

def list_customers(limit: int = 50):
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
          SELECT id, name, email, signup_ts
          FROM customers
          ORDER BY id ASC
          LIMIT %s;
        """, (limit,))
        return cur.fetchall()

def list_accounts(limit: int = 50):
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
          SELECT a.id, a.customer_id, c.name AS customer_name, a.account_type, a.status, a.opened_ts
          FROM accounts a
          JOIN customers c ON c.id = a.customer_id
          ORDER BY a.id ASC
          LIMIT %s;
        """, (limit,))
        return cur.fetchall()

def list_merchants(limit: int = 50):
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
          SELECT id, name, category, risk_tier
          FROM merchants
          ORDER BY id ASC
          LIMIT %s;
        """, (limit,))
        return cur.fetchall()
