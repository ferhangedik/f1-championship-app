#routes/analytics.py — Season-based race analytics.
"""""
(1) Grid effect (scatter): starting grid position vs finishing position -> overtaking patterns.
(2) Pit-stop chart: total pit stops per race and the average per driver. (Because FastF1 pit duration can be NULL, the count is used as the basis.)
(3) Fastest laps table: round, race, driver, team, lap time.
"""

from flask import Blueprint, render_template
import db
from routes.common import resolve_season

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

GRID_EFFECT = """
SELECT res.grid_position AS grid, res.finish_position AS finish
FROM hfg_results res
JOIN hfg_races r ON r.race_id = res.race_id
WHERE r.season_id = %s
  AND res.grid_position IS NOT NULL
  AND res.finish_position IS NOT NULL
  AND res.grid_position > 0;
"""

# Based on pit-stop count (duration can be NULL). Average per driver = total pit stops / number of distinct drivers who pitted.
PITSTOP_SUMMARY = """
SELECT r.round, r.name,
       COUNT(p.pit_stop_id) AS total_stops,
       ROUND(COUNT(p.pit_stop_id)::numeric
             / NULLIF(COUNT(DISTINCT p.driver_id), 0), 2) AS avg_per_driver
FROM hfg_races r
LEFT JOIN hfg_pit_stops p ON p.race_id = r.race_id
WHERE r.season_id = %s AND r.is_upcoming = FALSE
GROUP BY r.round, r.name
ORDER BY r.round;
"""

FASTEST_LAPS = """
SELECT r.round, r.name AS race,
       d.first_name, d.last_name,
       t.name AS team,
       res.fastest_lap_time
FROM hfg_results res
JOIN hfg_races r   ON r.race_id = res.race_id
JOIN hfg_drivers d ON d.driver_id = res.driver_id
LEFT JOIN hfg_teams t ON t.team_id = res.team_id
WHERE r.season_id = %s AND res.is_fastest_lap = TRUE
ORDER BY r.round;
"""


@bp.route("/")
def index():
    season, seasons = resolve_season()
    grid = pits = fastest = []
    if season:
        sid = season["season_id"]
        grid = db.query(GRID_EFFECT, (sid,))
        pits = db.query(PITSTOP_SUMMARY, (sid,))
        fastest = db.query(FASTEST_LAPS, (sid,))

    # {x: grid, y: finish} points for the scatter chart
    grid_points = [{"x": g["grid"], "y": g["finish"]} for g in grid]
    pit_labels = [f"R{p['round']}" for p in pits]
    pit_totals = [int(p["total_stops"]) for p in pits]
    pit_avgs = [float(p["avg_per_driver"] or 0) for p in pits]

    return render_template(
        "analytics/index.html",
        season=season, seasons=seasons,
        grid_points=grid_points,
        pit_labels=pit_labels, pit_totals=pit_totals, pit_avgs=pit_avgs,
        fastest=fastest,
    )