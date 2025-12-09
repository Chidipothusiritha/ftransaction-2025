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

from werkzeug.security import generate_password_hash, check_password_hash

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
    """Landing page with choice between admin and user login"""
    content = """
    <div style="min-height: 80vh; display: flex; align-items: center; justify-content: center;">
      <div class="card p-5" style="max-width: 600px;">
        <h2 class="text-center mb-4">FinGuard</h2>
        <p class="text-center text-muted mb-4">Financial Transaction Monitoring System</p>
        
        <div class="row g-3">
          <div class="col-md-6">
            <div class="card bg-light p-4 text-center h-100">
              <h5 class="mb-3">👤 User Portal</h5>
              <p class="small text-muted mb-3">Access your account, make payments, and view transactions</p>
              <a href="{{ url_for('portal.auth_login') }}" class="btn btn-primary w-100">User Login</a>
            </div>
          </div>
          <div class="col-md-6">
            <div class="card bg-light p-4 text-center h-100">
              <h5 class="mb-3">🛡️ Admin Portal</h5>
              <p class="small text-muted mb-3">Monitor alerts, manage customers, and view reports</p>
              <a href="{{ url_for('admin.admin_login') }}" class="btn btn-success w-100">Admin Login</a>
            </div>
          </div>
        </div>
      </div>
    </div>
    """
    return render_page(content, show_sidebar=False, is_landing=True)


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
    """
    User login with email + password only.
    PIN is used later as a step-up factor for suspicious transactions.
    """
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

        if not check_password_hash(row["password_hash"], pw):
            flash("Invalid email or password.")
            return redirect(url_for("portal.auth_login"))

        session["customer_id"] = row["customer_id"]

        # Ensure stable 'web portal' device
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
        <div class="col-md-6">
          <label class="form-label">Full name</label>
          <input name="name" class="form-control" required>
        </div>
        <div class="col-md-6">
          <label class="form-label">Email</label>
          <input name="email" type="email" class="form-control" required>
        </div>
        <div class="col-md-6">
          <label class="form-label">Password</label>
          <input name="password" type="password" class="form-control" minlength="6" required>
        </div>
        <div class="col-md-6">
          <label class="form-label">Confirm password</label>
          <input name="password2" type="password" class="form-control" minlength="6" required>
        </div>
        <div class="col-md-6">
          <label class="form-label">4-digit Security PIN</label>
          <input name="pin" type="password" class="form-control" pattern="\\d{4}" maxlength="4" required>
          <div class="form-text">We will ask for this PIN to confirm suspicious payments.</div>
        </div>
        <div class="col-md-6">
          <label class="form-label">Confirm PIN</label>
          <input name="pin2" type="password" class="form-control" pattern="\\d{4}" maxlength="4" required>
        </div>
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
        pin = (request.form.get("pin") or "").strip()
        pin2 = (request.form.get("pin2") or "").strip()

        if not valid_email(email):
            flash("Please enter a valid email.")
            return redirect(url_for("portal.auth_signup"))
        if pw != pw2:
            flash("Passwords do not match.")
            return redirect(url_for("portal.auth_signup"))
        if len(pw) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(url_for("portal.auth_signup"))
        if not (pin.isdigit() and len(pin) == 4 and pin == pin2):
            flash("PIN must be a 4-digit number and match in both fields.")
            return redirect(url_for("portal.auth_signup"))

        # existing customer or new
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

            # Default accounts on first signup
            run_query(
                "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) "
                "VALUES (%s,%s,%s,%s,NOW())",
                (customer_id, 'CHECKING', 'ACTIVE', 10000.00),
            )
            run_query(
                "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) "
                "VALUES (%s,%s,%s,%s,NOW())",
                (customer_id, 'SAVINGS', 'ACTIVE', 0.00),
            )

        # Ensure email not already registered in customer_auth
        _, dupe = run_query("SELECT 1 FROM customer_auth WHERE email=%s", (email,))
        if dupe:
            flash("Email already registered. Please sign in.")
            return redirect(url_for("portal.auth_login"))

        run_query(
            "INSERT INTO customer_auth (customer_id, email, password_hash, pin_hash) "
            "VALUES (%s,%s,%s,%s)",
            (customer_id, email, generate_password_hash(pw), generate_password_hash(pin)),
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


# ------------------------ Resolve User Alert ------------------------

@portal_bp.post("/portal/alerts/resolve", endpoint="resolve_user_alert")
@login_required
def resolve_user_alert():
    """Allow users to resolve their own alerts"""
    cid = current_customer_id()
    try:
        alert_id = int(request.form.get("alert_id"))
        
        # Verify this alert belongs to this customer
        _, rows = run_query(
            """
            SELECT a.id
            FROM alerts a
            JOIN transactions t ON t.id = a.transaction_id
            JOIN accounts acc ON acc.id = t.account_id
            WHERE a.id = %s AND acc.customer_id = %s
            """,
            (alert_id, cid)
        )
        
        if not rows:
            flash("Cannot resolve this alert.")
            return redirect(url_for("portal.portal_home"))
        
        run_query("UPDATE alerts SET status='cleared' WHERE id=%s", (alert_id,))
        flash("Alert resolved successfully.")
    except Exception as e:
        flash(f"Error resolving alert: {e}")
    
    return redirect(url_for("portal.portal_home"))


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

    # Revenue (credits) and savings
    _, revenue_rows = run_query(
        """
        SELECT COALESCE(SUM(t.amount), 0)::float as total_revenue
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.customer_id = %s AND t.direction = 'credit' AND t.status = 'approved'
        """,
        (cid,),
    )
    total_revenue = revenue_rows[0]["total_revenue"] if revenue_rows else 0.0

    _, savings_rows = run_query(
        """
        SELECT COALESCE(SUM(balance), 0)::float as total_savings
        FROM accounts
        WHERE customer_id = %s AND account_type = 'SAVINGS'
        """,
        (cid,),
    )
    total_savings = savings_rows[0]["total_savings"] if savings_rows else 0.0

    # Spending by merchant risk tier (last 30 days)
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

    # Recent transactions (all directions)
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

    # Pending suspicious tx for PIN modal
    pending_tx = None
    alert_type = None
    pending_tx_id = session.get("pending_tx_id")
    
    if pending_tx_id:
        _, rows = run_query(
            """
            SELECT t.id, t.amount, t.currency, t.ts,
                   m.name AS merchant,
                   a.rule_code AS alert_rule
            FROM transactions t
            LEFT JOIN merchants m ON m.id = t.merchant_id
            LEFT JOIN alerts a ON a.transaction_id = t.id
            WHERE t.id = %s
            ORDER BY a.created_ts DESC
            LIMIT 1
            """,
            (pending_tx_id,),
        )
        if rows:
            pending_tx = rows[0]
            alert_type = pending_tx.get('alert_rule', 'UNKNOWN')
        else:
            session.pop("pending_tx_id", None)

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
        <div class="col-md-6">
          <a href="{{ url_for('portal.make_payment_page') }}" class="btn btn-primary w-100">Make Payment</a>
        </div>
        <div class="col-md-6">
          <a href="{{ url_for('portal.account_details') }}" class="btn btn-outline-primary w-100">Account Details</a>
        </div>
      </div>
      {% if pending_tx %}
      <div class="alert alert-warning mt-3 mb-0">
        <strong>⚠️ Action Required:</strong> You have a suspicious transaction pending verification.
        <button type="button" class="btn btn-sm btn-warning ms-2" data-bs-toggle="modal" data-bs-target="#verifyTxModal">
          Verify Now
        </button>
      </div>
      {% endif %}
    </div>

    <!-- Recent Transactions -->
    <div class="card p-3 mb-3">
      <h5 class="card-title">Recent Transactions</h5>
      <div class="table-wrap mt-2">
        <table class="table table-sm">
          <thead>
            <tr>
              <th>ID</th><th>Merchant</th><th>Amount</th><th>Type</th>
              <th>Status</th><th>Date</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {% for r in tx %}
              <tr>
                <td>{{r.id}}</td>
                <td>{{r.merchant_name or 'â€”'}}</td>
                <td>{{r.amount}} {{r.currency}}</td>
                <td>
                  <span class="badge text-bg-{{ 'danger' if r.direction == 'debit' else 'success' }}">
                    {{r.direction}}
                  </span>
                </td>
                <td>{{r.status}}</td>
                <td>{{r.ts}}</td>
                <td>
                  <form method="post" action="{{ url_for('portal.delete_portal_transaction') }}"
                        onsubmit="return confirm('Delete this transaction?');"
                        class="d-inline">
                    <input type="hidden" name="transaction_id" value="{{ r.id }}">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not tx %}
              <tr><td colspan="7" class="text-muted">No transactions yet.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Recent Alerts -->
    <div class="card p-3 mb-3">
      <h5 class="card-title">Recent Alerts</h5>
      <div class="table-wrap mt-2">
        <table class="table table-sm">
          <thead>
            <tr><th>ID</th><th>Rule</th><th>Severity</th><th>Amount</th><th>Time</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for a in alerts %}
              <tr>
                <td>{{a.id}}</td>
                <td>{{a.rule_code}}</td>
                <td>
                  <span class="badge text-bg-{{ 'danger' if a.severity == 'high' else 'warning' if a.severity == 'medium' else 'secondary' }}">
                    {{a.severity}}
                  </span>
                </td>
                <td>{{a.amount}} {{a.currency}}</td>
                <td>{{a.created_ts}}</td>
                <td>
                  <form method="post" action="{{ url_for('portal.resolve_user_alert') }}" class="d-inline">
                    <input type="hidden" name="alert_id" value="{{a.id}}">
                    <button class="btn btn-sm btn-outline-success">Resolve</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not alerts %}
              <tr><td colspan="6" class="text-muted">No alerts.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Spending by Risk Tier Pie Chart -->
    <div class="card p-3 mb-4">
      <h5 class="card-title">Spending by Risk Category (Last 30 Days)</h5>
      <div style="max-width: 400px; margin: 0 auto;">
        <canvas id="riskPieChart"></canvas>
      </div>
    </div>

    <!-- Suspicious Transaction PIN Modal -->
    <div class="modal fade" id="verifyTxModal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <form method="post" action="{{ url_for('portal.confirm_suspicious_tx') }}">
            <div class="modal-header bg-warning text-dark">
              <h5 class="modal-title">
                ⚠️ Suspicious Transaction Detected
              </h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <!-- Alert-specific message -->
              <div class="alert alert-warning mb-3">
                <strong>Security Alert:</strong>
                {% if alert_type == 'AMOUNT_THRESHOLD' or alert_type == 'SPIKE_VS_AVG' %}
                  This is a unusually high amount for your account. Did you authorize this transaction?
                {% elif alert_type == 'NEW_DEVICE' %}
                  This transaction was made from a new device we haven't seen before. Is this you?
                {% elif alert_type == 'VELOCITY_3_IN_2MIN' %}
                  We detected multiple rapid transactions on your account. Did you make all of these purchases?
                {% else %}
                  We detected unusual activity on your account. Please verify this transaction.
                {% endif %}
              </div>
              
              {% if pending_tx %}
                <div class="card mb-3" style="background: #f8f9fa; border-left: 4px solid #ffc107;">
                  <div class="card-body">
                    <h6 class="card-title mb-3">Transaction Details</h6>
                    <div class="row mb-2">
                      <div class="col-5 text-muted">Merchant:</div>
                      <div class="col-7"><strong>{{ pending_tx.merchant or 'Unknown' }}</strong></div>
                    </div>
                    <div class="row mb-2">
                      <div class="col-5 text-muted">Amount:</div>
                      <div class="col-7"><strong class="text-danger">${{ pending_tx.amount }} {{ pending_tx.currency }}</strong></div>
                    </div>
                    <div class="row">
                      <div class="col-5 text-muted">Time:</div>
                      <div class="col-7"><strong>{{ pending_tx.ts }}</strong></div>
                    </div>
                  </div>
                </div>
              {% endif %}
              
              <input type="hidden" name="tx_id" value="{{ pending_tx.id if pending_tx else '' }}">
              
              <div class="mb-3">
                <label class="form-label fw-bold">Enter your 4-digit Security PIN</label>
                <input type="password"
                       name="pin"
                       class="form-control form-control-lg text-center"
                       maxlength="4"
                       pattern="\\d{4}"
                       placeholder="••••"
                       style="letter-spacing: 10px; font-size: 24px;"
                       required
                       autofocus>
                <div class="form-text">This is the PIN you set during account creation</div>
              </div>
            </div>
            <div class="modal-footer">
              <button class="btn btn-success btn-lg flex-fill" name="action" value="approve">
                ✓ Approve Transaction
              </button>
              <button class="btn btn-danger btn-lg flex-fill" name="action" value="deny">
                ✗ Decline
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script>
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
              'rgba(75, 192, 192, 0.8)',
              'rgba(255, 206, 86, 0.8)',
              'rgba(255, 99, 132, 0.8)',
              'rgba(201, 203, 207, 0.8)'
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
              labels: { padding: 15, font: { size: 12 } }
            }
          }
        }
      });
    </script>

    <!-- Auto-show PIN modal if there is a pending suspicious tx -->
    <script>
      document.addEventListener('DOMContentLoaded', function() {
        {% if pending_tx %}
          console.log('Pending transaction detected:', {{ pending_tx.id if pending_tx else 'null' }});
          const modalElement = document.getElementById('verifyTxModal');
          if (modalElement) {
            const verifyModal = new bootstrap.Modal(modalElement, {
              backdrop: 'static',
              keyboard: false
            });
            verifyModal.show();
          } else {
            console.error('Modal element not found');
          }
        {% else %}
          console.log('No pending transaction');
        {% endif %}
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
        risk_spending=risk_spending,
        tx=tx,
        alerts=alerts,
        pending_tx=pending_tx,
        alert_type=alert_type,
    )


# ------------------------ Account Details ------------------------

@portal_bp.get("/portal/account-details", endpoint="account_details")
@login_required
def account_details():
    cid = current_customer_id()

    _, cust = run_query("SELECT id, name, email FROM customers WHERE id=%s", (cid,))
    customer: Dict[str, Any] = cust[0] if cust else {"name": "Customer", "email": ""}

    _, accounts = run_query(
        "SELECT id, account_type, balance, status, opened_ts FROM accounts "
        "WHERE customer_id=%s ORDER BY id",
        (cid,),
    )

    _, devices = run_query(
        "SELECT id, fingerprint, label, first_seen_ts, last_seen_ts "
        "FROM devices WHERE customer_id=%s ORDER BY last_seen_ts DESC",
        (cid,),
    )

    # Cards (optional table)
    _, cards = run_query(
        """
        SELECT id, card_type, name_on_card, 
               RIGHT(card_number, 4) as last4,
               expiry_month, expiry_year, 
               '***' as cvv_mask,
               account_id
        FROM cards
        WHERE customer_id=%s
        ORDER BY id
        """,
        (cid,),
    )

    _, customer_accounts = run_query(
        "SELECT id, account_type FROM accounts WHERE customer_id=%s ORDER BY id",
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

    <!-- Accounts -->
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="card-title mb-0">My Accounts</h4>
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#createAccountModal">
          Create Account
        </button>
      </div>
      <div class="table-wrap">
        <table class="table table-striped">
          <thead>
            <tr><th>Account ID</th><th>Type</th><th>Balance</th><th>Opened</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for a in accounts %}
              <tr>
                <td>{{ a.id }}</td>
                <td><span class="badge text-bg-primary">{{ a.account_type }}</span></td>
                <td>${{ "%.2f"|format(a.balance) }}</td>
                <td>{{ a.opened_ts }}</td>
                <td>
                  <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#editAccountModal{{ a.id }}">Edit</button>
                  <form method="post" action="{{ url_for('portal.delete_account') }}"
                        class="d-inline" onsubmit="return confirm('Delete this account?');">
                    <input type="hidden" name="account_id" value="{{ a.id }}">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not accounts %}
              <tr><td colspan="5" class="text-muted">No accounts found.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Edit Account Modals -->
    {% for a in accounts %}
    <div class="modal fade" id="editAccountModal{{ a.id }}" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Edit Account #{{ a.id }}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.edit_account') }}">
            <input type="hidden" name="account_id" value="{{ a.id }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Balance</label>
                <input type="number" name="balance" step="0.01" class="form-control" value="{{ a.balance }}" required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Save Changes</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}
    <!-- Devices -->
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="card-title mb-0">My Devices</h4>
        <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addDeviceModal">
          Add Device
        </button>
      </div>
      <div class="table-wrap">
        <table class="table table-striped">
          <thead>
            <tr><th>Device ID</th><th>Device Name</th>
                <th>First Seen</th><th>Last Seen</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for d in devices %}
              <tr>
                <td>{{ d.id }}</td>
                <td>{{ d.label if d.label and d.label != 'Web Portal' else 'MacBook' }}</td>
                <td>{{ d.first_seen_ts }}</td>
                <td>{{ d.last_seen_ts }}</td>
                <td>
                  <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#editDeviceModal{{ d.id }}">Edit</button>
                  <form method="post" action="{{ url_for('portal.delete_device') }}"
                        class="d-inline" onsubmit="return confirm('Delete this device?');">
                    <input type="hidden" name="device_id" value="{{ d.id }}">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not devices %}
              <tr><td colspan="5" class="text-muted">No devices found.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Edit Device Modals -->
    {% for d in devices %}
    <div class="modal fade" id="editDeviceModal{{ d.id }}" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Edit Device #{{ d.id }}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.edit_device') }}">
            <input type="hidden" name="device_id" value="{{ d.id }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Device Name</label>
                <input type="text" name="label" class="form-control" value="{{ d.label }}" required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Save Changes</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}

    <!-- Cards -->
    <div class="card p-4 mb-3">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="card-title mb-0">Cards</h4>
        <button class="btn btn-outline-primary" data-bs-toggle="modal" data-bs-target="#addCardModal">
          Add Card
        </button>
      </div>
      <div class="table-wrap">
        <table class="table table-striped">
          <thead>
            <tr>
              <th>Card Type</th><th>Name on Card</th><th>Card Number</th>
              <th>Expiry</th><th>CVV</th><th>Account ID</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            {% for c in cards %}
              <tr>
                <td><span class="badge text-bg-secondary">{{ c.card_type }}</span></td>
                <td>{{ c.name_on_card }}</td>
                <td>**** **** **** {{ c.last4 }}</td>
                <td>{{ "%02d"|format(c.expiry_month) }}/{{ c.expiry_year }}</td>
                <td>{{ c.cvv_mask }}</td>
                <td>{{ c.account_id }}</td>
                <td>
                  <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#editCardModal{{ c.id }}">Edit</button>
                  <form method="post" action="{{ url_for('portal.delete_card') }}"
                        class="d-inline" onsubmit="return confirm('Delete this card?');">
                    <input type="hidden" name="card_id" value="{{ c.id }}">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not cards %}
              <tr><td colspan="7" class="text-muted">No cards yet.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Edit Card Modals -->
    {% for c in cards %}
    <div class="modal fade" id="editCardModal{{ c.id }}" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Edit Card</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.edit_card') }}">
            <input type="hidden" name="card_id" value="{{ c.id }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Name on Card</label>
                <input type="text" name="name_on_card" class="form-control" value="{{ c.name_on_card }}" required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Save Changes</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}

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

    <!-- Add Device Modal -->
    <div class="modal fade" id="addDeviceModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Add Device</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.add_device') }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Device Name</label>
                <input type="text" name="label" class="form-control" placeholder="iPhone 15, MacBook Pro, ..." required>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Add Device</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Add Card Modal -->
    <div class="modal fade" id="addCardModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Add Card</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <form method="post" action="{{ url_for('portal.add_card') }}">
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Card Type</label>
                <select name="card_type" class="form-select" required>
                  <option value="CREDIT">Credit</option>
                  <option value="DEBIT">Debit</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label">Name on Card</label>
                <input type="text" name="name_on_card" class="form-control" value="{{ customer.name }}" required>
              </div>
              <div class="mb-3">
                <label class="form-label">Card Number (16 digits)</label>
                <input type="text" name="card_number" class="form-control" pattern="\\d{16}" maxlength="16" required>
              </div>
              <div class="row">
                <div class="col-md-4 mb-3">
                  <label class="form-label">Expiry Month</label>
                  <input type="number" name="expiry_month" min="1" max="12" class="form-control" required>
                </div>
                <div class="col-md-4 mb-3">
                  <label class="form-label">Expiry Year</label>
                  <input type="number" name="expiry_year" min="2024" max="2050" class="form-control" required>
                </div>
                <div class="col-md-4 mb-3">
                  <label class="form-label">CVV</label>
                  <input type="text" name="cvv" class="form-control" pattern="\\d{3}" maxlength="3" required>
                </div>
              </div>
              <div class="mb-3">
                <label class="form-label">Linked Account</label>
                <select name="account_id" class="form-select" required>
                  {% for a in customer_accounts %}
                    <option value="{{ a.id }}">{{ a.id }} - {{ a.account_type }}</option>
                  {% endfor %}
                </select>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="submit" class="btn btn-primary">Add Card</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    """
    return render_page(
        content,
        show_sidebar=False,
        customer=customer,
        accounts=accounts,
        devices=devices,
        cards=cards,
        customer_accounts=customer_accounts,
    )


@portal_bp.post("/portal/create-account", endpoint="create_account")
@login_required
def create_account():
    cid = current_customer_id()
    try:
        account_type = (request.form.get("account_type") or "").upper()
        holder_name = (request.form.get("holder_name") or "").strip()
        balance = float(request.form.get("balance", 0))

        if account_type not in ("CHECKING", "SAVINGS"):
            flash("Invalid account type.")
            return redirect(url_for("portal.account_details"))

        run_query(
            "INSERT INTO accounts (customer_id, account_type, status, balance, opened_ts) "
            "VALUES (%s,%s,%s,%s,NOW())",
            (cid, account_type, "ACTIVE", balance),
        )
        flash(f"{account_type} account created successfully with balance ${balance:.2f}")
    except Exception as e:
        flash(f"Error creating account: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/accounts/delete", endpoint="delete_account")
@login_required
def delete_account():
    cid = current_customer_id()
    try:
        account_id = int(request.form.get("account_id"))

        # Ensure this account belongs to the user
        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Cannot delete this account.")
            return redirect(url_for("portal.account_details"))

        # Delete related tx / alerts, then account
        run_query(
            "DELETE FROM alerts WHERE transaction_id IN (SELECT id FROM transactions WHERE account_id=%s)",
            (account_id,),
        )
        run_query("DELETE FROM transactions WHERE account_id=%s", (account_id,))
        run_query("DELETE FROM cards WHERE account_id=%s", (account_id,))
        run_query("DELETE FROM accounts WHERE id=%s", (account_id,))

        flash(f"Account {account_id} and related data deleted.")
    except Exception as e:
        flash(f"Error deleting account: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/devices/add", endpoint="add_device")
@login_required
def add_device():
    cid = current_customer_id()
    try:
        label = (request.form.get("label") or "").strip()
        # Auto-generate fingerprint based on label and timestamp
        import hashlib
        import time
        fingerprint = hashlib.md5(f"{label}{time.time()}".encode()).hexdigest()

        run_query(
            """
            INSERT INTO devices (customer_id, fingerprint, label, first_seen_ts, last_seen_ts)
            VALUES (%s,%s,%s,NOW(),NOW())
            """,
            (cid, fingerprint, label),
        )
        flash("Device added successfully.")
    except Exception as e:
        flash(f"Error adding device: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/accounts/edit", endpoint="edit_account")
@login_required
def edit_account():
    cid = current_customer_id()
    try:
        account_id = int(request.form.get("account_id"))
        balance = float(request.form.get("balance"))

        # Verify ownership
        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Cannot edit this account.")
            return redirect(url_for("portal.account_details"))

        run_query("UPDATE accounts SET balance=%s WHERE id=%s", (balance, account_id))
        flash("Account updated successfully.")
    except Exception as e:
        flash(f"Error updating account: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/devices/edit", endpoint="edit_device")
@login_required
def edit_device():
    cid = current_customer_id()
    try:
        device_id = int(request.form.get("device_id"))
        label = (request.form.get("label") or "").strip()

        # Verify ownership
        _, rows = run_query(
            "SELECT 1 FROM devices WHERE id=%s AND customer_id=%s",
            (device_id, cid),
        )
        if not rows:
            flash("Cannot edit this device.")
            return redirect(url_for("portal.account_details"))

        run_query("UPDATE devices SET label=%s WHERE id=%s", (label, device_id))
        flash("Device updated successfully.")
    except Exception as e:
        flash(f"Error updating device: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/cards/edit", endpoint="edit_card")
@login_required
def edit_card():
    cid = current_customer_id()
    try:
        card_id = int(request.form.get("card_id"))
        name_on_card = (request.form.get("name_on_card") or "").strip()

        # Verify ownership
        _, rows = run_query(
            "SELECT 1 FROM cards WHERE id=%s AND customer_id=%s",
            (card_id, cid),
        )
        if not rows:
            flash("Cannot edit this card.")
            return redirect(url_for("portal.account_details"))

        run_query("UPDATE cards SET name_on_card=%s WHERE id=%s", (name_on_card, card_id))
        flash("Card updated successfully.")
    except Exception as e:
        flash(f"Error updating card: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/devices/delete", endpoint="delete_device")
@login_required
def delete_device():
    cid = current_customer_id()
    try:
        device_id = int(request.form.get("device_id"))
        _, rows = run_query(
            "SELECT 1 FROM devices WHERE id=%s AND customer_id=%s",
            (device_id, cid),
        )
        if not rows:
            flash("Cannot delete this device.")
            return redirect(url_for("portal.account_details"))

        run_query("DELETE FROM device_events WHERE device_id=%s", (device_id,))
        run_query("DELETE FROM devices WHERE id=%s", (device_id,))
        flash("Device deleted.")
    except Exception as e:
        flash(f"Error deleting device: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/cards/add", endpoint="add_card")
@login_required
def add_card():
    cid = current_customer_id()
    try:
        card_type = (request.form.get("card_type") or "CREDIT").upper()
        name_on_card = (request.form.get("name_on_card") or "").strip()
        card_number = (request.form.get("card_number") or "").strip()
        expiry_month = int(request.form.get("expiry_month"))
        expiry_year = int(request.form.get("expiry_year"))
        cvv = (request.form.get("cvv") or "").strip()
        account_id = int(request.form.get("account_id"))

        if len(card_number) != 16 or not card_number.isdigit():
            flash("Card number must be 16 digits.")
            return redirect(url_for("portal.account_details"))
        if len(cvv) != 3 or not cvv.isdigit():
            flash("CVV must be 3 digits.")
            return redirect(url_for("portal.account_details"))

        # Ensure account belongs to customer
        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Invalid account for this card.")
            return redirect(url_for("portal.account_details"))

        run_query(
            """
            INSERT INTO cards (
                customer_id, account_id, card_type, name_on_card,
                card_number, expiry_month, expiry_year, cvv
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (cid, account_id, card_type, name_on_card, card_number,
             expiry_month, expiry_year, cvv),
        )
        flash("Card added successfully.")
    except Exception as e:
        flash(f"Error adding card: {e}")
    return redirect(url_for("portal.account_details"))


@portal_bp.post("/portal/cards/delete", endpoint="delete_card")
@login_required
def delete_card():
    cid = current_customer_id()
    try:
        card_id = int(request.form.get("card_id"))
        _, rows = run_query(
            "SELECT 1 FROM cards WHERE id=%s AND customer_id=%s",
            (card_id, cid),
        )
        if not rows:
            flash("Cannot delete this card.")
            return redirect(url_for("portal.account_details"))

        run_query("DELETE FROM cards WHERE id=%s", (card_id,))
        flash("Card deleted.")
    except Exception as e:
        flash(f"Error deleting card: {e}")
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
    _, merchants = run_query("SELECT id, name FROM merchants ORDER BY name LIMIT 100")
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
    return render_page(
        content,
        show_sidebar=False,
        customer=customer,
        accounts=accounts,
        merchants=merchants,
        devices=devices,
    )


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

        # Validate account ownership
        _, rows = run_query(
            "SELECT 1 FROM accounts WHERE id=%s AND customer_id=%s",
            (account_id, cid),
        )
        if not rows:
            flash("Invalid account selection.")
            return redirect(url_for("portal.make_payment_page"))

        merchant_id: Optional[int] = int(merchant_id_raw) if merchant_id_raw else None
        device_id: Optional[int]
        if device_id_raw:
            device_id = int(device_id_raw)
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

        # Check if any HIGH or MEDIUM severity alert fired
        _, alert_rows = run_query(
            "SELECT id, rule_code, severity FROM alerts WHERE transaction_id=%s AND severity IN ('high', 'med')",
            (tx_id,),
        )
        if alert_rows:
            # Mark pending verification and open PIN modal on dashboard
            run_query(
                "UPDATE transactions SET status='declined' WHERE id=%s",
                (tx_id,),
            )
            session["pending_tx_id"] = tx_id
            alert_details = ", ".join([f"{a['rule_code']} ({a['severity']})" for a in alert_rows])
            flash(f"Suspicious activity detected: {alert_details} - please verify with your PIN.")
            return redirect(url_for("portal.portal_home"))

        flash(f"Transaction {tx_id} processed successfully!")
    except Exception as e:
        flash(f"Error: {e}")
        return redirect(url_for("portal.make_payment_page"))
    return redirect(url_for("portal.portal_home"))


@portal_bp.post("/portal/transactions/delete", endpoint="delete_portal_transaction")
@login_required
def delete_portal_transaction():
    cid = current_customer_id()
    try:
        transaction_id = int(request.form.get("transaction_id"))
        # Ensure txn belongs to this customer
        _, rows = run_query(
            """
            SELECT t.id
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.id = %s AND a.customer_id = %s
            """,
            (transaction_id, cid),
        )
        if not rows:
            flash("Cannot delete this transaction.")
            return redirect(url_for("portal.portal_home"))

        run_query("DELETE FROM alerts WHERE transaction_id=%s", (transaction_id,))
        run_query("DELETE FROM transactions WHERE id=%s", (transaction_id,))
        flash(f"Transaction {transaction_id} deleted.")
    except Exception as e:
        flash(f"Error deleting transaction: {e}")
    return redirect(url_for("portal.portal_home"))


# ------------------------ Suspicious Transaction PIN Confirm ------------------------

@portal_bp.post("/portal/transactions/confirm", endpoint="confirm_suspicious_tx")
@login_required
def confirm_suspicious_tx():
    cid = current_customer_id()
    try:
        tx_id = int(request.form.get("tx_id"))
        pin = (request.form.get("pin") or "").strip()
        action = (request.form.get("action") or "approve").lower()

        # Validate tx belongs to this user & is pending
        _, tx_rows = run_query(
            """
            SELECT t.id, t.account_id, t.amount, t.direction
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.id=%s AND a.customer_id=%s
            """,
            (tx_id, cid),
        )
        if not tx_rows:
            flash("Transaction not found.")
            return redirect(url_for("portal.portal_home"))

        tx = tx_rows[0]

        # Fetch PIN hash
        _, auth = run_query(
            "SELECT pin_hash FROM customer_auth WHERE customer_id=%s",
            (cid,),
        )
        if not auth or not auth[0]["pin_hash"]:
            flash("PIN not set for this account.")
            return redirect(url_for("portal.portal_home"))

        if not check_password_hash(auth[0]["pin_hash"], pin):
            flash("Incorrect PIN, please try again.")
            session["pending_tx_id"] = tx_id
            return redirect(url_for("portal.portal_home"))

        if action == "approve":
            run_query(
                "UPDATE alerts SET status='cleared' WHERE transaction_id=%s",
                (tx_id,),
            )
            run_query(
                "UPDATE transactions SET status='approved' WHERE id=%s",
                (tx_id,),
            )
            flash("Transaction approved and alert resolved.")
        else:
            # Deny as fraud: reverse balance effect and mark alerts
            delta = tx["amount"] if tx["direction"] == "debit" else -tx["amount"]
            run_query(
                "UPDATE accounts SET balance = balance + %s WHERE id=%s",
                (delta, tx["account_id"]),
            )
            run_query(
                "UPDATE alerts SET status='confirmed' WHERE transaction_id=%s",
                (tx_id,),
            )
            run_query(
                "UPDATE transactions SET status='reversed' WHERE id=%s",
                (tx_id,),
            )
            
            # Send notification to admin (if table exists)
            try:
                _, customer = run_query("SELECT name, email FROM customers WHERE id=%s", (cid,))
                if customer:
                    run_query(
                        """
                        INSERT INTO admin_notifications (customer_id, transaction_id, title, message, type, created_ts)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            cid,
                            tx_id,
                            "🚨 Fraud Reported by User",
                            f"Customer {customer[0]['name']} ({customer[0]['email']}) reported transaction #{tx_id} (${tx['amount']}) as fraudulent.",
                            "danger"
                        )
                    )
                    flash("Transaction marked as fraud and reversed. Admin has been notified.")
                else:
                    flash("Transaction marked as fraud and reversed.")
            except Exception:
                # Table might not exist yet, just skip notification
                flash("Transaction marked as fraud and reversed.")

        session.pop("pending_tx_id", None)
    except Exception as e:
        flash(f"Error verifying transaction: {e}")
        session.pop("pending_tx_id", None)  # Clear even on error
    return redirect(url_for("portal.portal_home"))


# ------------------------ Demo Fraudulent Transaction ------------------------

@portal_bp.post("/portal/demo-fraud", endpoint="demo_fraud_tx")
@login_required
def demo_fraud_tx():
    """
    Demo helper: create a large, suspicious debit transaction as if it came
    from another part of the system (unknown device, high-risk merchant).
    It uses the same alert + PIN flow as normal transactions.
    """
    cid = current_customer_id()
    try:
        # Choose an account (prefer CHECKING)
        _, accs = run_query(
            """
            SELECT id
            FROM accounts
            WHERE customer_id=%s
            ORDER BY (account_type='CHECKING') DESC, id
            LIMIT 1
            """,
            (cid,),
        )
        if not accs:
            flash("No account available for demo.")
            return redirect(url_for("portal.portal_home"))
        account_id = accs[0]["id"]

        # Choose a high-risk merchant if present
        _, merch = run_query(
            """
            SELECT id
            FROM merchants
            ORDER BY (risk_tier='high') DESC NULLS LAST, id
            LIMIT 1
            """
        )
        merchant_id = merch[0]["id"] if merch else None

        device_id = None   # external / unknown device
        amount = 15000.00
        currency = "USD"
        direction = "debit"
        status = "approved"

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

        # Did we get a high severity alert?
        _, alert_rows = run_query(
            "SELECT id FROM alerts WHERE transaction_id=%s AND severity='high'",
            (tx_id,),
        )
        if alert_rows:
            run_query(
                "UPDATE transactions SET status='declined' WHERE id=%s",
                (tx_id,),
            )
            session["pending_tx_id"] = tx_id
            flash("ðŸš¨ Demo suspicious transaction created â€“ please verify with your PIN.")
        else:
            flash("Demo transaction created but no alert fired â€“ check alert thresholds.")

    except Exception as e:
        flash(f"Error creating demo transaction: {e}")
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
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "account_type",
            "merchant_name",
            "amount",
            "currency",
            "direction",
            "status",
            "ts",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=my_transactions.csv"},
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
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "transaction_id",
            "rule_code",
            "severity",
            "status",
            "amount",
            "currency",
            "created_ts",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=my_alerts.csv"},
    )