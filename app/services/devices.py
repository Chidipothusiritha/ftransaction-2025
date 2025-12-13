# app/services/devices.py

from __future__ import annotations
from typing import Optional

from ..db import get_conn


def _get_or_create_device(
    customer_id: int,
    fingerprint: str,
    label: Optional[str] = None,
) -> int:
    """
    Use DB function get_or_create_device if available, otherwise fallback.
    """
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT get_or_create_device(%s, %s, %s);",
                (customer_id, fingerprint, label),
            )
            row = cur.fetchone()
            conn.commit()
            if row and row[0]:
                return int(row[0])
        except Exception:
            conn.rollback()

        # Fallback
        cur.execute(
            """
            SELECT id FROM devices
            WHERE customer_id = %s AND fingerprint = %s
            """,
            (customer_id, fingerprint),
        )
        row = cur.fetchone()
        if row:
            device_id = int(row[0])
            cur.execute(
                "UPDATE devices SET last_seen_ts = NOW() WHERE id = %s;",
                (device_id,),
            )
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
        device_id = int(cur.fetchone()[0])
        conn.commit()
        return device_id


def ensure_portal_device(customer_id: int) -> int:
    """
    Ensure there is a stable 'web portal' device for this customer.
    """
    fingerprint = f"web_portal_{customer_id}"
    label = "Web Portal"
    return _get_or_create_device(customer_id, fingerprint, label)