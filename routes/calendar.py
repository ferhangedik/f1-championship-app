#routes/calendar.py — Race calendar and countdown to the next race.

from datetime import datetime, time
from flask import Blueprint, render_template
import db

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

UPCOMING = """
SELECT r.race_id, r.name, r.round, r.race_date, r.race_time,
       c.name AS circuit, c.location, c.country, s.year
FROM hfg_races r
JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
JOIN hfg_seasons  s ON s.season_id = r.season_id
WHERE r.is_upcoming = TRUE
  AND r.race_date >= CURRENT_DATE   -- only races from today onward (so the countdown is meaningful)
ORDER BY r.race_date, r.round;
"""


@bp.route("/")
def index():
    upcoming = db.query(UPCOMING)

    next_iso = None
    if upcoming:
        nxt = upcoming[0]
        t = nxt["race_time"] or time(13, 0)
        next_iso = datetime.combine(nxt["race_date"], t).isoformat() + "Z"

    return render_template(
        "calendar.html",
        upcoming=upcoming,
        next_race=upcoming[0] if upcoming else None,
        next_iso=next_iso,
    )