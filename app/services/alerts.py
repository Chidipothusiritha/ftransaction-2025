# app/services/alerts.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ..db import run_query, table_exists, table_columns


# ------------------------ Alert rule defaults ------------------------

DEFAULT_THRESHOLD = 200.0
DEFAULT_SPIKE_MULTIPLIER = 2.5
DEFAULT_LOOKBACK_DAYS = 30


def get_alert_rule_for_account(account_id: Optional[int]) -> Dict[str, Any]:
    """
    Fetch per-account alert rule from alert_rules table if it exists,
    otherwise fall back to defaults.
    """
    if account_id is None or not table_exists("public", "alert_rules"):
        return {
            "amount_threshold": DEFAULT_THRESHOLD,
            "spike_multiplier": DEFAULT_SPIKE_MULTIPLIER,
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
        }

    # Specific rule for this account
    _, rows = run_query(
        """
        SELECT amount_threshold::float AS amount_threshold,
               spike_multiplier::float  AS spike_multiplier,
               lookback_days::int       AS lookback_days
        FROM alert_rules
        WHERE account_id=%s
        """,
        (account_id,),
    )
    if rows:
        return rows[0]

    # Fallback default row (account_id IS NULL)
    _, defrows = run_query(
        """
        SELECT amount_threshold::float AS amount_threshold,
               spike_multiplier::float  AS spike_multiplier,
               lookback_days::int       AS lookback_days
        FROM alert_rules
        WHERE account_id IS NULL
        """
    )
    if defrows:
        return defrows[0]

    return {
        "amount_threshold": DEFAULT_THRESHOLD,
        "spike_multiplier": DEFAULT_SPIKE_MULTIPLIER,
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
    }


def rolling_avg_amount(account_id: int, lookback_days: int) -> float:
    """
    Average transaction amount for this account over the last N days.
    """
    _, rows = run_query(
        """
        SELECT COALESCE(AVG(amount),0)::float AS avg_amt
        FROM transactions
        WHERE account_id=%s
          AND ts >= NOW() - %s::interval
        """,
        (account_id, f"{lookback_days} days"),
    )
    return float(rows[0]["avg_amt"]) if rows else 0.0


def notifications_mode() -> Optional[str]:
    """
    Auto-detect notifications schema.
    Returns:
      - 'simple'   -> transaction_id, message, created_ts, delivered
      - 'channels' -> alert_id, channel, status, sent_ts, payload
      - None       -> unknown schema (no auto-insert)
    """
    if not table_exists("public", "notifications"):
        return None
    cols = set(table_columns("public", "notifications"))
    if {"transaction_id", "message", "created_ts", "delivered"}.issubset(cols):
        return "simple"
    if {"alert_id", "channel", "status", "sent_ts", "payload"}.issubset(cols):
        return "channels"
    return None


def create_alert(
    transaction_id: int,
    rule_code: str,
    severity: str = "high",   # enum: low / med / high
    status: str = "open",     # enum: open / cleared / confirmed
) -> None:
    """
    Insert an alert row, and optionally mirror into notifications depending on schema.
    """
    sev = (severity or "high").lower()
    st = (status or "open").lower()

    run_query(
        """
        INSERT INTO alerts (transaction_id, rule_code, severity, status, created_ts)
        VALUES (%s,%s,%s,%s,NOW())
        """,
        (transaction_id, rule_code, sev, st),
    )

    mode = notifications_mode()
    if mode == "simple":
        msg = f"Alert {rule_code} triggered for transaction {transaction_id}"
        run_query(
            """
            INSERT INTO notifications (transaction_id, message, created_ts, delivered)
            VALUES (%s,%s,NOW(),FALSE)
            """,
            (transaction_id, msg),
        )
    elif mode == "channels":
        _, aid_row = run_query(
            "SELECT id FROM alerts WHERE transaction_id=%s ORDER BY id DESC LIMIT 1",
            (transaction_id,),
        )
        if aid_row:
            run_query(
                """
                INSERT INTO notifications (alert_id, channel, status, sent_ts, payload)
                VALUES (%s,'ui','PENDING',NOW(), jsonb_build_object('message', %s))
                """,
                (aid_row[0]["id"], f"Alert {rule_code} for txn {transaction_id}"),
            )


# ------------------------ Risk-tier helpers ------------------------

def _merchant_risk_tier(merchant_id: Optional[int]) -> str:
    """
    Return normalized risk tier for merchant: 'low','med','high', or 'med' default.
    """
    if not merchant_id:
        return "med"
    _, rows = run_query(
        "SELECT risk_tier FROM merchants WHERE id=%s",
        (merchant_id,),
    )
    if not rows or rows[0]["risk_tier"] is None:
        return "med"
    tier = str(rows[0]["risk_tier"]).strip().lower()
    if tier in {"low", "med", "high"}:
        return tier
    return "med"


def _severity_for_threshold(
    amount: float,
    threshold: float,
    risk_tier: str,
) -> str:
    """
    Risk-tier aware severity for amount spikes:
      - LOW-risk merchant: high severity if amount >= threshold
      - MED-risk merchant: med for modest spikes, high for very large
      - HIGH-risk merchant: low for modest, med for very large
    """
    tier = (risk_tier or "med").lower()
    if tier == "low":
        # Low-risk category with a big amount is suspicious
        return "high"
    if tier == "med":
        return "high" if amount >= threshold * 2 else "med"
    if tier == "high":
        return "med" if amount >= threshold * 3 else "low"
    return "med"


def _severity_for_spike_vs_avg(
    amount: float,
    avg: float,
    risk_tier: str,
) -> str:
    """
    Severity for SPIKE_VS_ROLLING_AVG alerts.
    """
    tier = (risk_tier or "med").lower()
    ratio = amount / avg if avg > 0 else 0.0
    if tier == "low":
        return "high" if ratio >= 2.0 else "med"
    if tier == "med":
        return "high" if ratio >= 3.0 else "med"
    if tier == "high":
        return "med" if ratio >= 4.0 else "low"
    return "med"


# ------------------------ Velocity & DB-based rules ------------------------

def run_db_rules(transaction_id: int) -> None:
    """
    Call the Postgres rule functions that you defined in schema.sql
    on the new transaction. Best-effort: errors are ignored.
    Currently:
      - rule_new_device(txn_id)
      - rule_velocity_3in2min(txn_id)
    """
    for fn in ("rule_new_device", "rule_velocity_3in2min"):
        try:
            run_query(f"SELECT {fn}(%s);", (transaction_id,))
        except Exception:
            # best-effort: don't break transaction flow if rule function fails
            pass


# ------------------------ Main insert_transaction ------------------------

def insert_transaction(
    account_id: int,
    merchant_id: Optional[int],
    device_id: Optional[int],
    amount: float,
    currency: str,
    status: str,
    ts_iso: Optional[str],
    direction: str = "debit",
) -> int:

    """
    Insert a transaction, run alert rules, and return the new transaction id.

    Rules:
      1) Threshold rule (THRESHOLD_EXCEEDED) — risk-tier aware
      2) Spike vs rolling average (SPIKE_VS_ROLLING_AVG) — risk-tier aware
      3) DB-backed velocity + new-device rules via rule_velocity_3in2min / rule_new_device
    """
    ts = ts_iso or datetime.utcnow().isoformat()
    status_norm = (status or "approved").lower()
    direction_norm = (direction or "debit").lower()
    if direction_norm not in ("debit", "credit"):
        direction_norm = "debit"

    # Insert transaction
    _, rows = run_query(
        """
        INSERT INTO transactions (
          account_id, merchant_id, device_id,
          amount, currency, status, ts, direction
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            account_id,
            merchant_id,
            device_id,
            amount,
            currency,
            status_norm,
            ts,
            direction_norm,
        ),
    )

    tx_id = rows[0]["id"]

    # Update running balance on the account:
    # debit  → subtract, credit → add
    balance_delta = amount if direction_norm == "credit" else -amount
    run_query(
        """
        UPDATE accounts
        SET balance = COALESCE(balance, 0) + %s
        WHERE id = %s
        """,
        (balance_delta, account_id),
    )


    # Fetch per-account rule settings
    rule = get_alert_rule_for_account(account_id)
    thr = float(rule["amount_threshold"])
    mult = float(rule["spike_multiplier"])
    lb = int(rule["lookback_days"])

    # Risk tier based on merchant
    risk_tier = _merchant_risk_tier(merchant_id)

    # 1) Threshold rule (Python-side)
    if amount >= thr:
        sev = _severity_for_threshold(amount, thr, risk_tier)
        create_alert(
            transaction_id=tx_id,
            rule_code="THRESHOLD_EXCEEDED",
            severity=sev,
            status="open",
        )

    # 2) Rolling-average spike rule (Python-side)
    avg_amt = rolling_avg_amount(account_id, lb)
    if avg_amt > 0 and amount >= (avg_amt * mult):
        sev = _severity_for_spike_vs_avg(amount, avg_amt, risk_tier)
        create_alert(
            transaction_id=tx_id,
            rule_code="SPIKE_VS_ROLLING_AVG",
            severity=sev,
            status="open",
        )

    # 3) DB-backed rules (velocity + new device, etc.)
    run_db_rules(tx_id)

    return tx_id
