# app/routes/admin.py

from __future__ import annotations

from typing import Any, Dict, Sequence
import csv
from io import StringIO

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
    return render_template("admin_login.html")


@admin_bp.post("/admin/login", endpoint="admin_do_login")
def admin_do_login():
    user = (request.form.get("username") or "").strip()
    pw = request.form.get("password") or ""
    if user == ADMIN_USER and pw == ADMIN_PASSWORD:
        session["is_admin"] = True
        flash("Welcome, admin.")
        return redirect(url_for("admin.admin_dashboard"))
    flash("Invalid admin credentials.")
    return redirect(url_for("admin.admin_login"))


@admin_bp.get("/admin/logout", endpoint="admin_logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.")
    return redirect(url_for("portal.auth_login"))


# ------------------------ Admin Dashboard ------------------------

@admin_bp.get("/admin", endpoint="admin_dashboard")
@admin_bp.get("/admin/dashboard", endpoint="admin_dashboard_alt")
@admin_required
def admin_dashboard():
    # Stats
    _, customer_count = run_query("SELECT COUNT(*) as count FROM customers")
    _, account_count = run_query("SELECT COUNT(*) as count FROM accounts")
    _, tx_count = run_query("SELECT COUNT(*) as count FROM transactions")
    _, alert_count = run_query("SELECT COUNT(*) as count FROM alerts WHERE status='open'")
    
    stats = {
        'customers': customer_count[0]['count'] if customer_count else 0,
        'accounts': account_count[0]['count'] if account_count else 0,
        'transactions': tx_count[0]['count'] if tx_count else 0,
        'open_alerts': alert_count[0]['count'] if alert_count else 0,
    }

    # Recent activity
    _, recent_tx = run_query(
        """
        SELECT t.id, t.amount, t.currency, t.direction, t.status, t.ts,
               c.name as customer_name, m.name as merchant_name
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        JOIN customers c ON c.id = a.customer_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        ORDER BY t.ts DESC
        LIMIT 10
        """,
    )

    _, recent_alerts = run_query(
        """
        SELECT a.id, a.rule_code, a.severity, a.created_ts,
               c.name as customer_name, t.amount, t.currency
        FROM alerts a
        JOIN transactions t ON t.id = a.transaction_id
        JOIN accounts acc ON acc.id = t.account_id
        JOIN customers c ON c.id = acc.customer_id
        WHERE a.status = 'open'
        ORDER BY a.created_ts DESC
        LIMIT 10
        """,
    )

    content = """
    <div class="row g-3 mb-4">
      <div class="col-12">
        <h2>Admin Dashboard</h2>
      </div>
      <div class="col-md-3">
        <div class="card p-3 bg-primary text-white">
          <h6 class="mb-1">Total Customers</h6>
          <h3 class="mb-0">{{ stats.customers }}</h3>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3 bg-success text-white">
          <h6 class="mb-1">Total Accounts</h6>
          <h3 class="mb-0">{{ stats.accounts }}</h3>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3 bg-info text-white">
          <h6 class="mb-1">Total Transactions</h6>
          <h3 class="mb-0">{{ stats.transactions }}</h3>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card p-3 bg-danger text-white">
          <h6 class="mb-1">Open Alerts</h6>
          <h3 class="mb-0">{{ stats.open_alerts }}</h3>
        </div>
      </div>
    </div>

    <div class="row g-3 mb-3">
      <div class="col-12">
        <div class="card p-3">
          <h5 class="card-title">Quick Actions</h5>
          <div class="d-flex gap-2 flex-wrap">
            <a href="{{ url_for('admin.transactions_page') }}" class="btn btn-sm btn-primary">Manage Transactions</a>
            <a href="{{ url_for('admin.alerts_page') }}" class="btn btn-sm btn-warning">View Alerts</a>
            <a href="{{ url_for('admin.customers_page') }}" class="btn btn-sm btn-success">Customer View</a>
            <a href="{{ url_for('admin.reports_page') }}" class="btn btn-sm btn-info">Download Reports</a>
          </div>
        </div>
      </div>
    </div>

    <div class="row g-3">
      <div class="col-md-6">
        <div class="card p-3">
          <h5 class="card-title">Recent Transactions</h5>
          <div class="table-wrap"><table class="table table-sm">
            <thead><tr><th>ID</th><th>Customer</th><th>Amount</th><th>Type</th><th>Status</th></tr></thead>
            <tbody>
              {% for t in recent_tx %}
                <tr>
                  <td>{{t.id}}</td>
                  <td>{{t.customer_name}}</td>
                  <td>{{t.amount}} {{t.currency}}</td>
                  <td><span class="badge text-bg-{{ 'danger' if t.direction == 'debit' else 'success' }}">{{t.direction}}</span></td>
                  <td>{{t.status}}</td>
                </tr>
              {% endfor %}
              {% if not recent_tx %}<tr><td colspan="5" class="text-muted">No transactions</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>
      
      <div class="col-md-6">
        <div class="card p-3">
          <h5 class="card-title">Recent Open Alerts</h5>
          <div class="table-wrap"><table class="table table-sm">
            <thead><tr><th>ID</th><th>Customer</th><th>Rule</th><th>Severity</th><th>Amount</th></tr></thead>
            <tbody>
              {% for a in recent_alerts %}
                <tr>
                  <td>{{a.id}}</td>
                  <td>{{a.customer_name}}</td>
                  <td><code>{{a.rule_code}}</code></td>
                  <td><span class="badge text-bg-{{ 'danger' if a.severity == 'high' else 'warning' if a.severity == 'medium' else 'secondary' }}">{{a.severity}}</span></td>
                  <td>{{a.amount}} {{a.currency}}</td>
                </tr>
              {% endfor %}
              {% if not recent_alerts %}<tr><td colspan="5" class="text-success">No open alerts</td></tr>{% endif %}
            </tbody>
          </table></div>
        </div>
      </div>
    </div>
    """
    return render_page(content, stats=stats, recent_tx=recent_tx, recent_alerts=recent_alerts, show_sidebar=True)


# ------------------------ Reports ------------------------

@admin_bp.get("/admin/reports", endpoint="reports_page")
@admin_required
def reports_page():
    content = """
    <div class="mb-3">
      <a href="{{ url_for('admin.admin_dashboard') }}" class="btn btn-outline-secondary">← Back to Dashboard</a>
    </div>
    <div class="card p-4">
      <h4 class="card-title mb-3">Download Reports</h4>
      <div class="row g-3">
        <div class="col-md-4">
          <div class="card bg-light p-3">
            <h6>Transactions Report</h6>
            <p class="small text-muted mb-2">All transactions with details</p>
            <a href="{{ url_for('admin.download_transactions_csv') }}" class="btn btn-sm btn-primary">Download CSV</a>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card bg-light p-3">
            <h6>Alerts Report</h6>
            <p class="small text-muted mb-2">All alerts with status</p>
            <a href="{{ url_for('admin.download_alerts_csv') }}" class="btn btn-sm btn-primary">Download CSV</a>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card bg-light p-3">
            <h6>Customers Report</h6>
            <p class="small text-muted mb-2">Customer accounts overview</p>
            <a href="{{ url_for('admin.download_customers_csv') }}" class="btn btn-sm btn-primary">Download CSV</a>
          </div>
        </div>
      </div>
    </div>
    """
    return render_page(content, show_sidebar=True)


@admin_bp.get("/admin/reports/transactions.csv")
@admin_required
def download_transactions_csv():
    _, rows = run_query("""
        SELECT t.id, t.account_id, t.merchant_id, t.device_id, 
               t.amount, t.currency, t.status, t.direction, t.ts,
               c.name as customer_name, m.name as merchant_name
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        JOIN customers c ON c.id = a.customer_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        ORDER BY t.ts DESC
        LIMIT 1000
    """)
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'customer_name', 'account_id', 'merchant_name', 
                                                  'amount', 'currency', 'direction', 'status', 'ts'])
    writer.writeheader()
    writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=transactions.csv"}
    )


@admin_bp.get("/admin/reports/alerts.csv")
@admin_required
def download_alerts_csv():
    _, rows = run_query("""
        SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
               c.name as customer_name, t.amount, t.currency
        FROM alerts a
        JOIN transactions t ON t.id = a.transaction_id
        JOIN accounts acc ON acc.id = t.account_id
        JOIN customers c ON c.id = acc.customer_id
        ORDER BY a.created_ts DESC
        LIMIT 1000
    """)
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'transaction_id', 'customer_name', 'rule_code', 
                                                  'severity', 'status', 'amount', 'currency', 'created_ts'])
    writer.writeheader()
    writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=alerts.csv"}
    )


@admin_bp.get("/admin/reports/customers.csv")
@admin_required
def download_customers_csv():
    _, rows = run_query("""
        SELECT c.id, c.name, c.email, c.signup_ts,
               COUNT(DISTINCT a.id) as account_count,
               COUNT(DISTINCT t.id) as transaction_count
        FROM customers c
        LEFT JOIN accounts a ON a.customer_id = c.id
        LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY c.id, c.name, c.email, c.signup_ts
        ORDER BY c.id DESC
        LIMIT 1000
    """)
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'name', 'email', 'signup_ts', 
                                                  'account_count', 'transaction_count'])
    writer.writeheader()
    writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=customers.csv"}
    )


# ------------------------ Customers ------------------------

@admin_bp.get("/customers", endpoint="customers_page")
@admin_required
def customers_page():
    _, rows = run_query(
        """
        SELECT c.id, c.name, c.email, c.signup_ts,
               COUNT(DISTINCT t.id) as transaction_count
        FROM customers c
        LEFT JOIN accounts a ON a.customer_id = c.id
        LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY c.id, c.name, c.email, c.signup_ts
        ORDER BY c.id DESC
        LIMIT %s
        """,
        (DEFAULT_LIMIT,),
    )
    content = """
    <div class="mb-3">
      <a href="{{ url_for('admin.admin_dashboard') }}" class="btn btn-outline-secondary">← Back to Dashboard</a>
    </div>
    <div class="card shadow-sm mb-3">
      <div class="card-body">
        <h4 class="card-title mb-2">Create, Search, or Delete Customer</h4>
        <form method="post" action="{{ url_for('admin.create_customer') }}" class="row g-2">
          <div class="col-md-4"><label class="form-label">Name</label><input name="name" class="form-control"></div>
          <div class="col-md-4"><label class="form-label">Email</label><input name="email" type="email" class="form-control"></div>
          <div class="col-md-4 d-flex align-items-end gap-1">
            <button type="submit" name="action" value="create" class="btn btn-primary flex-fill">Create</button>
            <button type="submit" name="action" value="search" class="btn btn-outline-primary flex-fill">Search</button>
            <button type="submit" name="action" value="delete" class="btn btn-outline-danger flex-fill">Delete</button>
          </div>
        </form>
      </div>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">Recent Customers</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Signup Date</th><th>Transactions</th><th>Actions</th></tr></thead>
          <tbody>
            {% for r in rows %}
              <tr>
                <td>{{r.id}}</td>
                <td>{{r.name}}</td>
                <td>{{r.email}}</td>
                <td>{{r.signup_ts}}</td>
                <td>{{r.transaction_count}}</td>
                <td><a href="{{ url_for('admin.customer_detail', customer_id=r.id) }}" class="btn btn-sm btn-outline-primary">View</a></td>
              </tr>
            {% endfor %}
            {% if not rows %}<tr><td colspan="6" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, show_sidebar=True)


@admin_bp.post("/customers/create", endpoint="create_customer")
@admin_required
def create_customer():
    try:
        action = request.form.get("action", "create")
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        
        if action == "delete":
            # Delete customer by name or email
            if not name and not email:
                flash("Please enter a name or email to delete.")
                return redirect(url_for("admin.customers_page"))
            
            # Find customers to delete
            if name and email:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(email) LIKE LOWER(%s)",
                    (f"%{name}%", f"%{email}%")
                )
            elif name:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(name) LIKE LOWER(%s)",
                    (f"%{name}%",)
                )
            else:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(email) LIKE LOWER(%s)",
                    (f"%{email}%",)
                )
            
            if not customers:
                flash("No customers found to delete.")
                return redirect(url_for("admin.customers_page"))
            
            # Delete related data first, then customers
            customer_ids = [c["id"] for c in customers]
            customer_ids_str = ",".join(str(cid) for cid in customer_ids)
            
            # Delete in correct order
            run_query(f"DELETE FROM alerts WHERE transaction_id IN (SELECT t.id FROM transactions t JOIN accounts a ON a.id = t.account_id WHERE a.customer_id IN ({customer_ids_str}))")
            run_query(f"DELETE FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE customer_id IN ({customer_ids_str}))")
            run_query(f"DELETE FROM accounts WHERE customer_id IN ({customer_ids_str})")
            run_query(f"DELETE FROM device_events WHERE device_id IN (SELECT id FROM devices WHERE customer_id IN ({customer_ids_str}))")
            run_query(f"DELETE FROM devices WHERE customer_id IN ({customer_ids_str})")
            run_query(f"DELETE FROM customers WHERE id IN ({customer_ids_str})")
            
            flash(f"Deleted {len(customers)} customer(s) and all related data.")
            return redirect(url_for("admin.customers_page"))
        
        if action == "search":
            # Search for customer by name or email (partial match)
            if not name and not email:
                flash("Please enter a name or email to search.")
                return redirect(url_for("admin.customers_page"))
            
            # Build search query
            if name and email:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(email) LIKE LOWER(%s) ORDER BY id DESC",
                    (f"%{name}%", f"%{email}%")
                )
            elif name:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(name) LIKE LOWER(%s) ORDER BY id DESC",
                    (f"%{name}%",)
                )
            else:
                _, customers = run_query(
                    "SELECT id, name, email FROM customers WHERE LOWER(email) LIKE LOWER(%s) ORDER BY id DESC",
                    (f"%{email}%",)
                )
            
            if not customers:
                flash(f"No customers found matching your search.")
                return redirect(url_for("admin.customers_page"))
            elif len(customers) == 1:
                return redirect(url_for("admin.customer_detail", customer_id=customers[0]["id"]))
            else:
                flash(f"Found {len(customers)} matching customers. Showing the most recent one.")
                return redirect(url_for("admin.customer_detail", customer_id=customers[0]["id"]))
        
        # Create customer
        if not name or not email:
            flash("Both name and email are required to create a customer.")
            return redirect(url_for("admin.customers_page"))
            
        run_query(
            "INSERT INTO customers (name, email, signup_ts) VALUES (%s,%s,NOW())",
            (name, email),
        )
        flash("Customer created.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.customers_page"))


# ------------------------ Customer Detail View ------------------------

@admin_bp.get("/customers/<int:customer_id>", endpoint="customer_detail")
@admin_required
def customer_detail(customer_id: int):
    # Get customer info
    _, cust = run_query("SELECT id, name, email, signup_ts FROM customers WHERE id=%s", (customer_id,))
    if not cust:
        flash("Customer not found.")
        return redirect(url_for("admin.customers_page"))
    
    customer = cust[0]
    
    # Get customer accounts
    _, accounts = run_query(
        "SELECT id, account_type, balance, status FROM accounts WHERE customer_id=%s ORDER BY id",
        (customer_id,),
    )
    
    # Get customer transactions
    _, transactions = run_query(
        """
        SELECT t.id, t.account_id, t.amount, t.currency, t.direction, t.status, t.ts,
               m.name as merchant_name, a.account_type
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        WHERE a.customer_id = %s
        ORDER BY t.ts DESC
        LIMIT 50
        """,
        (customer_id,),
    )
    
    # Get customer alerts
    _, alerts = run_query(
        """
        SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
               t.amount, t.currency
        FROM alerts a
        JOIN transactions t ON t.id = a.transaction_id
        JOIN accounts acc ON acc.id = t.account_id
        WHERE acc.customer_id = %s
        ORDER BY a.created_ts DESC
        LIMIT 20
        """,
        (customer_id,),
    )
    
    content = """
    <div class="mb-3">
      <a href="{{ url_for('admin.customers_page') }}" class="btn btn-outline-secondary">← Back to Customers</a>
    </div>
    
    <div class="card p-4 mb-3">
      <h3 class="card-title">Customer: {{ customer.name }}</h3>
      <div class="row mt-3">
        <div class="col-md-4"><strong>ID:</strong> {{ customer.id }}</div>
        <div class="col-md-4"><strong>Email:</strong> {{ customer.email }}</div>
        <div class="col-md-4"><strong>Signup:</strong> {{ customer.signup_ts }}</div>
      </div>
    </div>

    <div class="card p-3 mb-3">
      <h5 class="card-title">Accounts</h5>
      <div class="table-wrap"><table class="table table-sm">
        <thead><tr><th>ID</th><th>Type</th><th>Balance</th><th>Status</th></tr></thead>
        <tbody>
          {% for a in accounts %}
            <tr><td>{{a.id}}</td><td>{{a.account_type}}</td><td>${{a.balance}}</td><td>{{a.status}}</td></tr>
          {% endfor %}
          {% if not accounts %}<tr><td colspan="4" class="text-muted">No accounts</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>

    <div class="card p-3 mb-3">
      <h5 class="card-title">Transactions</h5>
      <div class="table-wrap"><table class="table table-sm">
        <thead><tr><th>ID</th><th>Account</th><th>Merchant</th><th>Amount</th><th>Type</th><th>Status</th><th>Date</th></tr></thead>
        <tbody>
          {% for t in transactions %}
            <tr>
              <td>{{t.id}}</td>
              <td>{{t.account_type}}</td>
              <td>{{t.merchant_name or '—'}}</td>
              <td>{{t.amount}} {{t.currency}}</td>
              <td><span class="badge text-bg-{{ 'danger' if t.direction == 'debit' else 'success' }}">{{t.direction}}</span></td>
              <td>{{t.status}}</td>
              <td>{{t.ts}}</td>
            </tr>
          {% endfor %}
          {% if not transactions %}<tr><td colspan="7" class="text-muted">No transactions</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>

    <div class="card p-3">
      <h5 class="card-title">Alerts</h5>
      <div class="table-wrap"><table class="table table-sm">
        <thead><tr><th>ID</th><th>Transaction</th><th>Rule</th><th>Severity</th><th>Status</th><th>Amount</th><th>Date</th></tr></thead>
        <tbody>
          {% for a in alerts %}
            <tr>
              <td>{{a.id}}</td>
              <td>#{{a.transaction_id}}</td>
              <td><code>{{a.rule_code}}</code></td>
              <td><span class="badge text-bg-{{ 'danger' if a.severity == 'high' else 'warning' if a.severity == 'medium' else 'secondary' }}">{{a.severity}}</span></td>
              <td>{{a.status}}</td>
              <td>{{a.amount}} {{a.currency}}</td>
              <td>{{a.created_ts}}</td>
            </tr>
          {% endfor %}
          {% if not alerts %}<tr><td colspan="7" class="text-muted">No alerts</td></tr>{% endif %}
        </tbody>
      </table></div>
    </div>
    """
    return render_page(content, customer=customer, accounts=accounts, transactions=transactions, alerts=alerts, show_sidebar=True)


# ------------------------ Accounts ------------------------

@admin_bp.get("/accounts", endpoint="accounts_page")
@admin_required
def accounts_page():
    _, rows = run_query(
        """
        SELECT a.id, a.customer_id, a.account_type, a.status, a.balance, a.opened_ts,
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
              {% for c in customers %}<option value="{{c.id}}">{{c.id}} – {{c.name}}</option>{% endfor %}
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
          <thead><tr><th>ID</th><th>Customer</th><th>Type</th><th>Balance</th><th>Status</th><th>Opened</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.customer_id}} – {{r.customer_name}}</td><td>{{r.account_type}}</td><td>${{r.balance}}</td><td>{{r.status}}</td><td>{{r.opened_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="6" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, customers=customers, show_sidebar=True)


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
          <thead><tr><th>ID</th><th>Name</th><th>Category</th><th>Risk Tier</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.name}}</td><td>{{r.category}}</td><td>{{r.risk_tier}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="4" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, show_sidebar=True)


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
              {% for c in customers %}<option value="{{c.id}}">{{c.id}} – {{c.name}}</option>{% endfor %}
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
          <thead><tr><th>ID</th><th>Customer</th><th>Fingerprint</th><th>Label</th><th>First Seen</th><th>Last Seen</th></tr></thead>
          <tbody>
            {% for r in rows %}<tr><td>{{r.id}}</td><td>{{r.customer_id}} – {{r.customer_name}}</td><td class="monospace">{{r.fingerprint}}</td><td>{{r.label}}</td><td>{{r.first_seen_ts}}</td><td>{{r.last_seen_ts}}</td></tr>{% endfor %}
            {% if not rows %}<tr><td colspan="6" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody></table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, customers=customers, show_sidebar=True)


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


# ------------------------ Transactions ------------------------

@admin_bp.get("/transactions", endpoint="transactions_page")
@admin_required
def transactions_page():
    _, tx = run_query(
        """
        SELECT
          t.id, t.account_id, t.merchant_id, t.device_id,
          t.amount, t.currency, t.direction, t.status, t.ts,
          c.name as customer_name,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM alerts a
              WHERE a.transaction_id = t.id AND a.status = 'open'
            ) THEN TRUE ELSE FALSE
          END AS suspicious
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        JOIN customers c ON c.id = a.customer_id
        WHERE t.device_id IS NOT NULL
        ORDER BY t.ts DESC
        LIMIT %s
    """,
        (DEFAULT_LIMIT,),
    )

    content = """
    <div class="mb-3">
      <a href="{{ url_for('admin.admin_dashboard') }}" class="btn btn-outline-secondary">← Back to Dashboard</a>
    </div>
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
              <div class="col-md-4">
                <label class="form-label">Direction</label>
                <select name="direction" class="form-select">
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                </select>
              </div>
              <div class="col-md-6"><label class="form-label">Status</label><input name="status" class="form-control" value="approved"></div>
              <div class="col-md-6"><label class="form-label">Timestamp</label><input name="ts" type="datetime-local" class="form-control"></div>
              <div class="col-12"><button class="btn btn-primary w-100">Create &amp; Check Alerts</button></div>
            </form>
          </div>
        </div>
      </div>

      <div class="col-12 col-xl-5">
        <div class="alert alert-info small">
          Simulate transactions from different accounts, devices, and merchants.
          Alerts will be raised automatically.
        </div>
      </div>
    </div>

    <div class="card shadow-sm mt-3">
      <div class="card-body">
        <h5 class="card-title">Recent Transactions</h5>
        <div class="table-wrap"><table class="table table-sm table-striped">
          <thead>
            <tr><th>ID</th><th>Customer</th><th>Account</th><th>Merchant</th><th>Device</th><th>Amount</th><th>Currency</th><th>Type</th><th>Suspicious</th><th>Timestamp</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for r in tx %}
              <tr>
                <td>{{r.id}}</td>
                <td>{{r.customer_name}}</td>
                <td>{{r.account_id}}</td>
                <td>{{r.merchant_id}}</td>
                <td>{{r.device_id}}</td>
                <td>{{r.amount}}</td>
                <td>{{r.currency}}</td>
                <td><span class="badge text-bg-{{ 'danger' if r.direction == 'debit' else 'success' }}">{{r.direction}}</span></td>
                <td>{% if r.suspicious %}<span class="badge text-bg-danger">Yes</span>{% else %}<span class="badge text-bg-secondary">No</span>{% endif %}</td>
                <td>{{r.ts}}</td>
                <td>
                  <form method="post" action="{{ url_for('admin.delete_transaction') }}" class="d-inline" onsubmit="return confirm('Delete this transaction?');">
                    <input type="hidden" name="transaction_id" value="{{r.id}}">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not tx %}<tr><td colspan="11" class="text-muted">None yet.</td></tr>{% endif %}
          </tbody>
        </table></div>
      </div>
    </div>
    """
    return render_page(content, tx=tx, show_sidebar=True)


@admin_bp.post("/transactions/create", endpoint="create_transaction")
@admin_required
def create_transaction():
    try:
        aid = int(request.form.get("account_id"))
        mid = request.form.get("merchant_id")
        did = request.form.get("device_id")
        amount = float(request.form.get("amount"))
        currency = (request.form.get("currency") or "USD").upper()
        direction = (request.form.get("direction") or "debit").lower()
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
            direction=direction,
        )
        flash(f"Transaction {tx_id} created. Rules evaluated.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.transactions_page"))


@admin_bp.post("/transactions/delete", endpoint="delete_transaction")
@admin_required
def delete_transaction():
    try:
        transaction_id = int(request.form.get("transaction_id"))
        # Delete alerts first, then transaction
        run_query("DELETE FROM alerts WHERE transaction_id = %s", (transaction_id,))
        run_query("DELETE FROM transactions WHERE id = %s", (transaction_id,))
        flash(f"Transaction {transaction_id} deleted.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.transactions_page"))


# ------------------------ Alerts ------------------------

@admin_bp.get("/alerts", endpoint="alerts_page")
@admin_required
def alerts_page():
    _, rows = run_query(
        """
        SELECT
          a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
          t.amount, t.currency, c.name AS customer_name
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
    <div class="mb-3">
      <a href="{{ url_for('admin.admin_dashboard') }}" class="btn btn-outline-secondary">← Back to Dashboard</a>
    </div>
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">Open Alerts</h4>
        <p class="text-muted small mb-3">
          These alerts are currently <strong>open</strong>. Click <em>Resolve</em> once investigated.
        </p>
        <div class="table-wrap"><table class="table table-sm table-striped align-middle">
          <thead>
            <tr><th>ID</th><th>Transaction</th><th>Customer</th><th>Rule</th><th>Severity</th><th>Amount</th><th>Status</th><th>Created</th><th>Action</th></tr>
          </thead>
          <tbody>
            {% for a in rows %}
              <tr>
                <td>{{a.id}}</td><td>#{{a.transaction_id}}</td><td>{{a.customer_name}}</td>
                <td><code>{{a.rule_code}}</code></td>
                <td>
                  {% if a.severity == 'high' %}<span class="badge text-bg-danger">{{a.severity}}</span>
                  {% elif a.severity == 'medium' %}<span class="badge text-bg-warning text-dark">{{a.severity}}</span>
                  {% else %}<span class="badge text-bg-secondary">{{a.severity}}</span>{% endif %}
                </td>
                <td>{{a.amount}} {{a.currency}}</td><td>{{a.status}}</td><td>{{a.created_ts}}</td>
                <td>
                  <form method="post" action="{{ url_for('admin.resolve_alert') }}" class="d-inline">
                    <input type="hidden" name="alert_id" value="{{a.id}}">
                    <button class="btn btn-sm btn-outline-success">Resolve</button>
                  </form>
                </td>
              </tr>
            {% endfor %}
            {% if not rows %}<tr><td colspan="9" class="text-muted">No open alerts 🎉</td></tr>{% endif %}
          </tbody>
        </table></div>
      </div>
    </div>
    """
    return render_page(content, rows=rows, show_sidebar=True)


@admin_bp.post("/alerts/resolve", endpoint="resolve_alert")
@admin_required
def resolve_alert():
    try:
        alert_id = int(request.form.get("alert_id"))
        run_query("UPDATE alerts SET status='resolved' WHERE id=%s", (alert_id,))
        flash(f"Alert {alert_id} resolved.")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for("admin.alerts_page"))