#routes/races.py — Race list and race detail pages.
#The detail page has four sections: results, sprint (on sprint weekends), qualifying and pit stops.

from flask import Blueprint, render_template, abort
import db
from routes.common import resolve_season

bp = Blueprint("races", __name__, url_prefix="/races")


RACE_LIST = """
SELECT r.race_id, r.round, r.name, r.race_date, r.is_upcoming,
       c.name AS circuit, c.country,
       COUNT(res.result_id) AS result_count
FROM hfg_races r
JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
LEFT JOIN hfg_results res ON res.race_id = r.race_id
WHERE r.season_id = %s
GROUP BY r.race_id, c.name, c.country
ORDER BY r.round;
"""

RACE_HEADER = """
SELECT r.race_id, r.name, r.round, r.race_date, r.race_time, r.is_upcoming,
       s.year, c.name AS circuit, c.location, c.country, c.wiki_url AS circuit_url
FROM hfg_races r
JOIN hfg_seasons s ON s.season_id = r.season_id
JOIN hfg_circuits c ON c.circuit_id = r.circuit_id
WHERE r.race_id = %s;
"""

# Results: non-finishers (DNF, finish_position IS NULL) are pushed to the end.
RACE_RESULTS = """
SELECT res.finish_position, res.grid_position, res.points, res.status,
       res.fastest_lap_time, res.is_fastest_lap,
       d.driver_id, d.first_name, d.last_name,
       t.name AS team
FROM hfg_results res
JOIN hfg_drivers d ON d.driver_id = res.driver_id
LEFT JOIN hfg_teams t ON t.team_id = res.team_id
WHERE res.race_id = %s
ORDER BY res.finish_position ASC NULLS LAST;
"""

RACE_SPRINT = """
SELECT spr.finish_position, spr.grid_position, spr.points, spr.status,
       d.driver_id, d.first_name, d.last_name, t.name AS team
FROM hfg_sprint_results spr
JOIN hfg_drivers d ON d.driver_id = spr.driver_id
LEFT JOIN hfg_teams t ON t.team_id = spr.team_id
WHERE spr.race_id = %s
ORDER BY spr.finish_position ASC NULLS LAST;
"""

# The team is taken from the driver's result in this race (not the current team).
RACE_QUALIFYING = """
SELECT q.q1_time, q.q2_time, q.q3_time, q.grid_position,
       d.driver_id, d.first_name, d.last_name, t.name AS team
FROM hfg_qualifying q
JOIN hfg_drivers d ON d.driver_id = q.driver_id
LEFT JOIN hfg_results res ON res.race_id = q.race_id AND res.driver_id = q.driver_id
LEFT JOIN hfg_teams t ON t.team_id = COALESCE(res.team_id, d.team_id)
WHERE q.race_id = %s
ORDER BY q.grid_position ASC NULLS LAST;
"""

RACE_PITSTOPS = """
SELECT p.stop_number, p.lap, p.duration,
       d.driver_id, d.first_name, d.last_name
FROM hfg_pit_stops p
JOIN hfg_drivers d ON d.driver_id = p.driver_id
WHERE p.race_id = %s
ORDER BY d.last_name, p.stop_number;
"""

@bp.route("/")
def index():
    season, seasons = resolve_season()
    races = db.query(RACE_LIST, (season["season_id"],)) if season else []
    return render_template("races/index.html",
                           season=season, seasons=seasons, races=races)


@bp.route("/<int:race_id>")
def detail(race_id):
    race = db.query(RACE_HEADER, (race_id,), one=True)
    if not race:
        abort(404)

    results = db.query(RACE_RESULTS, (race_id,))
    sprint = db.query(RACE_SPRINT, (race_id,))
    qualifying = db.query(RACE_QUALIFYING, (race_id,))
    pit_stops = db.query(RACE_PITSTOPS, (race_id,))

    return render_template(
        "races/detail.html",
        race=race, results=results, sprint=sprint, qualifying=qualifying,
        pit_stops=pit_stops,
    )