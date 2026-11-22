#routes/compare.py — Compare two drivers (and teammates) over a season.

from flask import Blueprint, render_template, request
import db
from routes.common import all_seasons

bp = Blueprint("compare", __name__, url_prefix="/compare")

DRIVER_OPTIONS = """
SELECT d.driver_id, d.first_name, d.last_name
FROM hfg_drivers d
ORDER BY d.last_name, d.first_name;
"""

# Points (Grand Prix + sprint) of one driver in one season, from hfg_v_round_points.
SEASON_POINTS = """
(SELECT COALESCE(SUM(vp.points), 0)
   FROM hfg_v_round_points vp JOIN hfg_races r2 ON r2.race_id = vp.race_id
  WHERE vp.driver_id = %(d)s AND r2.season_id = %(s)s)"""

SEASON_STATS = """
SELECT COUNT(*) FILTER (WHERE res.finish_position = 1)  AS wins,
       COUNT(*) FILTER (WHERE res.finish_position <= 3) AS podiums,
       """ + SEASON_POINTS + """ AS points,
       COUNT(*)                                         AS races
FROM hfg_results res
JOIN hfg_races r ON r.race_id = res.race_id
WHERE res.driver_id = %(d)s AND r.season_id = %(s)s;
"""

SEASON_PROGRESS = """
SELECT r.round,
       COALESCE(vp.points, 0) AS points,
       res.finish_position
FROM hfg_races r
LEFT JOIN hfg_v_round_points vp
       ON vp.race_id = r.race_id AND vp.driver_id = %(d)s
LEFT JOIN hfg_results res
       ON res.race_id = r.race_id AND res.driver_id = %(d)s
WHERE r.season_id = %(s)s AND r.is_upcoming = FALSE
ORDER BY r.round;
"""


def _driver_name(driver_id):
    row = db.query("SELECT first_name, last_name FROM hfg_drivers WHERE driver_id=%s",
                   (driver_id,), one=True)
    return f"{row['first_name']} {row['last_name']}" if row else "?"


TEAMS_IN_SEASON = """
SELECT DISTINCT t.team_id, t.name
FROM hfg_results res
JOIN hfg_races r ON r.race_id = res.race_id
JOIN hfg_teams t ON t.team_id = res.team_id
WHERE r.season_id = %s
ORDER BY t.name;
"""

TEAM_DRIVERS = """
SELECT d.driver_id, d.first_name, d.last_name, COUNT(*) AS races
FROM hfg_results res
JOIN hfg_races r   ON r.race_id = res.race_id
JOIN hfg_drivers d ON d.driver_id = res.driver_id
WHERE r.season_id = %s AND res.team_id = %s
GROUP BY d.driver_id
ORDER BY races DESC, d.last_name
LIMIT 2;
"""

TEAMMATE_STATS = """
SELECT COUNT(*)                                          AS races,
       """ + SEASON_POINTS + """ AS points,
       COUNT(*) FILTER (WHERE res.finish_position = 1)   AS wins,
       COUNT(*) FILTER (WHERE res.finish_position <= 3)  AS podiums,
       ROUND(AVG(res.finish_position), 1)                AS avg_finish
FROM hfg_results res
JOIN hfg_races r ON r.race_id = res.race_id
WHERE r.season_id = %(s)s AND res.driver_id = %(d)s;
"""

TEAMMATE_ROUNDS = """
SELECT r.round, res.driver_id, res.finish_position, res.grid_position,
       COALESCE(vp.points, 0) AS points
FROM hfg_results res
JOIN hfg_races r ON r.race_id = res.race_id
LEFT JOIN hfg_v_round_points vp
       ON vp.race_id = res.race_id AND vp.driver_id = res.driver_id
WHERE r.season_id = %s AND res.driver_id IN (%s, %s)
ORDER BY r.round;
"""


@bp.route("/")
def index():
    drivers = db.query(DRIVER_OPTIONS)
    seasons = all_seasons()

    d1 = request.args.get("driver1", type=int)
    d2 = request.args.get("driver2", type=int)
    sel_id = request.args.get("season", type=int)
    season = None
    if sel_id:
        season = next((s for s in seasons if s["season_id"] == sel_id), None)
    if season is None and seasons:
        season = seasons[0]

    data = None
    if d1 and d2 and season:
        sid = season["season_id"]
        prog1 = db.query(SEASON_PROGRESS, {"d": d1, "s": sid})
        prog2 = db.query(SEASON_PROGRESS, {"d": d2, "s": sid})
        labels = [f"R{p['round']}" for p in prog1]
        data = {
            "labels": labels,
            "name1": _driver_name(d1),
            "name2": _driver_name(d2),
            "stats1": db.query(SEASON_STATS, {"d": d1, "s": sid}, one=True),
            "stats2": db.query(SEASON_STATS, {"d": d2, "s": sid}, one=True),
            "points1": [float(p["points"]) for p in prog1],
            "points2": [float(p["points"]) for p in prog2],
            # When there is no finish (DNF) the value is None -> a gap in Chart.js
            "finish1": [p["finish_position"] for p in prog1],
            "finish2": [p["finish_position"] for p in prog2],
        }

    return render_template(
        "drivers/compare.html",
        drivers=drivers, seasons=seasons, season=season,
        d1=d1, d2=d2, data=data,
    )


@bp.route("/teammates")
def teammates():
    seasons = all_seasons()
    sel_id = request.args.get("season", type=int)
    season = None
    if sel_id:
        season = next((s for s in seasons if s["season_id"] == sel_id), None)
    if season is None and seasons:
        season = seasons[0]

    teams = db.query(TEAMS_IN_SEASON, (season["season_id"],)) if season else []
    team_id = request.args.get("team", type=int)
    if team_id is None and teams:
        team_id = teams[0]["team_id"]

    data = None
    if season and team_id:
        sid = season["season_id"]
        drivers = db.query(TEAM_DRIVERS, (sid, team_id))
        if len(drivers) >= 2:
            d1, d2 = drivers[0]["driver_id"], drivers[1]["driver_id"]
            rounds = db.query(TEAMMATE_ROUNDS, (sid, d1, d2))

            # Group by round and compute the head-to-head
            by_round = {}
            for row in rounds:
                by_round.setdefault(row["round"], {})[row["driver_id"]] = row

            def worse_if_none(v):
                return v if v is not None else 999  # DNF/missing = worst

            race_h2h = {d1: 0, d2: 0}
            quali_h2h = {d1: 0, d2: 0}
            labels, pts1, pts2 = [], [], []
            for rnd in sorted(by_round):
                pair = by_round[rnd]
                if d1 in pair and d2 in pair:
                    f1 = worse_if_none(pair[d1]["finish_position"])
                    f2 = worse_if_none(pair[d2]["finish_position"])
                    if f1 < f2:
                        race_h2h[d1] += 1
                    elif f2 < f1:
                        race_h2h[d2] += 1
                    g1 = worse_if_none(pair[d1]["grid_position"])
                    g2 = worse_if_none(pair[d2]["grid_position"])
                    if g1 < g2:
                        quali_h2h[d1] += 1
                    elif g2 < g1:
                        quali_h2h[d2] += 1
                labels.append(f"R{rnd}")
                pts1.append(float(pair[d1]["points"]) if d1 in pair else 0)
                pts2.append(float(pair[d2]["points"]) if d2 in pair else 0)

            team_name = next((t["name"] for t in teams if t["team_id"] == team_id), "")
            data = {
                "team_name": team_name,
                "name1": _driver_name(d1), "name2": _driver_name(d2),
                "stats1": db.query(TEAMMATE_STATS, {"d": d1, "s": sid}, one=True),
                "stats2": db.query(TEAMMATE_STATS, {"d": d2, "s": sid}, one=True),
                "race_h2h": (race_h2h[d1], race_h2h[d2]),
                "quali_h2h": (quali_h2h[d1], quali_h2h[d2]),
                "labels": labels, "pts1": pts1, "pts2": pts2,
            }

    return render_template("drivers/teammates.html",
                           seasons=seasons, season=season,
                           teams=teams, team_id=team_id, data=data)