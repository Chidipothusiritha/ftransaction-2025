# app/__init__.py

from __future__ import annotations

from flask import Flask
from .ui import init_ui


def create_app():
    """
    Create and configure the Flask application.
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
        static_url_path='/static'
    )

    # Load configuration
    app.config.from_mapping(
        SECRET_KEY='dev-secret-key-change-in-production',
        DATABASE_URL='postgresql://ftms_user:ftms_password@localhost:5432/ftms_db',
    )

    # Initialize UI
    init_ui(app)

    # Register blueprints
    from .routes.admin import admin_bp
    from .routes.portal import portal_bp
    from .routes.api import api_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(api_bp)

    return app
