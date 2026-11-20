#routes/drivers.py — Driver list and driver profile pages.
"""
The profile page shows an info card, career statistics (races, wins, podiums, poles, total points) and a per-race + cumulative points chart (Chart.js) for the selected season. 
The cumulative points are computed in SQL with a window function.
"""

from flask import Blueprint, render_template, abort, request
import db

bp = Blueprint("drivers", __name__, url_prefix="/drivers")


DRIVER_LIST = """
SELECT d.driver_id, d.first_name, d.last_name, d.nationality,
       t.name AS team
FROM hfg_drivers d
LEFT JOIN hfg_teams t ON t.team_id = d.team_id
ORDER BY d.last_name, d.first_name;
"""

DRIVER_CARD = """
SELECT d.driver_id, d.first_name, d.last_name, d.date_of_birth,
       d.nationality, d.photo_url, d.wiki_url, t.name AS team
FROM hfg_drivers d
LEFT JOIN hfg_teams t ON t.team_id = d.team_id
WHERE d.driver_id = %s;
"""

# Career statistics: conditional counts with FILTER (across all seasons).
# Points come from hfg_v_round_points, so sprint points are included.
CAREER_STATS = """
SELECT COUNT(*)                                          AS races,
       COUNT(*) FILTER (WHERE finish_position = 1)       AS wins,
       COUNT(*) FILTER (WHERE finish_position <= 3)      AS podiums,
       COUNT(*) FILTER (WHERE grid_position = 1)         AS poles,
       (SELECT COALESCE(SUM(vp.points), 0)
          FROM hfg_v_round_points vp WHERE vp.driver_id = %(d)s) AS points
FROM hfg_results
WHERE driver_id = %(d)s;
"""

# Seasons the driver competed in (for the profile season selector)
DRIVER_SEASONS = """
SELECT DISTINCT s.season_id, s.year
FROM hfg_seasons s
JOIN hfg_races r   ON r.season_id = s.season_id
JOIN hfg_results res ON res.race_id = r.race_id
WHERE res.driver_id = %s
ORDER BY s.year DESC;
"""

# Per-round points (Grand Prix + sprint) + cumulative within a season (window function).
SEASON_PROGRESS = """
SELECT r.round, r.name,
       COALESCE(vp.points, 0)                                     AS points,
       res.finish_position,
       SUM(COALESCE(vp.points, 0)) OVER (ORDER BY r.round)        AS cumulative
FROM hfg_races r
LEFT JOIN hfg_v_round_points vp
       ON vp.race_id = r.race_id AND vp.driver_id = %(d)s
LEFT JOIN hfg_results res
       ON res.race_id = r.race_id AND res.driver_id = %(d)s
WHERE r.season_id = %(s)s AND r.is_upcoming = FALSE
ORDER BY r.round;
"""


@bp.route("/")
def index():
    drivers = db.query(DRIVER_LIST)
    return render_template("drivers/index.html", drivers=drivers)


@bp.route("/<int:driver_id>")
def profile(driver_id):
    driver = db.query(DRIVER_CARD, (driver_id,), one=True)
    if not driver:
        abort(404)

    stats = db.query(CAREER_STATS, {"d": driver_id}, one=True)
    seasons = db.query(DRIVER_SEASONS, (driver_id,))

    # Selected season: ?season=<id> or the most recent season they competed in
    sel_id = request.args.get("season", type=int)
    season = None
    if sel_id:
        season = next((s for s in seasons if s["season_id"] == sel_id), None)
    if season is None and seasons:
        season = seasons[0]

    progress = (db.query(SEASON_PROGRESS, {"d": driver_id, "s": season["season_id"]})
                if season else [])

    # Arrays for Chart.js
    labels = [f"R{p['round']}" for p in progress]
    points = [float(p["points"]) for p in progress]
    cumulative = [float(p["cumulative"]) for p in progress]

    return render_template(
        "drivers/profile.html",
        driver=driver, stats=stats, seasons=seasons, season=season,
        labels=labels, points=points, cumulative=cumulative,
    )