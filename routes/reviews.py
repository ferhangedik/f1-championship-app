#routes/reviews.py — Add/update/delete race reviews (rating + comment).
#The work is done by the stored procedures hfg_sp_save_review and hfg_sp_delete_review (procedures.sql). 

from flask import Blueprint, request, redirect, url_for, flash, session, abort
from psycopg.errors import RaiseException
import db
from helpers import login_required, is_admin

bp = Blueprint("reviews", __name__, url_prefix="/reviews")


@bp.route("/race/<int:race_id>", methods=["POST"])
@login_required
def save(race_id):
    if not db.query("SELECT 1 FROM hfg_races WHERE race_id = %s", (race_id,), one=True):
        abort(404)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()

    try:
        db.execute("CALL hfg_sp_save_review(%s, %s, %s, %s)",
                   (session["user_id"], race_id, rating, comment))
    except RaiseException as exc:
        flash(exc.diag.message_primary, "warning")
        return redirect(url_for("races.detail", race_id=race_id) + "#reviews")

    flash("Your review has been saved.", "success")
    return redirect(url_for("races.detail", race_id=race_id) + "#reviews")


@bp.route("/<int:review_id>/delete", methods=["POST"])
@login_required
def delete(review_id):
    rv = db.query("SELECT race_id FROM hfg_reviews WHERE review_id = %s", (review_id,), one=True)
    if not rv:
        flash("Review not found.", "warning")
        return redirect(url_for("standings.index"))

    # The procedure checks ownership: a user may delete only their own review, the admin may delete anyone's.
    try:
        db.execute("CALL hfg_sp_delete_review(%s, %s, %s)",
                   (review_id, session["user_id"], is_admin()))
    except RaiseException as exc:
        flash(exc.diag.message_primary, "danger")
        return redirect(url_for("races.detail", race_id=rv["race_id"]))

    flash("Review deleted.", "info")
    return redirect(url_for("races.detail", race_id=rv["race_id"]) + "#reviews")