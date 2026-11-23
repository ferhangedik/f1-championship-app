#tests/performance.py — Measures the execution time of the main queries.
""""
Each query is run with EXPLAIN (ANALYZE) 25 times; the median planning and execution times reported by PostgreSQL are written to tests/performance.json.
    python tests/performance.py
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db_standalone as dbs

QUERIES = [
    ("Driver standings (hfg_fn_driver_standings)", "SELECT * FROM hfg_fn_driver_standings(%(s)s)"),
    ("Constructor standings (hfg_fn_constructor_standings)", "SELECT * FROM hfg_fn_constructor_standings(%(s)s)"),
    ("Race detail: results of one race",
     """SELECT res.*, d.first_name, d.last_name, t.name FROM hfg_results res
        JOIN hfg_drivers d ON d.driver_id = res.driver_id LEFT JOIN hfg_teams t ON t.team_id = res.team_id
        WHERE res.race_id = %(r)s ORDER BY res.finish_position NULLS LAST"""),
    ("Driver profile: cumulative points (window function)",
     """SELECT r.round, COALESCE(vp.points, 0),
               SUM(COALESCE(vp.points, 0)) OVER (ORDER BY r.round)
        FROM hfg_races r LEFT JOIN hfg_v_round_points vp ON vp.race_id = r.race_id AND vp.driver_id = %(d)s
        WHERE r.season_id = %(s)s AND NOT r.is_upcoming ORDER BY r.round"""),
    ("Search (ILIKE on drivers)",
     """SELECT driver_id FROM hfg_drivers WHERE first_name ILIKE %(q)s OR last_name ILIKE %(q)s"""),
    ("Dashboard: season statistics (scalar sub-queries)",
     """SELECT (SELECT COUNT(*) FROM hfg_races WHERE season_id = %(s)s AND NOT is_upcoming),
               (SELECT COUNT(*) FROM hfg_races WHERE season_id = %(s)s),
               (SELECT COUNT(DISTINCT res.driver_id) FROM hfg_results res JOIN hfg_races r
                  ON r.race_id = res.race_id WHERE r.season_id = %(s)s)"""),
]


def main():
    out = []
    with dbs.connect() as conn:
        s = conn.execute("SELECT season_id FROM hfg_seasons WHERE year = 2025").fetchone()["season_id"]
        r = conn.execute("SELECT race_id FROM hfg_races WHERE season_id = %s ORDER BY round LIMIT 1",
                         (s,)).fetchone()["race_id"]
        d = conn.execute("SELECT driver_id FROM hfg_drivers WHERE last_name = 'Norris'").fetchone()["driver_id"]
        params = {"s": s, "r": r, "d": d, "q": "%nor%"}
        for name, sql in QUERIES:
            plan, exe, rows = [], [], 0
            for _ in range(25):
                res = conn.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, params).fetchone()
                doc = list(res.values())[0][0]
                plan.append(doc["Planning Time"]); exe.append(doc["Execution Time"])
                rows = doc["Plan"].get("Actual Rows", 0)
            out.append({"query": name, "planning_ms": round(statistics.median(plan), 3),
                        "execution_ms": round(statistics.median(exe), 3), "rows": rows})
            print(f"{name:<55} plan {out[-1]['planning_ms']:>7} ms  exec {out[-1]['execution_ms']:>7} ms  rows {rows}")
    pages = http_timings(r, d)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "performance.json"), "w") as f:
        json.dump({"queries": out, "pages": pages}, f, indent=2)


def http_timings(race_id, driver_id, base="http://127.0.0.1:8080"):
    """Median server response time of the main pages (application running locally)."""
    import time
    import urllib.request
    pages = []
    for url in ["/", "/standings/", f"/races/{race_id}", f"/drivers/{driver_id}",
                "/compare/teammates", "/analytics/"]:
        times = []
        for _ in range(15):
            t0 = time.perf_counter()
            with urllib.request.urlopen(base + url, timeout=10) as resp:
                resp.read()
            times.append((time.perf_counter() - t0) * 1000)
        pages.append({"url": url, "median_ms": round(statistics.median(times), 1),
                      "max_ms": round(max(times), 1)})
        print(f"{url:<25} median {pages[-1]['median_ms']} ms, max {pages[-1]['max_ms']} ms")
    return pages


if __name__ == "__main__":
    main()