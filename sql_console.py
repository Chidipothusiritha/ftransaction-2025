# sql_console.py (writes enabled for UPDATE/DELETE)
import os
import re
from typing import List, Tuple
from flask import Flask, request, render_template_string, redirect, url_for, flash
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# ---- Config ----
ALLOW_WRITE = True          # << enable writes for now
MAX_ROWS = 500
DEFAULT_LIMIT = 50

# allow single-statement SELECT/SHOW/EXPLAIN always;
# when ALLOW_WRITE is True, also allow single UPDATE/DELETE/INSERT
READONLY_START = re.compile(r'^\s*(WITH\b[\s\S]+?\)\s*)?(SELECT|SHOW|EXPLAIN)\b', re.I)
WRITE_START    = re.compile(r'^\s*(WITH\b[\s\S]+?\)\s*)?(UPDATE|DELETE|INSERT)\b', re.I)

# disallow multiple statements (no stray semicolons except trailing)
def is_single_statement(sql: str) -> bool:
    stripped = sql.strip()
    return stripped.count(";") <= (1 if stripped.endswith(";") else 0)

def is_allowed(sql: str) -> bool:
    if not is_single_statement(sql):
        return False
    if READONLY_START.match(sql):
        return True
    if ALLOW_WRITE and WRITE_START.match(sql):
        # Block DDL & potentially dangerous commands explicitly
        if re.search(r'\b(DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|VACUUM|ANALYZE|REINDEX)\b', sql, re.I):
            return False
        return True
    return False

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

def get_conn():
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "frauddb"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
    )

def run_query(sql: str, params: tuple = ()) -> Tuple[List[str], List[dict]]:
    """Execute a SQL and return (columns, rows as dicts). Commits on success."""
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        # SELECT-like queries return a description and rows; UPDATE/DELETE won't.
        rows = cur.fetchmany(MAX_ROWS) if cur.description else []
        cols = list(rows[0].keys()) if rows else ([d.name for d in cur.description] if cur.description else [])
        return cols, rows

BASE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Postgres SQL Console · Demo UI</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 24px; }
    .card { border-radius: 14px; }
    textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .table thead th { position: sticky; top: 0; background: #fff; }
    .monospace { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .table-wrap { max-height: 60vh; overflow:auto; border:1px solid #e9ecef; border-radius: 10px; }
  </style>
</head>
<body>
  <div class="container-fluid">
    <div class="row g-4">

      <!-- Sidebar -->
      <div class="col-12 col-lg-3">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title">Tables</h5>
            <ul class="list-unstyled mb-0">
              <li><a href="{{ url_for('table_view', schema='public', table='customers') }}">👤 Customers</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='accounts') }}">🏦 Accounts</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='merchants') }}">🛍 Merchants</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='transactions') }}">💳 Transactions</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='alerts') }}">⚠️ Alerts</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='devices') }}">📱 Devices</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='device_events') }}">📟 Device Events</a></li>
              <li><a href="{{ url_for('table_view', schema='public', table='notifications') }}">🔔 Notifications</a></li>
            </ul>

            <hr class="my-3">

            <div class="small text-muted">
              Single-statement execution; DDL blocked.
            </div>
          </div>
        </div>

        {% if tables %}
        <div class="card shadow-sm mt-3">
          <div class="card-body">
            <h6 class="card-title mb-2">Tables</h6>
            <ul class="list-unstyled mb-0">
              {% for sch, tbl in tables %}
                <li>
                  <a href="{{ url_for('table_view', schema=sch, table=tbl) }}" class="link-secondary monospace">
                    {{ sch }}.{{ tbl }}
                  </a>
                </li>
              {% endfor %}
            </ul>
          </div>
        </div>
        {% endif %}
      </div>
      <!-- End Sidebar -->

      <!-- Main Content -->
      <div class="col-12 col-lg-9">

        {% with msgs = get_flashed_messages() %}
          {% if msgs %}
            <div class="alert alert-info">{{ msgs[0] }}</div>
          {% endif %}
        {% endwith %}

        <!-- SQL Query Form -->
        <div class="card shadow-sm mb-3">
          <div class="card-body">
            <h5 class="card-title mb-3">SQL Query</h5>
            <form method="post" action="{{ url_for('run_sql') }}" class="row g-2">
              <div class="col-12">
                <textarea name="sql" rows="6" class="form-control"
                          placeholder="SELECT * FROM transactions ORDER BY ts DESC LIMIT 50;">
                          {{ sql or '' }}</textarea>
              </div>
              <div class="col-auto">
                <button class="btn btn-primary" type="submit">Run</button>
              </div>
              <div class="col-auto">
                <a href="{{ url_for('home') }}" class="btn btn-outline-secondary">Clear</a>
              </div>
              <div class="col-12 small text-muted mt-2">
                Allowed now: SELECT/SHOW/EXPLAIN and UPDATE/DELETE/INSERT (single statement; no DDL).
              </div>
            </form>
          </div>
        </div>
        <!-- End SQL Form -->

        <!-- Results Table -->
        {% if cols is not none %}
        <div class="card shadow-sm">
          <div class="card-body">
            <h6 class="card-title mb-2">Results ({{ rows|length }} rows)</h6>
            {% if rows %}
              <div class="table-wrap">
                <table class="table table-sm table-striped align-middle">
                  <thead>
                    <tr>
                      {% for c in cols %}
                        <th class="text-nowrap">{{ c }}</th>
                      {% endfor %}
                    </tr>
                  </thead>
                  <tbody>
                    {% for r in rows %}
                      <tr>
                        {% for c in cols %}
                          <td class="monospace">{{ r[c] }}</td>
                        {% endfor %}
                      </tr>
                    {% endfor %}
                  </tbody>
                </table>
              </div>
            {% else %}
              <p class="text-muted mb-0">
                No rows returned (writes usually don't return rows).
              </p>
            {% endif %}
          </div>
        </div>
        {% endif %}
        <!-- End Results Table -->

      </div>
      <!-- End Main Content -->

    </div>
  </div>
</body>

</html>
"""

def run_and_render(sql):
    cols, rows = run_query(sql)
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql, allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

def fetch_tables():
    sql = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog','information_schema')
    ORDER BY table_schema, table_name;
    """
    _, rows = run_query(sql)
    return [(r["table_schema"], r["table_name"]) for r in rows]

@app.get("/")
def home():
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=None, rows=None,
                                  sql=None, allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.post("/run")
def run_sql():
    sql = (request.form.get("sql") or "").strip()
    if not sql:
        flash("Please enter a SQL statement.")
        return redirect(url_for("home"))
    if not is_allowed(sql):
        flash("Blocked: only single SELECT/SHOW/EXPLAIN or UPDATE/DELETE/INSERT (no DDL).")
        return redirect(url_for("home"))
    try:
        return run_and_render(sql)
    except Exception as e:
        flash(f"Error: {e}")
        return redirect(url_for("home"))

@app.get("/schema")
def schema():
    sql = """
    SELECT table_schema, table_name, column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema NOT IN ('pg_catalog','information_schema')
    ORDER BY table_schema, table_name, ordinal_position
    LIMIT %s;
    """
    cols, rows = run_query(sql, (1000,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", "1000"),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.get("/table/<schema>/<table>")
def table_view(schema, table):
    sql = f'SELECT * FROM "{schema}"."{table}" ORDER BY 1 DESC LIMIT %s;'
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

# Quick links
@app.get("/alerts")
def alerts():
    sql = """
    SELECT a.id, a.transaction_id, a.rule_code, a.severity, a.status, a.created_ts,
           t.amount, t.account_id, t.merchant_id, t.device_id
    FROM alerts a
    JOIN transactions t ON t.id = a.transaction_id
    ORDER BY a.created_ts DESC
    LIMIT %s;
    """
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.get("/transactions")
def transactions():
    sql = "SELECT id, account_id, merchant_id, device_id, amount, currency, status, ts FROM transactions ORDER BY ts DESC LIMIT %s;"
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.get("/devices")
def devices():
    sql = "SELECT id, customer_id, fingerprint, label, first_seen_ts, last_seen_ts FROM devices ORDER BY last_seen_ts DESC NULLS LAST LIMIT %s;"
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.get("/accounts")
def accounts():
    sql = "SELECT id, customer_id, account_type, status, opened_ts FROM accounts ORDER BY opened_ts DESC LIMIT %s;"
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

@app.get("/merchants")
def merchants():
    sql = "SELECT id, name, category, risk_tier FROM merchants ORDER BY id DESC LIMIT %s;"
    cols, rows = run_query(sql, (DEFAULT_LIMIT,))
    tables = fetch_tables()
    return render_template_string(BASE, tables=tables, cols=cols, rows=rows,
                                  sql=sql.replace("%s", str(DEFAULT_LIMIT)),
                                  allow_write=ALLOW_WRITE, max_rows=MAX_ROWS)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
