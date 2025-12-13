# app/auth.py

from __future__ import annotations

import os
import re
from functools import wraps
from typing import Callable, Optional

from flask import session, redirect, url_for, flash

from .db import table_exists

# ------------------------ Admin credentials from env ------------------------

# These are used by the admin login view (in routes/admin.py)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # change in .env!


# ------------------------ Admin / user flags ------------------------

def is_admin() -> bool:
    """
    True if the current session belongs to an admin user.
    Admin login sets session['is_admin'] = True.
    """
    return bool(session.get("is_admin"))


def auth_table_exists() -> bool:
    """
    Check if the customer_auth table is present.
    """
    return table_exists("public", "customer_auth")


def current_customer_id() -> Optional[int]:
    """
    Convenience accessor for logged-in user id.
    """
    return session.get("customer_id")


# ------------------------ Decorators & validators ------------------------

def login_required(fn: Callable):
    """
    Decorator for user-portal routes. Redirects to /auth/login if no user.
    """
    @wraps(fn)
    def _inner(*args, **kwargs):
        if not current_customer_id():
            flash("Please sign in.")
            return redirect(url_for("portal.auth_login"))  # FIXED: Added "portal." prefix
        return fn(*args, **kwargs)
    return _inner


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s or ""))