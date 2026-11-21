#routes/standings.py — Championship standings (drivers + constructors).
#Points are computed ONLY for the selected season, Grand Prix and sprint points together, by the hfg_fn_driver_standings / hfg_fn_constructor_standings SQL functions.

from flask import Blueprint, render_template
import db
from routes.common import resolve_season

bp = Blueprint("standings", __name__, url_prefix="/standings")

DRIVER_STANDINGS = "SELECT * FROM hfg_fn_driver_standings(%s);"
CONSTRUCTOR_STANDINGS = "SELECT * FROM hfg_fn_constructor_standings(%s);"


@bp.route("/")
def index():
    season, seasons = resolve_season()
    drivers = constructors = []
    if season:
        drivers = db.query(DRIVER_STANDINGS, (season["season_id"],))
        constructors = db.query(CONSTRUCTOR_STANDINGS, (season["season_id"],))
    return render_template(
        "standings.html",
        season=season, seasons=seasons,
        drivers=drivers, constructors=constructors,
    )