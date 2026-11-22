#routes/home.py — Home page (dashboard) and site search.
#All values are computed with SQL aggregation queries.

from datetime import datetime, time
from flask import Blueprint, render_template, request
import db

bp = Blueprint("home", __name__)


CURRENT_SEASON = "SELECT season_id, year FROM hfg_seasons ORDER BY year DESC LIMIT 1"

# Championship leaders: the first row of the standings functions (procedures.sql)
DRIVER_LEADER = "SELECT * FROM hfg_fn_driver_standings(%s) LIMIT 1;"
TEAM_LEADER = "SELECT * FROM hfg_fn_constructor_standings(%s) LIMIT 1;"

LAST_RACE = """
SELECT r.race_id, r.name, r.round, r.race_date, c.country
FROM hfg_races r
JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
WHERE r.season_id = %s AND r.is_upcoming = FALSE
ORDER BY r.round DESC
LIMIT 1;
"""

PODIUM = """
SELECT res.finish_position, d.driver_id, d.first_name, d.last_name, t.name AS team
FROM hfg_results res
JOIN hfg_drivers d ON d.driver_id = res.driver_id
LEFT JOIN hfg_teams t ON t.team_id = res.team_id
WHERE res.race_id = %s AND res.finish_position <= 3
ORDER BY res.finish_position;
"""

SEASON_STATS = """
SELECT (SELECT COUNT(*) FROM hfg_races r WHERE r.season_id = %(sid)s AND r.is_upcoming = FALSE) AS completed,
       (SELECT COUNT(*) FROM hfg_races r WHERE r.season_id = %(sid)s) AS total_races,
       (SELECT COUNT(DISTINCT res.driver_id) FROM hfg_results res
          JOIN hfg_races r ON r.race_id = res.race_id WHERE r.season_id = %(sid)s) AS drivers,
       (SELECT COUNT(*) FROM hfg_reviews) AS reviews;
"""

NEXT_RACE = """
SELECT r.race_id, r.name, r.round, r.race_date, r.race_time,
       c.name AS circuit, c.country, s.year
FROM hfg_races r
JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
JOIN hfg_seasons  s ON s.season_id = r.season_id
WHERE r.is_upcoming = TRUE AND r.race_date >= CURRENT_DATE
ORDER BY r.race_date
LIMIT 1;
"""


@bp.route("/")
def index():
    season = db.query(CURRENT_SEASON, one=True)
    ctx = {"season": season}
    if season:
        sid = season["season_id"]
        ctx["driver_leader"] = db.query(DRIVER_LEADER, (sid,), one=True)
        ctx["team_leader"] = db.query(TEAM_LEADER, (sid,), one=True)
        ctx["stats"] = db.query(SEASON_STATS, {"sid": sid}, one=True)
        last = db.query(LAST_RACE, (sid,), one=True)
        ctx["last_race"] = last
        ctx["podium"] = db.query(PODIUM, (last["race_id"],)) if last else []

    nxt = db.query(NEXT_RACE, one=True)
    ctx["next_race"] = nxt
    if nxt:
        # stored in UTC
        t = nxt["race_time"] or time(13, 0)
        ctx["next_iso"] = datetime.combine(nxt["race_date"], t).isoformat() + "Z" # "Z" lets the browser convert to the visitor's time zone
    else:
        ctx["next_iso"] = None

    return render_template("home.html", **ctx)


@bp.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    drivers = races = []
    if q:
        like = f"%{q}%"
        drivers = db.query(
            """SELECT d.driver_id, d.first_name, d.last_name, t.name AS team
               FROM hfg_drivers d LEFT JOIN hfg_teams t ON t.team_id = d.team_id
               WHERE d.first_name ILIKE %s OR d.last_name ILIKE %s
                  OR (d.first_name || ' ' || d.last_name) ILIKE %s
               ORDER BY d.last_name LIMIT 30""",
            (like, like, like),
        )
        races = db.query(
            """SELECT r.race_id, r.name, r.race_date, s.year, c.country
               FROM hfg_races r
               JOIN hfg_seasons s ON s.season_id = r.season_id
               JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
               WHERE r.name ILIKE %s OR c.name ILIKE %s OR c.country ILIKE %s
               ORDER BY r.race_date DESC LIMIT 30""",
            (like, like, like),
        )
    return render_template("search.html", q=q, drivers=drivers, races=races)