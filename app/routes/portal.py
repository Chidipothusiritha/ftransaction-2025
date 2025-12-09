# app/routes/portal.py

from __future__ import annotations

import re
import csv
from io import StringIO
from typing import Optional, Dict, Any

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    session,
    Response,
    render_template,
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


# ------------------------ Landing ------------------------

@portal_bp.get("/", endpoint="home")
def home():
    return redirect(url_for("portal.start_page"))


@portal_bp.get("/start", endpoint="start_page")
def start_page():
    return redirect(url_for("portal.auth_login"))


# ------------------------ Auth: Login (NEW DESIGN) ------------------------

@portal_bp.get("/auth/login", endpoint="auth_login")
def auth_login():
    if not auth_table_exists():
        flash("Auth table (customer_auth) not found.")
    return render_template("ftms_login.html")


@portal_bp.post("/auth/login", endpoint="auth_do_login")
def auth_do_login():
    try:
        if not auth_table_exists():
            flash("Auth table (customer_auth) not found.")
            return redirect(url_for("portal.auth_login"))

        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""

        _, rows = run_query(
            "SELECT ca.customer_id, ca.password_hash FROM customer_auth ca WHERE LOWER(ca.email)=LOWER(%s)",
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

        session["customer_id"] = row["customer_id"]

        try:
            device_id = ensure_portal_device(row["customer_id"])
            session["device_id"] = device_id
        except Exception:
            pass

        run_query(
            "UPDATE customer_auth SET last_login_ts=NOW() WHERE customer_id=%s",
            (row["customer_id"],),
        )
        flash("Signed in successfully!")
        return redirect(url_for("portal.portal_home"))

    except Exception as e:
        flash(f"Login error: {e}")
        return redirect(url_for("portal.auth_login"))


# ------------------------ Auth: Signup ------------------------

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
            flash("Auth table (customer_auth) not found.")
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

        _, existing = run_query(
            "SELECT id FROM customers WHERE LOWER(email)=LOWER(%s)", (email,)
        )
        
        if existing:
            customer_id = existing[0]["id"]
        else:
            _, rid = run_query(
                "INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW()) RETURNING id",
                (name or email.split("@")[0], email),
            )
            customer_id = rid[0]["id"]
            
            # Create CHECKING account with $10,000 initial balance
            run_query(
                "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) VALUES (%s,%s,%s,%s,NOW())",
                (customer_id, 'CHECKING', 'ACTIVE', 10000.00)
            )
            
            # Create SAVINGS account with $0 initial balance
            run_query(
                "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) VALUES (%s,%s,%s,%s,NOW())",
                (customer_id, 'SAVINGS', 'ACTIVE', 0.00)
            )

        _, dupe = run_query("SELECT 1 FROM customer_auth WHERE email=%s", (email,))
        if dupe:
            flash("Email already registered. Please sign in.")
            return redirect(url_for("portal.auth_login"))

        from werkzeug.security import generate_password_hash

        run_query(
            "INSERT INTO customer_auth (customer_id, email, password_hash) VALUES (%s,%s,%s)",
            (customer_id, email, generate_password_hash(pw)),
        )

        session["customer_id"] = customer_id

        try:
            device_id = ensure_portal_device(customer_id)
            session["device_id"] = device_id
        except Exception:
            pass

        flash("Welcome! Account created with $10,000 starting balance.")
        return redirect(url_for("portal.portal_home"))
    except Exception as e:
        flash(f"Sign-up error: {e}")
        return redirect(url_for("portal.auth_signup"))


@portal_bp.get("/auth/logout", endpoint="auth_logout")
def auth_logout():
    session.pop("customer_id", None)
    session.pop("device_id", None)
    flash("User signed out.")
    return redirect(url_for("portal.auth_login"))


# ------------------------ User Portal Home (Overview Dashboard) ------------------------

@portal_bp.get("/portal", endpoint="portal_home")
@login_required
def portal_home():
    cid = current_customer_id()

    _, cust = run_query("SELECT id, name, email FROM customers WHERE id=%s", (cid,))
    customer: Dict[str, Any] = cust[0] if cust else {"name": "Customer", "email": ""}

    # Account balances & totals
    _, accounts = run_query(
        "SELECT id, account_type, balance FROM accounts WHERE customer_id=%s ORDER BY id",
        (cid,),
    )
    
    total_balance = sum(float(a["balance"]) for a in accounts)
    
    # Revenue (credits) and Savings calculation
    _, revenue_rows = run_query(
        """
        SELECT COALESCE(SUM(t.amount), 0)::float as total_revenue
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.customer_id = %s AND t.direction = 'credit' AND t.status = 'approved'
        """,
        (cid,),
    )
    total_revenue = revenue_rows[0]["total_revenue"] if revenue_rows else 0

    _, savings_rows = run_query(
        """
        SELECT COALESCE(SUM(balance), 0)::float as total_savings
        FROM accounts
        WHERE customer_id = %s AND account_type = 'SAVINGS'
        """,
        (cid,),
    )
    total_savings = savings_rows[0]["total_savings"] if savings_rows else 0

    # Spending chart data (last 30 days, grouped by day)
    _, spending_data = run_query(
        """
        SELECT DATE(t.ts) as day, SUM(t.amount)::float as total
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.customer_id = %s 
          AND t.direction = 'debit' 
          AND t.status = 'approved'
          AND t.ts >= NOW() - INTERVAL '30 days'
        GROUP BY DATE(t.ts)
        ORDER BY day DESC
        LIMIT 30
        """,
        (cid,),
    )
    
    # Spending by merchant risk tier
    _, risk_spending = run_query(
        """
        SELECT 
            COALESCE(m.risk_tier, 'UNKNOWN') as risk_tier,
            SUM(t.amount)::float as total
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        WHERE a.customer_id = %s 
          AND t.direction = 'debit' 
          AND t.status = 'approved'
          AND t.ts >= NOW() - INTERVAL '30 days'
        GROUP BY m.risk_tier
        ORDER BY total DESC
        """,
        (cid,),
    )

    # Recent transactions
    _, tx = run_query(
        """
        SELECT t.id, t.account_id, t.amount, t.currency, t.direction, t.status, t.ts,
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

    # Recent alerts
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

    content = """
    <div class="card p-4 mb-3" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
      <div>
        <h5 class="mb-1" style="opacity: 0.9;">FinGuard - User Portal</h5>
        <h3 class="card-title mb-1">Welcome, {{ customer.name }}</h3>
        <div style="opacity: 0.9;">{{ customer.email }}</div>
      </div>
    </div>

    <!-- Overview Cards -->
    <div class="row g-3 mb-4">
      <div class="col-md-4">
        <div class="card p-3 bg-primary text-white">
          <h6 class="mb-1">Available Balance</h6>
          <h3 class="mb-0">${{ "%.2f"|format(total_balance) }}</h3>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card p-3 bg-success text-white">
          <h6 class="mb-1">Total Revenue</h6>
          <h3 class="mb-0">${{ "%.2f"|format(total_revenue) }}</h3>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card p-3 bg-info text-white">
          <h6 class="mb-1">Total Savings</h6>
          <h3 class="mb-0">${{ "%.2f"|format(total_savings) }}</h3>
        </div>
      </div>
    </div>


    <!-- Quick Actions -->
    <div class="card p-3 mb-4">
      <h5 class="mb-3">Quick Actions</h5>
      <div class="row g-2">
        <div class="col-md-3">
          <a href="{{ url_for('portal.make_payment_page') }}" class="btn btn-primary w-100">Make Payment</a>
        </div>
        <div class="col-md-3">
          <a href="{{ url_for('portal.account_details') }}" class="btn btn-outline-primary w-100">Account Details</a>
        </div>
        <div class="col-md-3">
          <button class="btn btn-outline-secondary w-100" onclick="alert('Add Card feature coming soon!')">Add Card</button>
        </div>
        <div class="col-md-3">
          <button class="btn btn-outline-secondary w-100" onclick="alert('Add Device feature coming soon!')">Add Device</button>
        </div>
      </div>
    </div>

    <!-- Recent Transactions -->
    <div class="card p-3 mb-3">
      <h5 class="card-title">Recent Transactions</h5>
      <div class="table-wrap mt-2"><table class="table table-sm">
        <thead><tr><th>ID</th><th>Merchant</th><th>Amount</th><th>Type</th><th>Status</th><th>Date</th></tr></thead>
        <tbody>
          {% for r in tx %}
            <tr>
              <td>{{r.id}}</td>
              <td>{{r.merchant_name or 'â€”'}}</td>
              <td>{{r.amount}} {{r.currency}}</td>
              <td><span class="badge text-bg-{{ 'danger' if r.direction == 'debit' else 'success' }}">{{r.direction}}</span></td>
              <td>{{r.status}}</td>
              <td>{{r.ts}}</td>
            </tr>
          {% endfor %}
          {% if not tx %}<tr><td colspan="6" class="text-muted">No transactions yet.</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>

    <!-- Recent Alerts -->
    <div class="card p-3">
      <h5 class="card-title">Recent Alerts</h5>
      <div class="table-wrap mt-2"><table class="table table-sm">
        <thead><tr><th>ID</th><th>Rule</th><th>Severity</th><th>Amount</th><th>Time</th></tr></thead>
        <tbody>
          {% for a in alerts %}
            <tr><td>{{a.id}}</td><td>{{a.rule_code}}</td><td><span class="badge text-bg-{{ 'danger' if a.severity == 'high' else 'warning' if a.severity == 'medium' else 'secondary' }}">{{a.severity}}</span></td><td>{{a.amount}} {{a.currency}}</td><td>{{a.created_ts}}</td></tr>
          {% endfor %}
          {% if not alerts %}<tr><td colspan="5" class="text-muted">No alerts.</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>


    <!-- Spending by Risk Tier Pie Chart -->
    <div class="card p-3 mb-4">
      <h5 class="card-title">Spending by Risk Category (Last 30 Days)</h5>
      <div style="max-width: 400px; margin: 0 auto;">
        <canvas id="riskPieChart"></canvas>
      </div>
    </div>


    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script>
      // Pie chart for risk tier spending
      const ctxPie = document.getElementById('riskPieChart');
      const riskData = {{ risk_spending|tojson }};
      const hasData = riskData && riskData.length > 0;
      
      new Chart(ctxPie, {
        type: 'pie',
        data: {
          labels: hasData ? riskData.map(d => d.risk_tier) : ['No Data'],
          datasets: [{
            data: hasData ? riskData.map(d => d.total) : [1],
            backgroundColor: hasData ? [
              'rgba(75, 192, 192, 0.8)',   // LOW - Green
              'rgba(255, 206, 86, 0.8)',   // MEDIUM - Yellow
              'rgba(255, 99, 132, 0.8)',   // HIGH - Red
              'rgba(201, 203, 207, 0.8)'   // UNKNOWN - Gray
            ] : ['rgba(201, 203, 207, 0.3)'],
            borderColor: hasData ? [
              'rgba(75, 192, 192, 1)',
              'rgba(255, 206, 86, 1)',
              'rgba(255, 99, 132, 1)',
              'rgba(201, 203, 207, 1)'
            ] : ['rgba(201, 203, 207, 1)'],
            borderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: {
            legend: {
              position: 'bottom',
              labels: {
                padding: 15,
                font: {
                  size: 12
                }
              }
            }
          }
        }
      });
    </script>
    """
    return render_page(
        content,
        show_sidebar=False,
        customer=customer,
        total_balance=total_balance,
        total_revenue=total_revenue,
        total_savings=total_savings,
        spending_data=spending_data,
        risk_spending=risk_spending,
        tx=tx,
        alerts=alerts,
    )


# ------------------------ Account Details ------------------------

@portal_bp.get("/portal/account-details", endpoint="account_details")
@login_required
def account_details():
    cid = current_customer_id()
    
    _, cust = run_query("SELECT id, name, email FROM customers WHERE id=%s", (cid,))
    customer: Dict[str, Any] = cust[0] if cust else {"name": "Customer", "email": ""}
    
    _, accounts = run_query(
        "SELECT id, account_type, balance, status, opened_ts FROM accounts WHERE customer_id=%s ORDER BY id",
        (cid,),
    )
    
    _, devices = run_query(
        "SELECT id, fingerprint, label, first_seen_ts, last_seen_ts FROM devices WHERE customer_id=%s ORDER BY last_seen_ts DESC",
        (cid,),
    )
    
    content = """
    <div class="card p-4 mb-3" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
      <h5 class="mb-1" style="opacity: 0.9;">FinGuard - User Portal</h5>
      <h4 class="mb-0">Account Details - {{ customer.name }}</h4>
    </div>
    
    <div class="card p-4 mb-3">
      <h4 class="card-title mb-3">Customer Information</h4>
      <div class="row">
        <div class="col-md-4"><strong>ID:</strong> {{ customer.id }}</div>
        <div class="col-md-4"><strong>Name:</strong> {{ customer.name }}</div>
        <div class="col-md-4"><strong>Email:</strong> {{ customer.email }}</div>
      </div>
    </div>

    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="card-title mb-0">My Accounts</h4>
        {% if not accounts %}
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#createAccountModal">Create Account</button>
        {% endif %}
      </div>
      <div class="table-wrap"><table class="table table-striped">
        <thead>
          <tr><th>Account ID</th><th>Type</th><th>Balance</th><th>Status</th><th>Opened</th></tr>
        </thead>
        <tbody>
          {% for a in accounts %}
            <tr>
              <td>{{ a.id }}</td>
              <td><span class="badge text-bg-primary">{{ a.account_type }}</span></td>
              <td>${{ "%.2f"|format(a.balance) }}</td>
              <td><span class="badge text-bg-success">{{ a.status }}</span></td>
              <td>{{ a.opened_ts }}</td>
            </tr>
          {% endfor %}
          {% if not accounts %}<tr><td colspan="5" class="text-muted">No accounts found.</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>

    <div class="card p-4 mb-3">
      <h4 class="card-title mb-3">My Devices</h4>
      <div class="table-wrap"><table class="table table-striped">
        <thead>
          <tr><th>Device ID</th><th>Device Name</th><th>Fingerprint</th><th>First Seen</th><th>Last Seen</th></tr>
        </thead>
        <tbody>
          {% for d in devices %}
            <tr>
              <td>{{ d.id }}</td>
              <td>{{ d.label if d.label and d.label != 'Web Portal' else 'MacBook' }}</td>
              <td class="monospace">{{ d.fingerprint[:20] }}...</td>
              <td>{{ d.first_seen_ts }}</td>
              <td>{{ d.last_seen_ts }}</td>
            </tr>
          {% endfor %}
          {% if not devices %}<tr><td colspan="5" class="text-muted">No devices found.</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>

    <div class="card p-4">
      <h4 class="card-title mb-3">Cards</h4>
      <p class="text-muted">Card management coming soon!</p>
    </div>

    <div class="mt-3">
      <a href="{{ url_for('portal.portal_home') }}" class="btn btn-outline-secondary">Back to Portal</a>
    </div>

    <!-- Create Account Modal -->
    <div class="modal fade" id="createAccountModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Create New Account</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.create_account') }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Account Type</label>
                <select name="account_type" class="form-select" required>
                  <option value="">Select Type</option>
                  <option value="CHECKING">Checking</option>
                  <option value="SAVINGS">Savings</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Account Holder Name</label>
                <input type="text" name="holder_name" class="form-control" value="{{ customer.name }}" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Initial Balance</label>
                <input type="number" name="balance" step="0.01" min="0" class="form-control" value="0.00" required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Create Account</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    """
    return render_page(content, show_sidebar=False, customer=customer, accounts=accounts, devices=devices)


@portal_bp.post("/portal/create-account", endpoint="create_account")
@login_required
def create_account():
    cid = current_customer_id()
    try:
        account_type = request.form.get("account_type", "").upper()
        holder_name = request.form.get("holder_name", "").strip()
        balance = float(request.form.get("balance", 0))
        
        if account_type not in ["CHECKING", "SAVINGS"]:
            flash("Invalid account type.")
            return redirect(url_for("portal.account_details"))
        
        # Check if account type already exists for this customer
        _, existing = run_query(
            "SELECT id FROM accounts WHERE customer_id=%s AND account_type=%s",
            (cid, account_type)
        )
        
        if existing:
            flash(f"You already have a {account_type} account.")
            return redirect(url_for("portal.account_details"))
        
        # Create account
        run_query(
            "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) VALUES (%s,%s,%s,%s,NOW())",
            (cid, account_type, "ACTIVE", balance)
        )
        
        flash(f"{account_type} account created successfully with balance ${balance:.2f}")
        return redirect(url_for("portal.account_details"))
        
    except Exception as e:
        flash(f"Error creating account: {e}")
        return redirect(url_for("portal.account_details"))


# ------------------------ Make Payment ------------------------

@portal_bp.get("/portal/make-payment", endpoint="make_payment_page")
@login_required
def make_payment_page():
    cid = current_customer_id()
    
    _, cust = run_query("SELECT id, name, email FROM customers WHERE id=%s", (cid,))
    customer: Dict[str, Any] = cust[0] if cust else {"name": "Customer", "email": ""}
    
    _, accounts = run_query(
        "SELECT id, account_type, balance FROM accounts WHERE customer_id=%s ORDER BY id",
        (cid,),
    )

    _, merchants = run_query(
        "SELECT id, name FROM merchants ORDER BY name LIMIT 100"
    )
    
    _, devices = run_query(
        "SELECT id, label, fingerprint FROM devices WHERE customer_id=%s ORDER BY id",
        (cid,),
    )

    content = """
    <div class="card p-4 mb-3" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
      <h5 class="mb-1" style="opacity: 0.9;">FinGuard - User Portal</h5>
      <h4 class="mb-0">{{ customer.name }}</h4>
    </div>
    
    <div class="card p-4">
      <h3 class="card-title mb-3">Make a Payment</h3>
      <form method="post" action="{{ url_for('portal.create_portal_transaction') }}" class="row g-3">
        <div class="col-md-6">
          <label class="form-label">From Account</label>
          <select name="account_id" class="form-select" required>
            <option value="">Select Account</option>
            {% for a in accounts %}
              <option value="{{a.id}}">{{a.account_type}} - Balance: ${{a.balance}}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-6">
          <label class="form-label">To Merchant</label>
          <select name="merchant_id" class="form-select">
            <option value="">(Select merchant)</option>
            {% for m in merchants %}
              <option value="{{m.id}}">{{m.name}}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-md-4">
          <label class="form-label">Amount</label>
          <input name="amount" type="number" step="0.01" min="0.01" class="form-control" required>
        </div>
        <div class="col-md-4">
          <label class="form-label">Currency</label>
          <input name="currency" class="form-control" value="USD" readonly>
        </div>
        <div class="col-md-4">
          <label class="form-label">Payment Type</label>
          <select name="direction" class="form-select">
            <option value="debit">Debit</option>
            <option value="credit">Credit</option>
          </select>
        </div>
        <div class="col-md-12">
          <label class="form-label">Device</label>
          <select name="device_id" class="form-select">
            <option value="">Use current device</option>
            {% for d in devices %}
              <option value="{{d.id}}">{{d.label or d.fingerprint}}</option>
            {% endfor %}
          </select>
        </div>
        <div class="col-12 d-flex justify-content-end gap-2 mt-3">
          <a href="{{ url_for('portal.portal_home') }}" class="btn btn-outline-secondary">Cancel</a>
          <button class="btn btn-primary">Process Payment</button>
        </div>
      </form>
    </div>
    """
    return render_page(content, show_sidebar=False, customer=customer, accounts=accounts, merchants=merchants, devices=devices)


@portal_bp.post("/portal/transactions/create", endpoint="create_portal_transaction")
@login_required
def create_portal_transaction():
    cid = current_customer_id()
    try:
        account_id = int(request.form.get("account_id"))
        merchant_id_raw = request.form.get("merchant_id")
        device_id_raw = request.form.get("device_id")
        amount = float(request.form.get("amount"))
        currency = (request.form.get("currency") or "USD").upper()
        direction = (request.form.get("direction") or "debit").lower()
        status = "approved"

        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Invalid account selection.")
            return redirect(url_for("portal.make_payment_page"))

        merchant_id: Optional[int] = int(merchant_id_raw) if merchant_id_raw else None
        
        # Use selected device or current session device
        if device_id_raw:
            device_id: Optional[int] = int(device_id_raw)
        else:
            device_id = session.get("device_id")

        tx_id = insert_transaction(
            account_id=account_id,
            merchant_id=merchant_id,
            device_id=device_id,
            amount=amount,
            currency=currency,
            status=status,
            ts_iso=None,
            direction=direction,
        )
        flash(f"Transaction {tx_id} processed successfully!")
    except Exception as e:
        flash(f"Error: {e}")
        return redirect(url_for("portal.make_payment_page"))
    return redirect(url_for("portal.portal_home"))


# ------------------------ User Reports ------------------------

@portal_bp.get("/portal/reports", endpoint="user_reports")
@login_required
def user_reports():
    content = """
    <div class="card p-4">
      <h4 class="card-title mb-3">My Reports</h4>
      <div class="row g-3">
        <div class="col-md-6">
          <div class="card bg-light p-3">
            <h6>My Transactions</h6>
            <p class="small text-muted mb-2">Download all your transaction history</p>
            <a href="{{ url_for('portal.download_user_transactions') }}" class="btn btn-sm btn-primary">Download CSV</a>
          </div>
        </div>
        <div class="col-md-6">
          <div class="card bg-light p-3">
            <h6>My Alerts</h6>
            <p class="small text-muted mb-2">Download all alerts on your account</p>
            <a href="{{ url_for('portal.download_user_alerts') }}" class="btn btn-sm btn-primary">Download CSV</a>
          </div>
        </div>
      </div>
      <div class="mt-3">
        <a href="{{ url_for('portal.portal_home') }}" class="btn btn-outline-secondary">Back to Portal</a>
      </div>
    </div>
    """
    return render_page(content, show_sidebar=False)


@portal_bp.get("/portal/reports/transactions.csv")
@login_required
def download_user_transactions():
    cid = current_customer_id()
    _, rows = run_query(
        """
        SELECT t.id, t.account_id, t.amount, t.currency, t.direction, t.status, t.ts,
               m.name as merchant_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        WHERE a.customer_id = %s
        ORDER BY t.ts DESC
        """,
        (cid,),
    )
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'account_type', 'merchant_name', 
                                                  'amount', 'currency', 'direction', 'status', 'ts'])
    writer.writeheader()
    writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=my_transactions.csv"}
    )


@portal_bp.get("/portal/reports/alerts.csv")
@login_required
def download_user_alerts():
    cid = current_customer_id()
    _, rows = run_query(
        """
        SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
               t.amount, t.currency
        FROM alerts a
        JOIN transactions t ON t.id = a.transaction_id
        JOIN accounts acc ON acc.id = t.account_id
        WHERE acc.customer_id = %s
        ORDER BY a.created_ts DESC
        """,
        (cid,),
    )
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'transaction_id', 'rule_code', 
                                                  'severity', 'status', 'amount', 'currency', 'created_ts'])
    writer.writeheader()
    writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=my_alerts.csv"}
    )