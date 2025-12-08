# app/routes/portal.py

from __future__ import annotations

import re
from typing import Optional, Dict, Any

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from ..db import run_query
from ..ui import render_page
from ..services.alerts import insert_transaction
from ..services.devices import ensure_portal_device
from ..auth import auth_table_exists, login_required, current_customer_id

portal_bp = Blueprint("portal", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s or ""))


# ------------------------ Landing chooser ------------------------

@portal_bp.get("/", endpoint="home")
def home():
    return redirect(url_for("portal.start_page"))


@portal_bp.get("/start", endpoint="start_page")
def start_page():
    content = """
    <div class="row g-4">
      <div class="col-lg-6">
        <div class="card p-4">
          <h3 class="card-title mb-2">I’m an Admin</h3>
          <p class="text-muted">Manage customers, accounts, devices, transactions, and alerts.</p>
          <div class="d-flex gap-2 flex-wrap">
            {% if session.get('is_admin') %}
              <a class="btn btn-primary" href="{{ url_for('admin.transactions_page') }}">Go to Admin Dashboard</a>
              <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_logout') }}">Admin Logout</a>
            {% else %}
              <a class="btn btn-primary" href="{{ url_for('admin.admin_login') }}">Admin Login</a>
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
              <a class="btn btn-primary" href="{{ url_for('portal.portal_home') }}">Open My Portal</a>
              <a class="btn btn-outline-secondary" href="{{ url_for('portal.auth_logout') }}">User Logout</a>
            {% else %}
              <a class="btn btn-primary" href="{{ url_for('portal.auth_login') }}">User Login</a>
              <a class="btn btn-outline-primary" href="{{ url_for('portal.auth_signup') }}">User Sign up</a>
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
    # no sidebar on start page
    return render_page(content, show_sidebar=False)


# ------------------------ Auth: Signup / Login / Logout ------------------------

@portal_bp.get("/auth/signup", endpoint="auth_signup")
def auth_signup():
    if not auth_table_exists():
        flash("Auth table (customer_auth) not found. Add it to your schema to enable auth.")
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">Create your account</h3>
      <form method="post" action="{{ url_for('portal.auth_do_signup') }}" class="row g-3">
        <div class="col-md-6"><label class="form-label">Full name</label><input name="name" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Email</label><input name="email" type="email" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Password</label><input name="password" type="password" class="form-control" minlength="6" required></div>
        <div class="col-md-6"><label class="form-label">Confirm password</label><input name="password2" type="password" class="form-control" minlength="6" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign up</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('portal.auth_login') }}">I already have an account</a>
        </div>
      </form>
    </div>
    """
    return render_page(content, show_sidebar=False)


@portal_bp.post("/auth/signup", endpoint="auth_do_signup")
def auth_do_signup():
    try:
        if not auth_table_exists():
            flash("Auth table (customer_auth) not found. Add it to your schema.")
            return redirect(url_for("portal.auth_signup"))

        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""

        if not valid_email(email):
            flash("Please enter a valid email.")
            return redirect(url_for("portal.auth_signup"))
        if pw != pw2:
            flash("Passwords do not match.")
            return redirect(url_for("portal.auth_signup"))
        if len(pw) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(url_for("portal.auth_signup"))

        # ensure customer exists
        _, existing = run_query(
            "SELECT id FROM customers WHERE LOWER(email)=LOWER(%s)",
            (email,),
        )
        if existing:
            customer_id = existing[0]["id"]
        else:
            from werkzeug.security import generate_password_hash  # noqa: F401  (used for password hashing below)

            _, rid = run_query(
                "INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW()) RETURNING id",
                (name or email.split("@")[0], email),
            )
            customer_id = rid[0]["id"]

        # ensure not already registered in auth table
        _, dupe = run_query(
            "SELECT 1 FROM customer_auth WHERE email=%s",
            (email,),
        )
        if dupe:
            flash("Email already registered. Please sign in.")
            return redirect(url_for("portal.auth_login"))

        from werkzeug.security import generate_password_hash

        run_query(
            "INSERT INTO customer_auth (customer_id, email, password_hash) VALUES (%s,%s,%s)",
            (customer_id, email, generate_password_hash(pw)),
        )

        session["customer_id"] = customer_id

        # also create a portal device on signup (nice to have)
        try:
            device_id = ensure_portal_device(customer_id)
            session["device_id"] = device_id
        except Exception:
            pass

        flash("Welcome! Account created.")
        return redirect(url_for("portal.portal_home"))
    except Exception as e:
        flash(f"Sign-up error: {e}")
        return redirect(url_for("portal.auth_signup"))


@portal_bp.get("/auth/login", endpoint="auth_login")
def auth_login():
    if not auth_table_exists():
        flash("Auth table (customer_auth) not found. Add it to your schema to enable auth.")
    content = """
    <div class="card p-4">
      <h3 class="card-title mb-3">User Login</h3>
      <form method="post" action="{{ url_for('portal.auth_do_login') }}" class="row g-3" style="max-width:540px">
        <div class="col-12"><label class="form-label">Email</label><input name="email" type="email" class="form-control" required></div>
        <div class="col-12"><label class="form-label">Password</label><input name="password" type="password" class="form-control" required></div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary">Sign in</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('portal.auth_signup') }}">Create account</a>
        </div>
      </form>
    </div>
    """
    return render_page(content, show_sidebar=False)


@portal_bp.post("/auth/login", endpoint="auth_do_login")
def auth_do_login():
    try:
        if not auth_table_exists():
            flash("Auth table (customer_auth) not found.")
            return redirect(url_for("portal.auth_login"))

        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""

        _, rows = run_query(
            """
            SELECT ca.customer_id, ca.password_hash
            FROM customer_auth ca
            WHERE LOWER(ca.email)=LOWER(%s)
            """,
            (email,),
        )
        if not rows:
            flash("Invalid email or password.")
            return redirect(url_for("portal.auth_login"))

        row = rows[0]
        from werkzeug.security import check_password_hash

        if not check_password_hash(row["password_hash"], pw):
            flash("Invalid email or password.")
            return redirect(url_for("portal.auth_login"))

        # store logged-in customer
        session["customer_id"] = row["customer_id"]

        # Attach / create a portal device and stash its id in the session
        try:
            device_id = ensure_portal_device(row["customer_id"])
            session["device_id"] = device_id
        except Exception:
            # Don’t block login if device creation fails
            pass

        run_query(
            "UPDATE customer_auth SET last_login_ts=NOW() WHERE customer_id=%s",
            (row["customer_id"],),
        )
        flash("Signed in.")
        return redirect(url_for("portal.portal_home"))

    except Exception as e:
        flash(f"Login error: {e}")
        return redirect(url_for("portal.auth_login"))


@portal_bp.get("/auth/logout", endpoint="auth_logout")
def auth_logout():
    session.pop("customer_id", None)
    session.pop("device_id", None)
    flash("User signed out.")
    return redirect(url_for("portal.start_page"))


# ------------------------ User Portal ------------------------

@portal_bp.get("/portal", endpoint="portal_home")
@login_required
def portal_home():
    cid = current_customer_id()

    # basic customer info
    _, cust = run_query(
        "SELECT id, name, email FROM customers WHERE id=%s",
        (cid,),
    )
    customer: Dict[str, Any] = cust[0] if cust else {"name": "Customer", "email": ""}

    # user's transactions
    _, tx = run_query(
        """
      SELECT t.id, t.account_id, t.amount, t.currency, t.status, t.ts,
             m.name AS merchant_name
      FROM transactions t
      JOIN accounts a ON a.id=t.account_id
      LEFT JOIN merchants m ON m.id=t.merchant_id
      WHERE a.customer_id=%s
      ORDER BY t.ts DESC
      LIMIT 10
    """,
        (cid,),
    )

    # user's device logins
    _, devlogins = run_query(
        """
      SELECT de.id, de.device_id, de.ip_addr, de.user_agent, de.geo_city, de.geo_country,
             de.created_ts, d.label
      FROM device_events de
      JOIN devices d ON d.id=de.device_id
      WHERE d.customer_id=%s AND LOWER(de.event_type)='login'
      ORDER BY de.created_ts DESC
      LIMIT 10
    """,
        (cid,),
    )

    # user's alerts
    _, alerts = run_query(
        """
      SELECT a.id, a.rule_code, a.severity, a.created_ts, t.amount, t.currency
      FROM alerts a
      JOIN transactions t ON t.id=a.transaction_id
      JOIN accounts ac ON ac.id=t.account_id
      WHERE ac.customer_id=%s
      ORDER BY a.created_ts DESC
      LIMIT 10
    """,
        (cid,),
    )

    # accounts+merchants for "new transaction" form
    _, accounts = run_query(
        """
        SELECT id, account_type
        FROM accounts
        WHERE customer_id=%s
        ORDER BY id
        """,
        (cid,),
    )

    _, merchants = run_query(
        """
        SELECT id, name
        FROM merchants
        ORDER BY name
        LIMIT 100
        """
    )

    content = """
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center">
        <div>
          <h3 class="card-title mb-1">Welcome, {{ customer.name or 'Customer' }}</h3>
          <div class="text-muted">{{ customer.email }}</div>
        </div>
        <div><a class="btn btn-outline-secondary" href="{{ url_for('portal.auth_logout') }}">Log out</a></div>
      </div>
    </div>

    <div class="row g-3 mb-3">
      <div class="col-lg-6">
        <div class="card p-3">
          <h5 class="card-title mb-2">Create a New Transaction</h5>
          <p class="text-muted small mb-3">
            This will create a real transaction on your account and run the same alerts as the admin dashboard.
          </p>
          <form method="post" action="{{ url_for('portal.create_portal_transaction') }}" class="row g-2">
            <div class="col-md-6">
              <label class="form-label">Account</label>
              <select name="account_id" class="form-select" required>
                {% for a in accounts %}
                  <option value="{{a.id}}">Acct {{a.id}} — {{a.account_type}}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-6">
              <label class="form-label">Merchant</label>
              <select name="merchant_id" class="form-select">
                <option value="">(none)</option>
                {% for m in merchants %}
                  <option value="{{m.id}}">{{m.id}} — {{m.name}}</option>
                {% endfor %}
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label">Amount</label>
              <input name="amount" type="number" step="0.01" min="0.01" class="form-control" required>
            </div>
            <div class="col-md-4">
              <label class="form-label">Currency</label>
              <input name="currency" class="form-control" value="USD">
            </div>
            <div class="col-md-4">
              <label class="form-label">Status</label>
              <input name="status" class="form-control" value="approved">
            </div>
            <div class="col-12 d-flex justify-content-end mt-2">
              <button class="btn btn-primary">Create Transaction</button>
            </div>
          </form>
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
    </div>

    <div class="row g-3">
      <div class="col-lg-6">
        <div class="card p-3">
          <h5 class="card-title">Recent Transactions</h5>
          <div class="table-wrap mt-2"><table class="table table-sm">
            <thead><tr><th>id</th><th>account</th><th>merchant</th><th>amount</th><th>status</th><th>ts</th></tr></thead>
            <tbody>
              {% for r in tx %}
                <tr><td>{{r.id}}</td><td>{{r.account_id}}</td><td>{{r.merchant_name or '—'}}</td><td>{{r.amount}} {{r.currency}}</td><td>{{r.status}}</td><td>{{r.ts}}</td></tr>
              {% endfor %}
              {% if not tx %}<tr><td colspan="6" class="text-muted">No transactions yet.</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>

      <div class="col-lg-6">
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
    # show_sidebar=False here (portal is user-facing); admin sidebar is only on admin pages
    return render_page(
        content,
        show_sidebar=False,
        customer=customer,
        tx=tx,
        devlogins=devlogins,
        alerts=alerts,
        accounts=accounts,
        merchants=merchants,
    )


@portal_bp.post("/portal/transactions/create", endpoint="create_portal_transaction")
@login_required
def create_portal_transaction():
    """
    User-initiated transaction creation from the portal.
    Uses the same insert_transaction() helper as the admin side,
    so alerts are created in exactly the same way and appear on
    the admin dashboard.
    """
    cid = current_customer_id()
    try:
        account_id = int(request.form.get("account_id"))
        merchant_id_raw = request.form.get("merchant_id")
        amount = float(request.form.get("amount"))
        currency = (request.form.get("currency") or "USD").upper()
        status = (request.form.get("status") or "approved").lower()

        # Ensure the selected account belongs to the logged-in customer
        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Invalid account selection.")
            return redirect(url_for("portal.portal_home"))

        merchant_id: Optional[int] = int(merchant_id_raw) if merchant_id_raw else None

        # Use the portal device if we have one
        device_id = session.get("device_id")

        tx_id = insert_transaction(
            account_id=account_id,
            merchant_id=merchant_id,
            device_id=device_id,
            amount=amount,
            currency=currency,
            status=status,
            ts_iso=None,  # let DB default / now() handle ts
        )
        flash(f"Transaction {tx_id} created. Alerts evaluated.")
    except Exception as e:
        flash(f"Error creating transaction: {e}")
    return redirect(url_for("portal.portal_home"))
