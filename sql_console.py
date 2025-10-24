# sql_console.py — Admin + User portals, landing chooser, CRUD UI, alerts
import os
import re
from typing import List, Tuple, Optional, Dict, Any, Sequence
from datetime import datetime

from flask import (
    Flask, request, render_template_string, redirect,
    url_for, flash, jsonify, session
)
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# ------------------------ Config ------------------------
MAX_ROWS = 500
DEFAULT_LIMIT = 50

# Per-account alert defaults (used if alert_rules not present)
DEFAULT_THRESHOLD = float(os.getenv("DEFAULT_THRESHOLD", "200.0"))
DEFAULT_SPIKE_MULTIPLIER = float(os.getenv("DEFAULT_SPIKE_MULTIPLIER", "2.5"))
DEFAULT_LOOKBACK_DAYS = int(os.getenv("DEFAULT_LOOKBACK_DAYS", "30"))

# Admin auth via environment (no DB table)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # change in .env!

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

# ------------------------ DB helpers ------------------------
def get_conn():
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "frauddb"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        row_factory=dict_row,
    )

def run_query(sql: str, params: tuple = ()) -> Tuple[List[str], List[dict]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchmany(MAX_ROWS) if cur.description else []
        cols = list(rows[0].keys()) if rows else ([d.name for d in cur.description] if cur.description else [])
        return cols, rows

def table_exists(schema: str, table: str) -> bool:
    _, rows = run_query("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema=%s AND table_name=%s
    """, (schema, table))
    return bool(rows)

def table_columns(schema: str, table: str) -> Sequence[str]:
    _, rows = run_query("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
    """, (schema, table))
    return [r["column_name"] for r in rows]

# ------------------------ Auth helpers ------------------------
def is_admin() -> bool:
    return bool(session.get("is_admin"))

def auth_table_exists() -> bool:
    return table_exists("public", "customer_auth")

def current_customer_id() -> Optional[int]:
    return session.get("customer_id")

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def _inner(*args, **kwargs):
        if not current_customer_id():
            flash("Please sign in.")
            return redirect(url_for("auth_login"))
        return fn(*args, **kwargs)
    return _inner

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s or ""))

# ------------------------ Alert + Notification helpers ------------------------
def get_alert_rule_for_account(account_id: Optional[int]) -> Dict[str, Any]:
    if account_id is None or not table_exists("public", "alert_rules"):
        return {
            "amount_threshold": DEFAULT_THRESHOLD,
            "spike_multiplier": DEFAULT_SPIKE_MULTIPLIER,
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
        }
    _, rows = run_query("""
        SELECT amount_threshold::float AS amount_threshold,
               spike_multiplier::float  AS spike_multiplier,
               lookback_days::int       AS lookback_days
        FROM alert_rules WHERE account_id=%s
    """, (account_id,))
    if rows:
        return rows[0]
    _, defrows = run_query("""
        SELECT amount_threshold::float AS amount_threshold,
               spike_multiplier::float  AS spike_multiplier,
               lookback_days::int       AS lookback_days
        FROM alert_rules WHERE account_id IS NULL
    """)
    if defrows:
        return defrows[0]
    return {
        "amount_threshold": DEFAULT_THRESHOLD,
        "spike_multiplier": DEFAULT_SPIKE_MULTIPLIER,
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
    }

def rolling_avg_amount(account_id: int, lookback_days: int) -> float:
    _, rows = run_query("""
        SELECT COALESCE(AVG(amount),0)::float AS avg_amt
        FROM transactions
        WHERE account_id=%s AND ts >= NOW() - INTERVAL %s
    """, (account_id, f"{lookback_days} days"))
    return float(rows[0]["avg_amt"]) if rows else 0.0

def notifications_mode() -> Optional[str]:
    """Return 'simple' (transaction_id/message/created_ts/delivered) or
       'channels' (alert_id/channel/status/sent_ts/payload), else None."""
    if not table_exists("public", "notifications"):
        return None
    cols = set(table_columns("public", "notifications"))
    if {"transaction_id", "message", "created_ts", "delivered"}.issubset(cols):
        return "simple"
    if {"alert_id", "channel", "status", "sent_ts", "payload"}.issubset(cols):
        return "channels"
    return None

def create_alert(transaction_id: int, rule_code: str, severity: str = "HIGH", status: str = "OPEN"):
    run_query("""
        INSERT INTO alerts (transaction_id, rule_code, severity, status, created_ts)
        VALUES (%s,%s,%s,%s,NOW())
    """, (transaction_id, rule_code, severity, status))

    mode = notifications_mode()
    if mode == "simple":
        msg = f"Alert {rule_code} triggered for transaction {transaction_id}"
        run_query("""
            INSERT INTO notifications (transaction_id, message, created_ts, delivered)
            VALUES (%s,%s,NOW(),FALSE)
        """, (transaction_id, msg))
    elif mode == "channels":
        _, aid_row = run_query("SELECT id FROM alerts WHERE transaction_id=%s ORDER BY id DESC LIMIT 1", (transaction_id,))
        if aid_row:
            run_query("""
                INSERT INTO notifications (alert_id, channel, status, sent_ts, payload)
                VALUES (%s,'ui','PENDING',NOW(), jsonb_build_object('message', %s))
            """, (aid_row[0]["id"], f"Alert {rule_code} for txn {transaction_id}"))

def insert_transaction(account_id: int,
                       merchant_id: Optional[int],
                       device_id: Optional[int],
                       amount: float,
                       currency: str,
                       status: str,
                       ts_iso: Optional[str]) -> int:
    ts = ts_iso or datetime.utcnow().isoformat()
    _, rows = run_query("""
        INSERT INTO transactions (account_id, merchant_id, device_id, amount, currency, status, ts)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (account_id, merchant_id, device_id, amount, currency, status, ts))
    tx_id = rows[0]["id"]

    rule = get_alert_rule_for_account(account_id)
    thr = float(rule["amount_threshold"])
    mult = float(rule["spike_multiplier"])
    lb = int(rule["lookback_days"])

    if amount >= thr:
        create_alert(tx_id, "THRESHOLD_EXCEEDED", severity="CRITICAL")

    avg_amt = rolling_avg_amount(account_id, lb)
    if avg_amt > 0 and amount >= (avg_amt * mult):
        create_alert(tx_id, "SPIKE_VS_ROLLING_AVG", severity="HIGH")

    return tx_id

# ------------------------ Base template + renderer ------------------------
BASE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FT Admin · Transaction Monitor</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background:#f7f8fb; }
    .navbar-brand { letter-spacing:.3px; }
    .card { border:0; border-radius:16px; box-shadow: 0 4px 18px rgba(0,0,0,.06); }
    .card-title { font-weight:600; }
    .table thead th { position: sticky; top: 0; background: #fff; z-index: 1; }
    .table-wrap { max-height: 60vh; overflow:auto; border:1px solid #eef0f4; border-radius: 12px; }
    .monospace { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .sidebar .list-group-item { border:0; border-radius:10px; }
    .sidebar .list-group-item.active { background:#0d6efd; }
  </style>
</head>
<body>
<nav class="navbar navbar-dark navbar-expand-lg" style="background:#0a2a56;">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('start_page') }}">FT Admin</a>
    <div class="d-flex gap-2">
      <a class="btn btn-sm btn-outline-light" href="{{ url_for('start_page') }}">Home</a>

      {% if is_admin() %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('transactions_page') }}">Admin Dashboard</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin_logout') }}">Admin Logout</a>
      {% else %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin_login') }}">Admin Login</a>
      {% endif %}

      {% if session.get('customer_id') %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal_home') }}">My Portal</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('auth_logout') }}">User Logout</a>
      {% else %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('auth_login') }}">User Login</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('auth_signup') }}">User Sign up</a>
      {% endif %}
    </div>
  </div>
</nav>

<div class="container-fluid py-4">
  <div class="row g-4">
    {% if is_admin() %}
      <aside class="col-12 col-lg-3">
        <div class="card p-3 sidebar">
          <div class="list-group">
            <a class="list-group-item list-group-item-action" href="{{ url_for('customers_page') }}">Customers</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('accounts_page') }}">Accounts</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('merchants_page') }}">Merchants</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('devices_page') }}">Devices</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('device_events_page') }}">Device Events</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('transactions_page') }}">Transactions</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('alerts_page') }}">Alerts</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('notifications_page') }}">Notifications</a>
          </div>
        </div>
      </aside>
      <main class="col-12 col-lg-9">
    {% else %}
      <main class="col-12">
    {% endif %}

      {% with msgs = get_flashed_messages() %}
        {% if msgs %}<div class="alert alert-info">{{ msgs[0] }}</div>{% endif %}
      {% endwith %}
      {{ content|safe }}
      </main>
  </div>
</div>
</body>
</html>
"""

from flask import render_template_string
app.jinja_env.globals["is_admin"] = is_admin  # available in all templates

def render_page(content_tpl: str, **ctx):
    """Render inner content first, then inject HTML into BASE."""
    inner = render_template_string(content_tpl, **ctx)
    return render_template_string(BASE, content=inner)

# ------------------------ Landing chooser ------------------------
@app.get("/")
def home():
    return redirect(url_for("start_page"))

@app.get("/start")
def start_page():
    content = """
    <div class="row g-4">
      <div class="col-lg-6">
        <div class="card p-4">
          <h3 class="card-title mb-2">I’m an Admin</h3>
          <p class="text-muted">Manage customers, accounts, devices, transactions, and alerts.</p>
          <div class="d-flex gap-2 flex-wrap">
            {% if is_admin() %}
              <a class="btn btn-primary" href="{{ url_for('transactions_page') }}">Go to Admin Dashboard</a>
              <a class="btn btn-outline-secondary" href="{{ url_for('admin_logout') }}">Admin Logout</a>
            {% else %}
              <a class="btn btn-primary" href="{{ url_for('admin_login') }}">Admin Login</a>
            {% endif %}
          </div>
          <hr class="my-3">
          <div class="small text-muted">
            Admin credentials come from environment: <code>ADMIN_USER</code>/<code>ADMIN_PASSWORD</code>.
          </div>
        </div>
      </div>

      <div class="col-lg-6">
        <div class="card p-4">
          <h3 class="card-title mb-2">I’m a User</h3>
          <p class="text-muted">View my transactions, device logins, and alerts.</p>
          <div class="d-flex gap-2 flex-wrap">
            {% if session.get('customer_id') %}
              <a class="btn btn-primary" href="{{ url_for('portal_home') }}">Open My Portal</a>
              <a class="btn btn-outline-secondary" href="{{ url_for('auth_logout') }}">User Logout</a>
            {% else %}
              <a class="btn btn-primary" href="{{ url_for('auth_login') }}">User Login</a>
              <a class="btn btn-outline-primary" href="{{ url_for('auth_signup') }}">User Sign up</a>
            {% endif %}
          </div>
          <hr class="my-3">
          <div class="small text-muted">
            User signup/login uses the <code>customer_auth</code> table.
          </div>
        </div>
      </div>
    </div>
    """
    return render_page(content)

# ------------------------ Admin login/logout (env-based) ------------------------
@app.get("/admin/login")
def admin_login():
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">Admin Login</h3>
      <form method="post" action="{{ url_for('admin_do_login') }}" class="row g-3" style="max-width:540px">
        <div class="col-12"><label class="form-label">Username</label><input name="username" class="form-control" required></div>
        <div class="col-12"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign in</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('start_page') }}">Back</a>
        </div>
        <div class="form-text mt-2">Set <code>ADMIN_USER</code> and <code>ADMIN_PASSWORD</code> in your <code>.env</code>.</div>
      </form>
    </div>
    """
    return render_page(content)

@app.post("/admin/login")
def admin_do_login():
    user = (request.form.get("username") or "").strip()
    pw = request.form.get("password") or ""
    if user == ADMIN_USER and pw == ADMIN_PASSWORD:
        session["is_admin"] = True
        flash("Welcome, admin.")
        return redirect(url_for("transactions_page"))
    flash("Invalid admin credentials.")
    return redirect(url_for("admin_login"))

@app.get("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.")
    return redirect(url_for("start_page"))

# ------------------------ Admin: Customers ------------------------
@app.get("/customers")
def customers_page():
    _, rows = run_query("""
        SELECT id, name, email, signup_ts
        FROM customers
        ORDER BY id DESC
        LIMIT %s
    """, (DEFAULT_LIMIT,))
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Create Customer</h4>
        <form method="post" action="{{ url_for('create_customer') }}" class="row g-2">
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

@app.post("/customers/create")
def create_customer():
    try:
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        run_query("INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW())", (name, email))
        flash("Customer created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("customers_page"))

# ------------------------ Admin: Accounts ------------------------
@app.get("/accounts")
def accounts_page():
    _, rows = run_query("""
        SELECT a.id, a.customer_id, a.account_type, a.status, a.opened_ts,
               c.name AS customer_name
        FROM accounts a
        LEFT JOIN customers c ON c.id=a.customer_id
        ORDER BY a.id DESC
        LIMIT %s
    """, (DEFAULT_LIMIT,))
    _, customers = run_query("SELECT id, name FROM customers ORDER BY id DESC LIMIT 200")
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Create Account</h4>
        <form method="post" action="{{ url_for('create_account') }}" class="row g-2">
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

@app.post("/accounts/create")
def create_account():
    try:
        cid = int(request.form.get("customer_id"))
        acc_type = (request.form.get("account_type") or "CHECKING").upper()
        status = (request.form.get("status") or "ACTIVE").upper()
        run_query("""
            INSERT INTO accounts (customer_id, account_type, status, opened_ts)
            VALUES (%s,%s,%s,NOW())
        """, (cid, acc_type, status))
        flash("Account created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("accounts_page"))

# ------------------------ Admin: Merchants ------------------------
@app.get("/merchants")
def merchants_page():
    _, rows = run_query("SELECT id, name, category, risk_tier FROM merchants ORDER BY id DESC LIMIT %s", (DEFAULT_LIMIT,))
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Create Merchant</h4>
        <form method="post" action="{{ url_for('create_merchant') }}" class="row g-2">
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

@app.post("/merchants/create")
def create_merchant():
    try:
        name = (request.form.get("name") or "").strip()
        category = (request.form.get("category") or "").strip()
        risk = (request.form.get("risk_tier") or "LOW").upper()
        run_query("INSERT INTO merchants (name, category, risk_tier) VALUES (%s,%s,%s)", (name, category, risk))
        flash("Merchant created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("merchants_page"))

# ------------------------ Admin: Devices ------------------------
@app.get("/devices")
def devices_page():
    _, rows = run_query("""
        SELECT d.id, d.customer_id, c.name AS customer_name, d.fingerprint, d.label, d.first_seen_ts, d.last_seen_ts
        FROM devices d
        LEFT JOIN customers c ON c.id=d.customer_id
        ORDER BY d.last_seen_ts DESC NULLS LAST, d.id DESC
        LIMIT %s
    """, (DEFAULT_LIMIT,))
    _, customers = run_query("SELECT id, name FROM customers ORDER BY id DESC LIMIT 200")
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Register Device</h4>
        <form method="post" action="{{ url_for('create_device') }}" class="row g-2">
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

@app.post("/devices/create")
def create_device():
    try:
        customer_id = request.form.get("customer_id")
        fingerprint = (request.form.get("fingerprint") or "").strip()
        label = (request.form.get("label") or "").strip()
        run_query("""
            INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
            VALUES (%s,%s,%s,NOW(),NOW())
        """, (int(customer_id) if customer_id else None, fingerprint, label))
        flash("Device registered.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("devices_page"))

# ------------------------ Admin: Device Events ------------------------
@app.get("/device-events")
def device_events_page():
    _, rows = run_query("""
        SELECT de.id, de.device_id, de.event_type, de.ip_addr, de.user_agent,
               de.geo_city, de.geo_country, de.created_ts
        FROM device_events de
        ORDER BY de.created_ts DESC
        LIMIT %s
    """, (DEFAULT_LIMIT,))
    _, devices = run_query("SELECT id, label FROM devices ORDER BY id DESC LIMIT 200")
    content = """
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-3">Record Device Event</h4>
        <form method="post" action="{{ url_for('create_device_event') }}" class="row g-2">
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

@app.post("/device-events/create")
def create_device_event():
    try:
        device_id = int(request.form.get("device_id"))
        event_type = (request.form.get("event_type") or "login").strip()
        ip = (request.form.get("ip_addr") or "").strip()
        ua = (request.form.get("user_agent") or "").strip()
        city = (request.form.get("geo_city") or "").strip()
        cc = (request.form.get("geo_country") or "").upper().strip()[:2]
        run_query("""
            INSERT INTO device_events (device_id, event_type, ip_addr, user_agent, geo_city, geo_country, created_ts)
            VALUES (%s,%s,%s,%s,%s,%s,NOW())
        """, (device_id, event_type, ip, ua, city, cc))
        flash("Device event recorded.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("device_events_page"))

# ------------------------ Admin: Transactions (+ rules + alerts widget) ------------------------
@app.get("/transactions")
def transactions_page():
    _, tx = run_query("""
        SELECT id, account_id, merchant_id, device_id, amount, currency, status, ts
        FROM transactions
        ORDER BY ts DESC
        LIMIT %s
    """, (DEFAULT_LIMIT,))
    content = """
    <div class="row g-3">
      <div class="col-12 col-xl-7">
        <div class="card shadow-sm">
          <div class="card-body">
            <h4 class="card-title mb-3">Add Transaction</h4>
            <form method="post" action="{{ url_for('create_transaction') }}" class="row g-2">
              <div class="col-md-4"><label class="form-label">Account ID</label><input name="account_id" type="number" class="form-control" required></div>
              <div class="col-md-4"><label class="form-label">Merchant ID</label><input name="merchant_id" type="number" class="form-control"></div>
              <div class="col-md-4"><label class="form-label">Device ID</label><input name="device_id" type="number" class="form-control"></div>
              <div class="col-md-4"><label class="form-label">Amount</label><input name="amount" type="number" step="0.01" class="form-control" required></div>
              <div class="col-md-4"><label class="form-label">Currency</label><input name="currency" class="form-control" value="USD"></div>
              <div class="col-md-4"><label class="form-label">Status</label><input name="status" class="form-control" value="APPROVED"></div>
              <div class="col-md-6"><label class="form-label">Timestamp</label><input name="ts" type="datetime-local" class="form-control"></div>
              <div class="col-md-6 d-flex align-items-end"><button class="btn btn-primary w-100">Create & Check Alerts</button></div>
            </form>
          </div>
        </div>
      </div>
      <div class="col-12 col-xl-5">
        <div class="card shadow-sm mb-3">
          <div class="card-body">
            <h4 class="card-title mb-3">Per-Account Alert Rule</h4>
            <form method="post" action="{{ url_for('upsert_rule') }}" class="row g-2">
              <div class="col-12"><label class="form-label">Account ID</label><input name="account_id" type="number" class="form-control" required></div>
              <div class="col-6"><label class="form-label">Amount Threshold ($)</label><input name="amount_threshold" type="number" step="0.01" class="form-control" value="{{defaults.amount_threshold}}"></div>
              <div class="col-6"><label class="form-label">Spike × Avg</label><input name="spike_multiplier" type="number" step="0.1" class="form-control" value="{{defaults.spike_multiplier}}"></div>
              <div class="col-12"><label class="form-label">Lookback (days)</label><input name="lookback_days" type="number" class="form-control" value="{{defaults.lookback_days}}"></div>
              <div class="col-12 d-flex align-items-end"><button class="btn btn-success w-100">Save / Update Rule</button></div>
            </form>
          </div>
        </div>
        <div class="card shadow-sm">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-center">
              <h5 class="card-title mb-0">Recent Alerts</h5>
              <button id="refreshAlerts" class="btn btn-sm btn-outline-secondary">Refresh</button>
            </div>
            <div id="alertsBox" class="small mt-2"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="card shadow-sm mt-3">
      <div class="card-body">
        <h5 class="card-title">Recent Transactions</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>account_id</th><th>merchant_id</th><th>device_id</th><th>amount</th><th>currency</th><th>status</th><th>ts</th></tr></thead>
          <tbody>
            {% for r in tx %}<tr><td>{{r.id}}</td><td>{{r.account_id}}</td><td>{{r.merchant_id}}</td><td>{{r.device_id}}</td><td>{{r.amount}}</td><td>{{r.currency}}</td><td>{{r.status}}</td><td>{{r.ts}}</td></tr>{% endfor %}
            {% if not tx %}<tr><td colspan="8" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>

    <script>
      async function loadAlerts() {
        const box = document.getElementById('alertsBox');
        box.innerHTML = '<div class="text-muted">Loading…</div>';
        try {
          const res = await fetch('{{ url_for("api_alerts") }}?limit=12');
          const data = await res.json();
          if (!Array.isArray(data) || !data.length) {
            box.innerHTML = '<div class="text-muted">No alerts yet.</div>'; return;
          }
          box.innerHTML = data.map(a => `
            <div class="border rounded p-2 mb-2">
              <div class="d-flex justify-content-between">
                <span class="badge ${a.rule_code === 'THRESHOLD_EXCEEDED' ? 'text-bg-danger' : 'text-bg-warning'}">${a.rule_code}</span>
                <span class="text-muted">${new Date(a.created_ts).toLocaleString()}</span>
              </div>
              <div>Txn <b>${a.transaction_id}</b> • Acct <b>${a.account_id}</b> • $${Number(a.amount).toFixed(2)} • ${a.severity}</div>
            </div>
          `).join('');
        } catch(e) { box.innerHTML = '<div class="text-danger">Failed to load alerts.</div>'; }
      }
      document.getElementById('refreshAlerts').addEventListener('click', loadAlerts);
      loadAlerts(); setInterval(loadAlerts, 5000);
    </script>
    """
    defaults = {
        "amount_threshold": DEFAULT_THRESHOLD,
        "spike_multiplier": DEFAULT_SPIKE_MULTIPLIER,
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
    }
    return render_page(content, tx=tx, defaults=defaults)

@app.post("/transactions/create")
def create_transaction():
    try:
        aid = int(request.form.get("account_id"))
        mid = request.form.get("merchant_id")
        did = request.form.get("device_id")
        amount = float(request.form.get("amount"))
        currency = (request.form.get("currency") or "USD").upper()
        status = (request.form.get("status") or "APPROVED").upper()
        ts = request.form.get("ts")
        tx_id = insert_transaction(
            aid,
            int(mid) if mid else None,
            int(did) if did else None,
            amount, currency, status, ts
        )
        flash(f"Transaction {tx_id} created. Rules evaluated.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("transactions_page"))

@app.post("/rules/upsert")
def upsert_rule():
    if not table_exists("public", "alert_rules"):
        flash("alert_rules table not found—using environment defaults.")
        return redirect(url_for("transactions_page"))
    try:
        account_id = int(request.form.get("account_id"))
        thr = float(request.form.get("amount_threshold") or DEFAULT_THRESHOLD)
        mult = float(request.form.get("spike_multiplier") or DEFAULT_SPIKE_MULTIPLIER)
        lb = int(request.form.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
        run_query("""
          INSERT INTO alert_rules (account_id, amount_threshold, spike_multiplier, lookback_days, updated_ts)
          VALUES (%s,%s,%s,%s,NOW())
          ON CONFLICT (account_id) DO UPDATE SET
            amount_threshold=EXCLUDED.amount_threshold,
            spike_multiplier=EXCLUDED.spike_multiplier,
            lookback_days=EXCLUDED.lookback_days,
            updated_ts=NOW()
        """, (account_id, thr, mult, lb))
        flash("Alert rule saved.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("transactions_page"))

# ------------------------ Admin: Alerts / Notifications ------------------------
@app.get("/alerts")
def alerts_page():
    _, rows = run_query("""
      SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
             t.account_id, t.amount
      FROM alerts a
      JOIN transactions t ON t.id=a.transaction_id
      ORDER BY a.created_ts DESC
      LIMIT %s
    """, (DEFAULT_LIMIT,))
    content = """
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">Recent Alerts</h4>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>id</th><th>rule</th><th>severity</th><th>txn</th><th>account</th><th>amount</th><th>created</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.rule_code}}</td><td>{{r.severity}}</td><td>{{r.transaction_id}}</td><td>{{r.account_id}}</td><td>{{r.amount}}</td><td>{{r.created_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="7" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows)


def _notif_order_clause() -> str:
    if not table_exists("public", "notifications"):
        return "ORDER BY id DESC"
    cols = set(table_columns("public", "notifications"))
    if "sent_ts" in cols and "created_ts" in cols:
        return "ORDER BY COALESCE(sent_ts, created_ts) DESC NULLS LAST, id DESC"
    if "sent_ts" in cols:
        return "ORDER BY sent_ts DESC NULLS LAST, id DESC"
    if "created_ts" in cols:
        return "ORDER BY created_ts DESC NULLS LAST, id DESC"
    if "created_at" in cols:
        return "ORDER BY created_at DESC NULLS LAST, id DESC"
    return "ORDER BY id DESC"

@app.get("/notifications")
def notifications_page():
    if not table_exists("public", "notifications"):
        flash("notifications table not found.")
        return redirect(url_for("alerts_page"))

    order_clause = _notif_order_clause()
    sql = f"""
      SELECT *
      FROM notifications
      {order_clause}
      LIMIT %s
    """
    _, rows = run_query(sql, (DEFAULT_LIMIT,))
    headers = list(rows[0].keys()) if rows else []
    content = """
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">Notifications</h4>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr>{% for h in headers %}<th>{{h}}</th>{% endfor %}</tr></thead>
          <tbody>
            {% for r in rows %}<tr>{% for h in headers %}<td>{{ r[h] }}</td>{% endfor %}</tr>{% endfor %}
            {% if not rows %}<tr><td class="text-muted">None yet.</td></tr>{% endif %}
          </tbody>
        </table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, headers=headers)

# ------------------------ Alerts API for widget ------------------------
@app.get("/api/alerts")
def api_alerts():
    limit = int(request.args.get("limit", "12"))
    _, rows = run_query("""
      SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
             t.account_id, t.amount
      FROM alerts a
      JOIN transactions t ON t.id=a.transaction_id
      ORDER BY a.created_ts DESC
      LIMIT %s
    """, (limit,))
    return jsonify(rows)

# ======================== USER PORTAL ========================

# ---------- Auth: Signup / Login / Logout ----------
@app.get("/auth/signup")
def auth_signup():
    if not auth_table_exists():
        flash("Auth table (customer_auth) not found. Add it to your schema to enable auth.")
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">Create your account</h3>
      <form method="post" action="{{ url_for('auth_do_signup') }}" class="row g-3">
        <div class="col-md-6"><label class="form-label">Full name</label><input name="name" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Email</label><input name="email" type="email" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Password</label><input name="password" type="password" class="form-control" minlength="6" required></div>
        <div class="col-md-6"><label class="form-label">Confirm password</label><input name="password2" type="password" class="form-control" minlength="6" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign up</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('auth_login') }}">I already have an account</a>
        </div>
      </form>
    </div>
    """
    return render_page(content)

@app.post("/auth/signup")
def auth_do_signup():
    try:
        if not auth_table_exists():
            flash("Auth table (customer_auth) not found. Add it to your schema.")
            return redirect(url_for("auth_signup"))

        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""

        if not valid_email(email):
            flash("Please enter a valid email."); return redirect(url_for("auth_signup"))
        if pw != pw2:
            flash("Passwords do not match."); return redirect(url_for("auth_signup"))
        if len(pw) < 6:
            flash("Password must be at least 6 characters."); return redirect(url_for("auth_signup"))

        _, existing = run_query("SELECT id FROM customers WHERE LOWER(email)=LOWER(%s)", (email,))
        if existing:
            customer_id = existing[0]["id"]
        else:
            _, rid = run_query("INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW()) RETURNING id",
                               (name or email.split("@")[0], email))
            customer_id = rid[0]["id"]

        _, dupe = run_query("SELECT 1 FROM customer_auth WHERE email=%s", (email,))
        if dupe:
            flash("Email already registered. Please sign in."); return redirect(url_for("auth_login"))

        run_query("INSERT INTO customer_auth (customer_id, email, password_hash) VALUES (%s,%s,%s)",
                  (customer_id, email, generate_password_hash(pw)))

        session["customer_id"] = customer_id
        flash("Welcome! Account created.")
        return redirect(url_for("portal_home"))
    except Exception as e:
        flash(f"Sign-up error: {e}")
        return redirect(url_for("auth_signup"))

@app.get("/auth/login")
def auth_login():
    if not auth_table_exists():
        flash("Auth table (customer_auth) not found. Add it to your schema to enable auth.")
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">User Login</h3>
      <form method="post" action="{{ url_for('auth_do_login') }}" class="row g-3" style="max-width:540px">
        <div class="col-12"><label class="form-label">Email</label><input name="email" type="email" class="form-control" required></div>
        <div class="col-12"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign in</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('auth_signup') }}">Create account</a>
        </div>
      </form>
    </div>
    """
    return render_page(content)

@app.post("/auth/login")
def auth_do_login():
    try:
        if not auth_table_exists():
            flash("Auth table (customer_auth) not found.")
            return redirect(url_for("auth_login"))

        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""

        _, rows = run_query("""
            SELECT ca.customer_id, ca.password_hash
            FROM customer_auth ca
            WHERE LOWER(ca.email)=LOWER(%s)
        """, (email,))
        if not rows:
            flash("Invalid email or password."); return redirect(url_for("auth_login"))

        row = rows[0]
        if not check_password_hash(row["password_hash"], pw):
            flash("Invalid email or password."); return redirect(url_for("auth_login"))

        session["customer_id"] = row["customer_id"]
        run_query("UPDATE customer_auth SET last_login_ts=NOW() WHERE customer_id=%s", (row["customer_id"],))
        flash("Signed in.")
        return redirect(url_for("portal_home"))
    except Exception as e:
        flash(f"Login error: {e}")
        return redirect(url_for("auth_login"))

@app.get("/auth/logout")
def auth_logout():
    session.pop("customer_id", None)
    flash("User signed out.")
    return redirect(url_for("start_page"))

# ---------- User Portal ----------
@app.get("/portal")
@login_required
def portal_home():
    cid = current_customer_id()

    _, cust = run_query("SELECT id, name, email FROM customers WHERE id=%s", (cid,))
    customer = cust[0] if cust else {"name": "Customer", "email": ""}

    _, tx = run_query("""
      SELECT t.id, t.account_id, t.amount, t.currency, t.status, t.ts,
             m.name AS merchant_name
      FROM transactions t
      JOIN accounts a ON a.id=t.account_id
      LEFT JOIN merchants m ON m.id=t.merchant_id
      WHERE a.customer_id=%s
      ORDER BY t.ts DESC
      LIMIT 10
    """, (cid,))

    _, devlogins = run_query("""
      SELECT de.id, de.device_id, de.ip_addr, de.user_agent, de.geo_city, de.geo_country, de.created_ts,
             d.label
      FROM device_events de
      JOIN devices d ON d.id=de.device_id
      WHERE d.customer_id=%s AND LOWER(de.event_type)='login'
      ORDER BY de.created_ts DESC
      LIMIT 10
    """, (cid,))

    _, alerts = run_query("""
      SELECT a.id, a.rule_code, a.severity, a.created_ts, t.amount, t.currency
      FROM alerts a
      JOIN transactions t ON t.id=a.transaction_id
      JOIN accounts ac ON ac.id=t.account_id
      WHERE ac.customer_id=%s
      ORDER BY a.created_ts DESC
      LIMIT 10
    """, (cid,))

    content = """
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center">
        <div>
          <h3 class="card-title mb-1">Welcome, {{ customer.name or 'Customer' }}</h3>
          <div class="text-muted">{{ customer.email }}</div>
        </div>
        <div><a class="btn btn-outline-secondary" href="{{ url_for('auth_logout') }}">Log out</a></div>
      </div>
    </div>

    <div class="row g-3">
      <div class="col-lg-6">
        <div class="card p-3">
          <h5 class="card-title">Recent Transactions</h5>
          <div class="table-wrap mt-2"><table class="table table-sm">
            <thead><tr><th>id</th><th>merchant</th><th>amount</th><th>status</th><th>ts</th></tr></thead>
            <tbody>
              {% for r in tx %}
                <tr><td>{{r.id}}</td><td>{{r.merchant_name or '—'}}</td><td>{{r.amount}} {{r.currency}}</td><td>{{r.status}}</td><td>{{r.ts}}</td></tr>
              {% endfor %}
              {% if not tx %}<tr><td colspan="5" class="text-muted">No transactions yet.</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>
      <div class="col-lg-6">
        <div class="card p-3">
          <h5 class="card-title">Recent Device Logins</h5>
          <div class="table-wrap mt-2"><table class="table table-sm">
            <thead><tr><th>device</th><th>ip</th><th>city</th><th>country</th><th>time</th></tr></thead>
            <tbody>
              {% for r in devlogins %}
                <tr><td>{{r.label or r.device_id}}</td><td>{{r.ip_addr or '—'}}</td><td>{{r.geo_city or '—'}}</td><td>{{r.geo_country or '—'}}</td><td>{{r.created_ts}}</td></tr>
              {% endfor %}
              {% if not devlogins %}<tr><td colspan="5" class="text-muted">No logins recorded.</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>

      <div class="col-12">
        <div class="card p-3">
          <h5 class="card-title">Recent Alerts</h5>
          <div class="table-wrap mt-2"><table class="table table-sm">
            <thead><tr><th>id</th><th>rule</th><th>severity</th><th>amount</th><th>time</th></tr></thead>
            <tbody>
              {% for a in alerts %}
                <tr><td>{{a.id}}</td><td>{{a.rule_code}}</td><td>{{a.severity}}</td><td>{{a.amount}} {{a.currency}}</td><td>{{a.created_ts}}</td></tr>
              {% endfor %}
              {% if not alerts %}<tr><td colspan="5" class="text-muted">No alerts.</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>
    </div>
    """
    return render_page(content, customer=customer, tx=tx, devlogins=devlogins, alerts=alerts)

# ------------------------ Run ------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
