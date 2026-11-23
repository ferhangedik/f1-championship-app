#routes/admin.py — Administrator panel (only the 'admin' user).
"""
Protected by the @admin_required decorator. Contains the dashboard (statistics and the latest entries of the driver audit log) and driver CRUD (create / edit / delete). 
Every write goes through a stored procedure (hfg_sp_create_driver, hfg_sp_update_driver, hfg_sp_delete_driver in procedures.sql), which validates the input;
the hfg_trg_drivers_audit trigger then records the change in hfg_driver_audit.
"""

from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
from psycopg.errors import DataError, RaiseException
import db
from helpers import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def dashboard():
    # All counts in a single query with sub-queries
    stats = db.query(
        """SELECT (SELECT COUNT(*) FROM hfg_drivers)  AS drivers,
                  (SELECT COUNT(*) FROM hfg_teams)    AS teams,
                  (SELECT COUNT(*) FROM hfg_races)    AS races,
                  (SELECT COUNT(*) FROM hfg_circuits) AS circuits,
                  (SELECT COUNT(*) FROM hfg_users)    AS users,
                  (SELECT COUNT(*) FROM hfg_results)  AS results,
                  (SELECT COUNT(*) FROM hfg_reviews)  AS reviews""",
        one=True,
    )
    # Latest changes recorded by the hfg_trg_drivers_audit trigger
    audit = db.query(
        """SELECT operation, changed_by, changed_at,
                  COALESCE(new_data, old_data) ->> 'first_name' AS first_name,
                  COALESCE(new_data, old_data) ->> 'last_name'  AS last_name
           FROM hfg_driver_audit
           ORDER BY changed_at DESC, audit_id DESC
           LIMIT 10"""
    )
    return render_template("admin/dashboard.html", stats=stats, audit=audit)


@bp.route("/drivers")
@admin_required
def drivers():
    rows = db.query(
        """SELECT d.driver_id, d.first_name, d.last_name, d.nationality, t.name AS team
           FROM hfg_drivers d
           LEFT JOIN hfg_teams t ON t.team_id = d.team_id
           ORDER BY d.last_name, d.first_name"""
    )
    return render_template("admin/drivers.html", drivers=rows)


@bp.route("/drivers/new", methods=["GET", "POST"])
@admin_required
def driver_new():
    teams = db.query("SELECT team_id, name FROM hfg_teams ORDER BY name")
    driver = None
    if request.method == "POST":
        if _save_driver(None):
            flash("Driver added.", "success")
            return redirect(url_for("admin.drivers"))
        driver = _form_values()  # keep what was typed after a validation error
    return render_template("admin/driver_form.html", teams=teams, driver=driver, action="new")


@bp.route("/drivers/<int:driver_id>/edit", methods=["GET", "POST"])
@admin_required
def driver_edit(driver_id):
    teams = db.query("SELECT team_id, name FROM hfg_teams ORDER BY name")
    driver = db.query("SELECT * FROM hfg_drivers WHERE driver_id = %s", (driver_id,), one=True)
    if not driver:
        abort(404)
    if request.method == "POST":
        if _save_driver(driver_id):
            flash("Driver updated.", "success")
            return redirect(url_for("admin.drivers"))
        driver = _form_values()
    return render_template("admin/driver_form.html", teams=teams, driver=driver, action="edit")


@bp.route("/drivers/<int:driver_id>/delete", methods=["POST"])
@admin_required
def driver_delete(driver_id):
    # the procedure refuses to delete a driver who has race results
    try:
        db.execute("CALL hfg_sp_delete_driver(%s, %s)", (driver_id, session["username"]))
        flash("Driver deleted.", "info")
    except RaiseException as exc:
        flash(exc.diag.message_primary, "danger")
    return redirect(url_for("admin.drivers"))


def _form_values():
    #The submitted form as a driver-like dict, used to refill the form.
    f = request.form
    try:
        dob = date.fromisoformat(f.get("date_of_birth") or "")
    except ValueError:
        dob = None
    return {
        "first_name": f.get("first_name", ""), "last_name": f.get("last_name", ""),
        "date_of_birth": dob, "nationality": f.get("nationality", ""),
        "team_id": f.get("team_id", type=int), "photo_url": f.get("photo_url", ""),
        "wiki_url": f.get("wiki_url", ""),
    }


def _save_driver(driver_id):
    """Create (driver_id None) or update a driver from the form data through the
    stored procedures. Returns True on success; on a validation error raised by
    the database it flashes the message and returns False."""
    f = request.form
    dob = f.get("date_of_birth") or None
    if dob:
        try:
            dob = date.fromisoformat(dob)
        except ValueError:
            flash("Date of birth must be a valid date (YYYY-MM-DD).", "danger")
            return False
    vals = (
        f.get("first_name", ""),
        f.get("last_name", ""),
        dob,
        f.get("nationality", ""),
        f.get("team_id", type=int) or None,
        f.get("photo_url", ""),
        f.get("wiki_url", ""),
        session["username"],
    )
    try:
        if driver_id is None:
            db.execute("CALL hfg_sp_create_driver(%s, %s, %s, %s, %s, %s, %s, %s)", vals)
        else:
            db.execute("CALL hfg_sp_update_driver(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                       (driver_id,) + vals)
    except (RaiseException, DataError) as exc:
        flash(exc.diag.message_primary, "danger")
        return False
    return True