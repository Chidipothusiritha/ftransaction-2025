# app/routes/api.py

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..db import run_query

api_bp = Blueprint("api", __name__)


# ------------------------ Alerts feed (widget) ------------------------

@api_bp.get("/api/alerts")
def api_alerts():
    """
    JSON feed of recent OPEN alerts for the dashboard widget.
    """
    limit = int(request.args.get("limit", "12"))
    _, rows = run_query(
        """
        SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
               t.account_id, t.amount
        FROM alerts a
        JOIN transactions t ON t.id=a.transaction_id
        WHERE a.status = 'open'
        ORDER BY a.created_ts DESC
        LIMIT %s
        """,
        (limit,),
    )
    return jsonify(rows)


# ------------------------ Optional: transaction feeds ------------------------

@api_bp.get("/api/transactions")
def api_transactions():
    """
    Simple JSON list of recent transactions.
    """
    limit = int(request.args.get("limit", "50"))
    _, rows = run_query(
        """
        SELECT id, account_id, merchant_id, device_id, amount, currency, status, ts
        FROM transactions
        ORDER BY ts DESC
        LIMIT %s
        """,
        (limit,),
    )
    return jsonify(rows)


@api_bp.get("/api/transaction/<int:txn_id>")
def api_transaction_detail(txn_id: int):
    """
    Joined view of a single transaction with customer/merchant/device info.
    """
    _, rows = run_query(
        """
        SELECT t.*,
               c.id AS customer_id, c.name AS customer_name, c.email,
               a.account_type,
               m.name AS merchant_name,
               d.label AS device_label
        FROM transactions t
        JOIN accounts a   ON a.id = t.account_id
        JOIN customers c  ON c.id = a.customer_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        LEFT JOIN devices d   ON d.id = t.device_id
        WHERE t.id = %s
        """,
        (txn_id,),
    )
    if not rows:
        return jsonify({"error": "not found"}), 404
    return jsonify(rows[0])
