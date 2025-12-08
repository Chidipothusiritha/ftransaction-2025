# app/ui.py

from __future__ import annotations

from flask import render_template_string

from .auth import is_admin


# ------------------------ Base layout template ------------------------

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
    <a class="navbar-brand" href="{{ url_for('portal.start_page') }}">FT Admin</a>
    <div class="d-flex gap-2">
      <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal.start_page') }}">Home</a>

      {% if is_admin() %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin.transactions_page') }}">Admin Dashboard</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin.admin_logout') }}">Admin Logout</a>
      {% else %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin.admin_login') }}">Admin Login</a>
      {% endif %}

      {% if session.get('customer_id') %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal.portal_home') }}">My Portal</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal.auth_logout') }}">User Logout</a>
      {% else %}
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal.auth_login') }}">User Login</a>
        <a class="btn btn-sm btn-outline-light" href="{{ url_for('portal.auth_signup') }}">User Sign up</a>
      {% endif %}
    </div>
  </div>
</nav>

<div class="container-fluid py-4">
  <div class="row g-4">
        {% if is_admin() and show_sidebar %}
      <aside class="col-12 col-lg-3">
        <div class="card p-3 sidebar">
          <div class="list-group">
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.customers_page') }}">Customers</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.accounts_page') }}">Accounts</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.merchants_page') }}">Merchants</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.devices_page') }}">Devices</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.device_events_page') }}">Device Events</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.transactions_page') }}">Transactions</a>
            <a class="list-group-item list-group-item-action" href="{{ url_for('admin.alerts_page') }}">Alerts</a>
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


# ------------------------ Integration helpers ------------------------

def init_ui(app):
    """
    Attach Jinja globals etc. to the Flask app.
    """
    app.jinja_env.globals["is_admin"] = is_admin


def render_page(content_tpl: str, show_sidebar: bool = True, **ctx):
    """
    Render inner content first, then inject into BASE layout.
    """
    inner = render_template_string(content_tpl, **ctx)
    return render_template_string(
        BASE,
        content=inner,
        show_sidebar=show_sidebar,
    )
