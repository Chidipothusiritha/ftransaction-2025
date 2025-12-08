# app/routes/admin.py

from __future__ import annotations

from typing import Any, Dict, Sequence

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from ..db import run_query, table_exists, table_columns
from ..ui import render_page
from ..auth import ADMIN_USER, ADMIN_PASSWORD, is_admin
from ..services.alerts import insert_transaction

admin_bp = Blueprint("admin", __name__)

DEFAULT_LIMIT = 50


# ------------------------ Admin auth helpers ------------------------

def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def _inner(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin login required.")
            return redirect(url_for("admin.admin_login"))
        return fn(*args, **kwargs)

    return _inner


# ------------------------ Admin login/logout ------------------------

@admin_bp.get("/admin/login", endpoint="admin_login")
def admin_login():
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">Admin Login</h3>
      <form method="post" action="{{ url_for('admin.admin_do_login') }}" class="row g-3" style="max-width:540px">
        <div class="col-12"><label class="form-label">Username</label><input name="username" class="form-control" required></div>
        <div class="col-12"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign in</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('portal.start_page') }}">Back</a>
        </div>
        <div class="form-text mt-2">Set <code>ADMIN_USER</code> and <code>ADMIN_PASSWORD</code> in your <code>.env</code>.</div>
      </form>
    </div>
    """
    return render_page(content, show_sidebar=False)


@admin_bp.post("/admin/login", endpoint="admin_do_login")
def admin_do_login():
    user = (request.form.get("username") or "").strip()
    pw = request.form.get("password") or ""
    if user == ADMIN_USER and pw == ADMIN_PASSWORD:
        session["is_admin"] = True
        flash("Welcome, admin.")
        return redirect(url_for("admin.transactions_page"))
    flash("Invalid admin credentials.")
    return redirect(url_for("admin.admin_login"))


@admin_bp.get("/admin/logout", endpoint="admin_logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.")
    return redirect(url_for("portal.start_page"))


# ------------------------ Customers ------------------------

@admin_bp.get("/customers", endpoint="customers_page")
@admin_required
def customers_page():
    _, rows = run_query(
        """
        SELECT id, name, email, signup_ts
        FROM customers
        ORDER BY id DESC
        LIMIT %s
        """,
        (DEFAULT_LIMIT,),
    )
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-2">Create Customer</h4>
        <form method="post" action="{{ url_for('admin.create_customer') }}" class="row g-2">
          <div class="col-md-4"><label class="form-label">Name</label><input name="name" class="form-control" required></div>
          <div class="col-md-4"><label class="form-label">Email</label><input name="email" type="email" class="form-control" required></div>
          <div class="col-md-4 d-flex align-items-end"><button class="btn btn-primary w-100">Create</button></div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Customers</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>name</th><th>email</th><th>signup_ts</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.name}}</td><td>{{r.email}}</td><td>{{r.signup_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="4" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows)


@admin_bp.post("/customers/create", endpoint="create_customer")
@admin_required
def create_customer():
    try:
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        run_query(
            "INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW())",
            (name, email),
        )
        flash("Customer created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.customers_page"))


# ------------------------ Accounts ------------------------

@admin_bp.get("/accounts", endpoint="accounts_page")
@admin_required
def accounts_page():
    _, rows = run_query(
        """
        SELECT a.id, a.customer_id, a.account_type, a.status, a.opened_ts,
               c.name AS customer_name
        FROM accounts a
        LEFT JOIN customers c ON c.id=a.customer_id
        ORDER BY a.id DESC
        LIMIT %s
    """,
        (DEFAULT_LIMIT,),
    )
    _, customers = run_query(
        "SELECT id, name FROM customers ORDER BY id DESC LIMIT 200"
    )
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Create Account</h4>
        <form method="post" action="{{ url_for('admin.create_account') }}" class="row g-2">
          <div class="col-md-3">
            <label class="form-label">Customer</label>
            <select name="customer_id" class="form-select" required>
              {% for c in customers %}<option value="{{c.id}}">{{c.id}} — {{c.name}}</option>{% endfor %}
            </select>
          </div>
          <div class="col-md-3"><label class="form-label">Type</label><input name="account_type" class="form-control" value="CHECKING"></div>
          <div class="col-md-3"><label class="form-label">Status</label><input name="status" class="form-control" value="ACTIVE"></div>
          <div class="col-md-3 d-flex align-items-end"><button class="btn btn-primary w-100">Create</button></div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Accounts</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>customer</th><th>type</th><th>status</th><th>opened_ts</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.customer_id}} — {{r.customer_name}}</td><td>{{r.account_type}}</td><td>{{r.status}}</td><td>{{r.opened_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="5" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, customers=customers)


@admin_bp.post("/accounts/create", endpoint="create_account")
@admin_required
def create_account():
    try:
        cid = int(request.form.get("customer_id"))
        acc_type = (request.form.get("account_type") or "CHECKING").upper()
        status = (request.form.get("status") or "ACTIVE").upper()
        run_query(
            """
            INSERT INTO accounts (customer_id, account_type, status, opened_ts)
            VALUES (%s,%s,%s,NOW())
        """,
            (cid, acc_type, status),
        )
        flash("Account created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.accounts_page"))


# ------------------------ Merchants ------------------------

@admin_bp.get("/merchants", endpoint="merchants_page")
@admin_required
def merchants_page():
    _, rows = run_query(
        "SELECT id, name, category, risk_tier FROM merchants ORDER BY id DESC LIMIT %s",
        (DEFAULT_LIMIT,),
    )
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Create Merchant</h4>
        <form method="post" action="{{ url_for('admin.create_merchant') }}" class="row g-2">
          <div class="col-md-4"><label class="form-label">Name</label><input name="name" class="form-control" required></div>
          <div class="col-md-4"><label class="form-label">Category</label><input name="category" class="form-control" placeholder="grocery, travel, ..."></div>
          <div class="col-md-3"><label class="form-label">Risk Tier</label><input name="risk_tier" class="form-control" value="LOW"></div>
          <div class="col-md-1 d-flex align-items-end"><button class="btn btn-primary w-100">Create</button></div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Merchants</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>name</th><th>category</th><th>risk_tier</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.name}}</td><td>{{r.category}}</td><td>{{r.risk_tier}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="4" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows)


@admin_bp.post("/merchants/create", endpoint="create_merchant")
@admin_required
def create_merchant():
    try:
        name = (request.form.get("name") or "").strip()
        category = (request.form.get("category") or "").strip()
        risk = (request.form.get("risk_tier") or "LOW").upper()
        run_query(
            "INSERT INTO merchants (name, category, risk_tier) VALUES (%s,%s,%s)",
            (name, category, risk),
        )
        flash("Merchant created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.merchants_page"))


# ------------------------ Devices ------------------------

@admin_bp.get("/devices", endpoint="devices_page")
@admin_required
def devices_page():
    _, rows = run_query(
        """
        SELECT d.id, d.customer_id, c.name AS customer_name, d.fingerprint, d.label, d.first_seen_ts, d.last_seen_ts
        FROM devices d
        LEFT JOIN customers c ON c.id=d.customer_id
        ORDER BY d.last_seen_ts DESC NULLS LAST, d.id DESC
        LIMIT %s
    """,
        (DEFAULT_LIMIT,),
    )
    _, customers = run_query(
        "SELECT id, name FROM customers ORDER BY id DESC LIMIT 200"
    )
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Register Device</h4>
        <form method="post" action="{{ url_for('admin.create_device') }}" class="row g-2">
          <div class="col-md-3">
            <label class="form-label">Customer</label>
            <select name="customer_id" class="form-select">
              <option value="">(none)</option>
              {% for c in customers %}<option value="{{c.id}}">{{c.id}} — {{c.name}}</option>{% endfor %}
            </select>
          </div>
          <div class="col-md-5"><label class="form-label">Fingerprint</label><input name="fingerprint" class="form-control" required></div>
          <div class="col-md-3"><label class="form-label">Label</label><input name="label" class="form-control" placeholder="iPhone 15, Chrome, ..."></div>
          <div class="col-md-1 d-flex align-items-end"><button class="btn btn-primary w-100">Add</button></div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Devices</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>customer</th><th>fingerprint</th><th>label</th><th>first_seen</th><th>last_seen</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.customer_id}} — {{r.customer_name}}</td><td class="monospace">{{r.fingerprint}}</td><td>{{r.label}}</td><td>{{r.first_seen_ts}}</td><td>{{r.last_seen_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="6" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, customers=customers)


@admin_bp.post("/devices/create", endpoint="create_device")
@admin_required
def create_device():
    try:
        customer_id = request.form.get("customer_id")
        fingerprint = (request.form.get("fingerprint") or "").strip()
        label = (request.form.get("label") or "").strip()
        run_query(
            """
            INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
            VALUES (%s,%s,%s,NOW(),NOW())
        """,
            (int(customer_id) if customer_id else None, fingerprint, label),
        )
        flash("Device registered.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.devices_page"))


# ------------------------ Device Events ------------------------

@admin_bp.get("/device-events", endpoint="device_events_page")
@admin_required
def device_events_page():
    _, rows = run_query(
        """
        SELECT de.id, de.device_id, de.event_type, de.ip_addr, de.user_agent,
               de.geo_city, de.geo_country, de.created_ts
        FROM device_events de
        ORDER BY de.created_ts DESC
        LIMIT %s
    """,
        (DEFAULT_LIMIT,),
    )
    _, devices = run_query(
        "SELECT id, label FROM devices ORDER BY id DESC LIMIT 200"
    )
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Record Device Event</h4>
        <form method="post" action="{{ url_for('admin.create_device_event') }}" class="row g-2">
          <div class="col-md-3">
            <label class="form-label">Device</label>
            <select name="device_id" class="form-select" required>
              {% for d in devices %}<option value="{{d.id}}">{{d.id}} — {{d.label or 'device'}}</option>{% endfor %}
            </select>
          </div>
          <div class="col-md-3"><label class="form-label">Event Type</label><input name="event_type" class="form-control" value="login"></div>
          <div class="col-md-3"><label class="form-label">IP</label><input name="ip_addr" class="form-control" placeholder="1.2.3.4"></div>
          <div class="col-md-3"><label class="form-label">User Agent</label><input name="user_agent" class="form-control"></div>
          <div class="col-md-3"><label class="form-label">City</label><input name="geo_city" class="form-control"></div>
          <div class="col-md-3"><label class="form-label">Country</label><input name="geo_country" maxlength="2" class="form-control" placeholder="US"></div>
          <div class="col-md-3 d-flex align-items-end"><button class="btn btn-primary w-100">Add Event</button></div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Device Events</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>device_id</th><th>type</th><th>ip</th><th>ua</th><th>city</th><th>country</th><th>created</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.device_id}}</td><td>{{r.event_type}}</td><td>{{r.ip_addr}}</td><td class="monospace">{{r.user_agent}}</td><td>{{r.geo_city}}</td><td>{{r.geo_country}}</td><td>{{r.created_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="8" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, devices=devices)


@admin_bp.post("/device-events/create", endpoint="create_device_event")
@admin_required
def create_device_event():
    try:
        device_id = int(request.form.get("device_id"))
        event_type = (request.form.get("event_type") or "login").strip()
        ip = (request.form.get("ip_addr") or "").strip()
        ua = (request.form.get("user_agent") or "").strip()
        city = (request.form.get("geo_city") or "").strip()
        cc = (request.form.get("geo_country") or "").upper().strip()[:2]
        run_query(
            """
            INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country, created_ts)
            VALUES (%s,%s,%s,%s,%s,%s,NOW())
        """,
            (device_id, event_type, ip, ua, city, cc),
        )
        flash("Device event recorded.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.device_events_page"))


# ------------------------ Transactions (with suspicious flag) ------------------------

@admin_bp.get("/transactions", endpoint="transactions_page")
@admin_required
def transactions_page():
    # suspicious = TRUE if there is at least one open alert for this transaction
    _, tx = run_query(
        """
        SELECT
          t.id,
          t.account_id,
          t.merchant_id,
          t.device_id,
          t.amount,
          t.currency,
          t.status,
          t.ts,
          CASE
            WHEN EXISTS (
              SELECT 1
              FROM alerts a
              WHERE a.transaction_id = t.id
                AND a.status = 'open'
            )
            THEN TRUE
            ELSE FALSE
          END AS suspicious
        FROM transactions t
        ORDER BY t.ts DESC
        LIMIT %s
    """,
        (DEFAULT_LIMIT,),
    )

    content = """
    <div class="row g-3">
      <div class="col-12 col-xl-7">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="card-title mb-3">Add Transaction</h4>
            <form method="post" action="{{ url_for('admin.create_transaction') }}" class="row g-2">
              <div class="col-md-4"><label class="form-label">Account ID</label><input name="account_id" type="number" class="form-control" required></div>
              <div class="col-md-4"><label class="form-label">Merchant ID</label><input name="merchant_id" type="number" class="form-control"></div>
              <div class="col-md-4"><label class="form-label">Device ID</label><input name="device_id" type="number" class="form-control"></div>
              <div class="col-md-4"><label class="form-label">Amount</label><input name="amount" type="number" step="0.01" class="form-control" required></div>
              <div class="col-md-4"><label class="form-label">Currency</label><input name="currency" class="form-control" value="USD"></div>
              <div class="col-md-4"><label class="form-label">Status</label><input name="status" class="form-control" value="approved"></div>
              <div class="col-md-6"><label class="form-label">Timestamp</label><input name="ts" type="datetime-local" class="form-control"></div>
              <div class="col-md-6 d-flex align-items-end"><button class="btn btn-primary w-100">Create &amp; Check Alerts</button></div>
            </form>
          </div>
        </div>
      </div>

      <div class="col-12 col-xl-5">
        <div class="alert alert-info small">
          Use this form to simulate transactions from different accounts, devices, and merchants.
          Alerts (amount spikes, velocity, new device, risk tiers, etc.) will be raised automatically
          and can be reviewed on the <a href="{{ url_for('admin.alerts_page') }}">Alerts</a> tab.
        </div>
      </div>
    </div>

    <div class="card shadow-sm mt-3">
      <div class="card-body">
        <h5 class="card-title">Recent Transactions</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead>
            <tr>
              <th>id</th>
              <th>account_id</th>
              <th>merchant_id</th>
              <th>device_id</th>
              <th>amount</th>
              <th>currency</th>
              <th>status</th>
              <th>suspicious</th>
              <th>ts</th>
            </tr>
          </thead>
          <tbody>
            {% for r in tx %}
              <tr>
                <td>{{r.id}}</td>
                <td>{{r.account_id}}</td>
                <td>{{r.merchant_id}}</td>
                <td>{{r.device_id}}</td>
                <td>{{r.amount}}</td>
                <td>{{r.currency}}</td>
                <td>{{r.status}}</td>
                <td>
                  {% if r.suspicious %}
                    <span class="badge text-bg-danger">Yes</span>
                  {% else %}
                    <span class="badge text-bg-secondary">No</span>
                  {% endif %}
                </td>
                <td>{{r.ts}}</td>
              </tr>
            {% endfor %}
            {% if not tx %}<tr><td colspan="9" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody>
        </table></div>
      </div>
    </div>
    """
    return render_page(content, tx=tx)


@admin_bp.post("/transactions/create", endpoint="create_transaction")
@admin_required
def create_transaction():
    try:
        aid = int(request.form.get("account_id"))
        mid = request.form.get("merchant_id")
        did = request.form.get("device_id")
        amount = float(request.form.get("amount"))
        currency = (request.form.get("currency") or "USD").upper()
        status = (request.form.get("status") or "approved").lower()
        ts = request.form.get("ts")
        tx_id = insert_transaction(
            account_id=aid,
            merchant_id=int(mid) if mid else None,
            device_id=int(did) if did else None,
            amount=amount,
            currency=currency,
            status=status,
            ts_iso=ts,
        )
        flash(f"Transaction {tx_id} created. Rules evaluated.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.transactions_page"))


# ------------------------ Alerts (with Resolve button) ------------------------

@admin_bp.get("/alerts", endpoint="alerts_page")
@admin_required
def alerts_page():
    """
    Show only OPEN alerts, with a Resolve button for each.
    Resolved alerts will not appear here anymore.
    """
    _, rows = run_query(
        """
        SELECT
          a.id,
          a.transaction_id,
          a.rule_code,
          a.severity,
          a.status,
          a.created_ts,
          t.amount,
          t.currency,
          c.name AS customer_name
        FROM alerts a
        JOIN transactions t ON t.id = a.transaction_id
        JOIN accounts acc ON acc.id = t.account_id
        JOIN customers c ON c.id = acc.customer_id
        WHERE a.status = 'open'
        ORDER BY a.created_ts DESC
        LIMIT %s
        """,
        (DEFAULT_LIMIT,),
    )

    content = """
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">Open Alerts</h4>
        <p class="text-muted small mb-3">
          These alerts are currently <strong>open</strong>. Click <em>Resolve</em> on an alert
          once it has been investigated. Resolved alerts will disappear from this list.
        </p>
        <div class="table-wrap"><table class="table table-sm table-striped align-middle">
          <thead>
            <tr>
              <th>id</th>
              <th>transaction</th>
              <th>customer</th>
              <th>rule</th>
              <th>severity</th>
              <th>amount</th>
              <th>status</th>
              <th>created</th>
              <th>action</th>
            </tr>
          </thead>
          <tbody>
            {% for a in rows %}
              <tr>
                <td>{{a.id}}</td>
                <td>#{{a.transaction_id}}</td>
                <td>{{a.customer_name}}</td>
                <td><code>{{a.rule_code}}</code></td>
                <td>
                  {% if a.severity == 'high' %}
                    <span class="badge text-bg-danger">{{a.severity}}</span>
                  {% elif a.severity == 'medium' %}
                    <span class="badge text-bg-warning text-dark">{{a.severity}}</span>
                  {% else %}
                    <span class="badge text-bg-secondary">{{a.severity}}</span>
                  {% endif %}
                </td>
                <td>{{a.amount}} {{a.currency}}</td>
                <td>{{a.status}}</td>
                <td>{{a.created_ts}}</td>
                <td>
                  <form method="post" action="{{ url_for('admin.resolve_alert') }}" class="d-inline">
                    <input type="hidden" name="alert_id" value="{{a.id}}">
                    <button class="btn btn-sm btn-outline-success">Resolve</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not rows %}
              <tr><td colspan="9" class="text-muted">No open alerts 🎉</td></tr>
            {% endif %}
          </tbody>
        </table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows)


@admin_bp.post("/alerts/resolve", endpoint="resolve_alert")
@admin_required
def resolve_alert():
    """
    Mark a single alert as resolved and redirect back to the Alerts page.
    Because alerts_page only shows status='open', it will disappear from the table.
    """
    try:
        alert_id_raw = request.form.get("alert_id")
        alert_id = int(alert_id_raw)
        run_query(
            "UPDATE alerts SET status='resolved' WHERE id=%s",
            (alert_id,),
        )
        flash(f"Alert {alert_id} resolved.")
    except Exception as e:
        flash(f"Error resolving alert: {e}")
    return redirect(url_for("admin.alerts_page"))
