# helpers.py — Shared helpers: session-based authentication decorators, the anti-CSRF token and utility functions used in templates.

import hmac
import secrets
from functools import wraps
from flask import session, redirect, url_for, flash, request, abort


def current_user():
    # Return the session user as a dictionary (or None).
    if session.get("user_id"):
        return {"user_id": session["user_id"], "username": session.get("username")}
    return None


def is_admin():
    return session.get("username") == "admin"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to perform this action.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to perform this action.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if session.get("username") != "admin":
            flash("This area is restricted to the administrator.", "danger")
            return redirect(url_for("standings.index"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    """Return the per-session anti-CSRF token (created on first use).

    Every POST form contains it in a hidden field; a request forged by another
    site cannot know it, so check_csrf() rejects such requests.
    """
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf():
    # before_request hook: a POST must send back the token of its session
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
            abort(400)