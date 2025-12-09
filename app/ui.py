# app/ui.py

from __future__ import annotations

from flask import render_template_string, session
from markupsafe import Markup

SIDEBAR_LINKS = [
    ("Customers", "admin.customers_page"),
    ("Accounts", "admin.accounts_page"),
    ("Merchants", "admin.merchants_page"),
    ("Devices", "admin.devices_page"),
    ("Transactions", "admin.transactions_page"),
    ("Alerts", "admin.alerts_page"),
]


def init_ui(app):
    """
    Initialize UI components if needed.
    This function is called from app/__init__.py
    """
    pass


def render_page(content: str, show_sidebar: bool = True, **context):
    """
    Render a page with optional sidebar navigation.
    """
    # First render the content with the context
    rendered_content = render_template_string(content, **context)
    
    # Check if this is a user portal page (no sidebar)
    is_user_portal = not show_sidebar
    
    # Then render the full page template
    template = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% if is_user_portal %}FinGuard - User Portal{% else %}FinGuard - Admin Portal{% endif %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { font-family: 'Inter', Arial, sans-serif; background: #f5f6fa; margin: 0; padding: 0; }
    .top-nav { background: #1e3a5f; color: white; padding: 0.75rem 1.5rem; display: flex; justify-content: space-between; align-items: center; }
    .top-nav-title { font-size: 1.25rem; font-weight: 600; }
    .top-nav-links { display: flex; gap: 0.5rem; }
    .top-nav-links a, .top-nav-links button { color: white; text-decoration: none; padding: 0.5rem 1rem; border-radius: 6px; background: transparent; border: 1px solid rgba(255,255,255,0.3); font-size: 0.9rem; transition: all 0.3s; }
    .top-nav-links a:hover, .top-nav-links button:hover { background: rgba(255,255,255,0.1); }
    .main-wrapper { display: flex; min-height: calc(100vh - 60px); }
    .sidebar { width: 220px; background: white; border-right: 1px solid #e0e6ed; padding: 1.5rem 0; }
    .sidebar-heading { font-size: 0.75rem; font-weight: 700; color: #8492a6; text-transform: uppercase; letter-spacing: 0.05em; padding: 0 1rem; margin-bottom: 0.75rem; }
    .sidebar a { display: block; padding: 0.75rem 1.5rem; color: #3c4858; text-decoration: none; font-size: 0.95rem; transition: all 0.2s; }
    .sidebar a:hover { background: #f0f3f7; color: #1e3a5f; }
    .content { flex: 1; padding: 2rem; max-width: 1400px; margin: 0 auto; width: 100%; }
    .card { border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 8px; }
    .table-wrap { overflow-x: auto; }
    .monospace { font-family: 'Courier New', monospace; font-size: 0.85rem; }
    .alert { border-radius: 6px; }
  </style>
</head>
<body>
  <nav class="top-nav">
    <div class="top-nav-title">{% if is_user_portal %}FinGuard - User Portal{% else %}FinGuard - Admin Portal{% endif %}</div>
    <div class="top-nav-links">
      {% if is_user_portal %}
        <a href="{{ url_for('portal.start_page') }}">Home</a>
        <a href="{{ url_for('portal.portal_home') }}">My Portal</a>
        <a href="{{ url_for('portal.auth_logout') }}">User Logout</a>
      {% else %}
        <a href="{{ url_for('portal.start_page') }}">Home</a>
        <a href="{{ url_for('admin.admin_dashboard') }}">Admin Dashboard</a>
        <a href="{{ url_for('admin.admin_logout') }}">Admin Logout</a>
        {% if session.get('customer_id') %}
          <a href="{{ url_for('portal.portal_home') }}">My Portal</a>
          <a href="{{ url_for('portal.auth_logout') }}">User Logout</a>
        {% endif %}
      {% endif %}
    </div>
  </nav>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div style="padding: 1rem 1.5rem;">
        {% for message in messages %}
          <div class="alert alert-info">{{ message }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="main-wrapper">
    {% if show_sidebar %}
    <aside class="sidebar">
      <div class="sidebar-heading">Data View</div>
      {% for label, endpoint in sidebar_links %}
        <a href="{{ url_for(endpoint) }}">{{ label }}</a>
      {% endfor %}
    </aside>
    {% endif %}
    <main class="content">
      {{ rendered_content|safe }}
    </main>
  </div>
</body>
</html>
    """
    
    # Add sidebar links, session, and is_user_portal to context
    final_context = {
        'sidebar_links': SIDEBAR_LINKS,
        'session': session,
        'rendered_content': Markup(rendered_content),
        'is_user_portal': is_user_portal
    }
    
    return render_template_string(template, **final_context)