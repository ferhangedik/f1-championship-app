#routes/auth.py — Session-based authentication (register, login, logout).

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import db

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("standings.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.query(
            "SELECT user_id, username, password_hash FROM hfg_users WHERE username = %s",
            (username,), one=True,
        )
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            flash(f"Welcome, {user['username']}!", "success")
            return redirect(_safe_next(request.args.get("next")))
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 8:
            flash("Username must be at least 3 and password at least 8 characters.", "warning")
        elif db.query("SELECT 1 FROM hfg_users WHERE username = %s", (username,), one=True):
            flash("That username is already taken.", "warning")
        else:
            db.execute(
                "INSERT INTO hfg_users (username, password_hash) VALUES (%s, %s)",
                (username, generate_password_hash(password)),
            )
            flash("Registration successful! You can now log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("standings.index"))