# app/__init__.py

import os
from flask import Flask

from .ui import init_ui


def create_app() -> Flask:
    """
    Application factory. Creates the Flask app, loads config,
    and registers all blueprints.
    """
    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

    # Attach UI helpers / Jinja globals
    init_ui(app)

    # Import and register blueprints
    from .routes.portal import portal_bp
    from .routes.admin import admin_bp
    from .routes.api import api_bp

    app.register_blueprint(portal_bp)   # /, /start, /auth/*, /portal
    app.register_blueprint(admin_bp)    # /admin/login, /customers, /transactions, ...
    app.register_blueprint(api_bp)      # /api/alerts, ...

    return app
