# app/routes/__init__.py

from .portal import portal_bp
from .admin import admin_bp
from .api import api_bp

__all__ = ["portal_bp", "admin_bp", "api_bp"]
