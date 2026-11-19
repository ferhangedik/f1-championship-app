"""
ergast_loader.py — Loads a season from the Jolpica-F1 (Ergast) open API. - Got an help of AI on this for make it faster.

This is the main loader of the project. For one season it:
  1. creates the season if it is missing and aligns the stored calendar with the official one (round numbers, dates, start times, circuits)
  2. for every round that already has official results, stores the race results, sprint results, qualifying and pit stops
  3. creates missing drivers and teams and completes their details (nationality, date of birth, Wikipedia link)


Usage:
    python ergast_loader.py --season 2026            # all rounds that have results
    python ergast_loader.py --season 2026 --round 8  # a single round
"""

import argparse
import json
import time
import unicodedata
import urllib.error
import urllib.request

import db_standalone as dbs

API = "https://api.jolpi.ca/ergast/f1"


def norm(s):
    # Lowercase and strip accents, so 'Hülkenberg' == 'Hulkenberg', 'Pérez' == 'Perez'.
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def get_json(url, retries=6):
    req = urllib.request.Request(url, headers={"User-Agent": "hfg-f1-thesis-loader"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                time.sleep(0.3)
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fetch(year, rnd, kind):
    data = get_json(f"{API}/{year}/{rnd}/{kind}.json?limit=100")
    races = data["MRData"]["RaceTable"]["Races"]
    return races[0] if races else {}


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_duration(s):
    if not s:
        return None
    try:
        if ":" in s:
            m, sec = s.split(":")
            val = int(m) * 60 + float(sec)
        else:
            val = float(s)
        return val if 0 < val < 1000 else None
    except ValueError:
        return None


# Teams, circuits and drivers: find the stored row or create it

TEAM_NAMES = {
    "red_bull": "Red Bull Racing",
    "rb": "Racing Bulls",
    "sauber": "Kick Sauber",
    "alpine": "Alpine",
    "cadillac": "Cadillac",
}


def team_for(cur, constructor):
    name = TEAM_NAMES.get(constructor.get("constructorId"), constructor["name"])
    cur.execute("SELECT team_id, name, nationality, wiki_url FROM hfg_teams")
    for t in cur.fetchall():
        if norm(t["name"]) == norm(name):
            if t["nationality"] is None or t["wiki_url"] is None:
                cur.execute(
                    """UPDATE hfg_teams SET nationality = COALESCE(nationality, %s),
                                            wiki_url    = COALESCE(wiki_url, %s)
                       WHERE team_id = %s""",
                    (constructor.get("nationality"), constructor.get("url"), t["team_id"]),
                )
            return t["team_id"]
    cur.execute(
        "INSERT INTO hfg_teams (name, nationality, wiki_url) VALUES (%s, %s, %s) RETURNING team_id",
        (name, constructor.get("nationality"), constructor.get("url")),
    )
    return cur.fetchone()["team_id"]


def circuit_for(cur, circuit):
    loc = circuit.get("Location") or {}
    cur.execute(
        """SELECT circuit_id FROM hfg_circuits
           WHERE name = %s OR (location = %s AND country = %s)""",
        (circuit["circuitName"], loc.get("locality"), loc.get("country")),
    )
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE hfg_circuits SET wiki_url = COALESCE(wiki_url, %s) WHERE circuit_id = %s",
                    (circuit.get("url"), row["circuit_id"]))
        return row["circuit_id"]
    cur.execute(
        """INSERT INTO hfg_circuits (name, location, country, wiki_url)
           VALUES (%s, %s, %s, %s) RETURNING circuit_id""",
        (circuit["circuitName"], loc.get("locality"), loc.get("country"), circuit.get("url")),
    )
    return cur.fetchone()["circuit_id"]


def load_drivers(cur):
    cur.execute("SELECT driver_id, first_name, last_name FROM hfg_drivers")
    by_full, by_last = {}, {}
    for r in cur.fetchall():
        by_full[(norm(r["first_name"]), norm(r["last_name"]))] = r["driver_id"]
        by_last.setdefault(norm(r["last_name"]), r["driver_id"])
    return {"full": by_full, "last": by_last, "completed": set()}


def driver_for(cur, cache, d, team_id):
    given, family = d.get("givenName", ""), d["familyName"]
    driver_id = cache["full"].get((norm(given), norm(family))) or cache["last"].get(norm(family))
    if driver_id is None:
        cur.execute(
            """INSERT INTO hfg_drivers (first_name, last_name, date_of_birth, nationality, team_id, wiki_url)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING driver_id""",
            (given, family, d.get("dateOfBirth"), d.get("nationality"), team_id, d.get("url")),
        )
        driver_id = cur.fetchone()["driver_id"]
        cache["full"][(norm(given), norm(family))] = driver_id
        cache["last"][norm(family)] = driver_id
        cache["completed"].add(driver_id)
        print(f"     + new driver: {given} {family}")
    elif driver_id not in cache["completed"]:
        cur.execute(
            """UPDATE hfg_drivers
                  SET date_of_birth = COALESCE(date_of_birth, %s),
                      nationality   = COALESCE(nationality, %s),
                      wiki_url      = COALESCE(wiki_url, %s)
                WHERE driver_id = %s
                  AND (date_of_birth IS NULL OR nationality IS NULL OR wiki_url IS NULL)""",
            (d.get("dateOfBirth"), d.get("nationality"), d.get("url"), driver_id),
        )
        cache["completed"].add(driver_id)
    return driver_id



# Calendar
def sync_schedule(cur, year):
    cur.execute(
        """INSERT INTO hfg_seasons (year) VALUES (%s)
           ON CONFLICT (year) DO UPDATE SET year = EXCLUDED.year
           RETURNING season_id""",
        (year,),
    )
    sid = cur.fetchone()["season_id"]
    api_races = get_json(f"{API}/{year}.json?limit=100")["MRData"]["RaceTable"]["Races"]

    cur.execute("SELECT race_id, name, race_date FROM hfg_races WHERE season_id = %s", (sid,))
    stored = cur.fetchall()
    by_name = {norm(r["name"]): r for r in stored}
    by_date = {r["race_date"].isoformat(): r for r in stored}

    for api in api_races:
        rnd, name, day = int(api["round"]), api["raceName"], api["date"]
        start = (api.get("time") or "").rstrip("Z") or None      # 'HH:MM:SS' in UTC
        circuit_id = circuit_for(cur, api["Circuit"])
        row = by_name.get(norm(name)) or by_date.get(day)
        if row:
            cur.execute(
                """UPDATE hfg_races
                      SET round = %s, race_date = %s, race_time = %s, circuit_id = %s
                    WHERE race_id = %s
                      AND (round, race_date, race_time, circuit_id)
                          IS DISTINCT FROM (%s, %s::date, %s::time, %s)""",
                (rnd, day, start, circuit_id, row["race_id"], rnd, day, start, circuit_id),
            )
            if cur.rowcount:
                print(f"  calendar: {row['name']} -> round {rnd} ({day})")
        else:
            cur.execute(
                """INSERT INTO hfg_races (season_id, circuit_id, name, round, race_date, race_time)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (sid, circuit_id, name, rnd, day, start),
            )
            print(f"  calendar: + {name}, round {rnd} ({day})")
    return sid

# One round
def load_round(cur, cache, year, rnd):
    cur.execute(
        """SELECT r.race_id FROM hfg_races r
           JOIN hfg_seasons s ON s.season_id = r.season_id
           WHERE s.year = %s AND r.round = %s""",
        (year, rnd),
    )
    row = cur.fetchone()
    if not row:
        print(f"  R{rnd:>2}: not in the calendar, skipped")
        return False
    rid = row["race_id"]

    race = fetch(year, rnd, "results")
    results = race.get("Results") or []
    if not results:
        print(f"  R{rnd:>2}: no results yet, skipped")
        return False

    ids = {}  # API driverId -> our driver_id (the pit-stop list has only the driverId)
    for res in results:
        team_id = team_for(cur, res["Constructor"])
        driver_id = driver_for(cur, cache, res["Driver"], team_id)
        ids[res["Driver"]["driverId"]] = driver_id
        classified = res.get("positionText", "").isdigit()
        lap = res.get("FastestLap") or {}
        cur.execute(
            """INSERT INTO hfg_results
                 (race_id, driver_id, team_id, grid_position, finish_position,
                  points, status, fastest_lap_time, is_fastest_lap)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (race_id, driver_id) DO UPDATE SET
                  team_id=EXCLUDED.team_id, grid_position=EXCLUDED.grid_position,
                  finish_position=EXCLUDED.finish_position, points=EXCLUDED.points,
                  status=EXCLUDED.status, fastest_lap_time=EXCLUDED.fastest_lap_time,
                  is_fastest_lap=EXCLUDED.is_fastest_lap""",
            (rid, driver_id, team_id, to_int(res.get("grid")),
             to_int(res.get("position")) if classified else None,
             float(res.get("points") or 0), res.get("status") or "Finished",
             (lap.get("Time") or {}).get("time"), lap.get("rank") == "1"),
        )

    # Sprint (only on sprint weekends; other rounds return an empty list)
    sprint = fetch(year, rnd, "sprint").get("SprintResults") or []
    for res in sprint:
        team_id = team_for(cur, res["Constructor"])
        driver_id = driver_for(cur, cache, res["Driver"], team_id)
        classified = res.get("positionText", "").isdigit()
        cur.execute(
            """INSERT INTO hfg_sprint_results
                 (race_id, driver_id, team_id, grid_position, finish_position, points, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (race_id, driver_id) DO UPDATE SET
                  team_id=EXCLUDED.team_id, grid_position=EXCLUDED.grid_position,
                  finish_position=EXCLUDED.finish_position, points=EXCLUDED.points,
                  status=EXCLUDED.status""",
            (rid, driver_id, team_id, to_int(res.get("grid")),
             to_int(res.get("position")) if classified else None,
             float(res.get("points") or 0), res.get("status") or "Finished"),
        )

    # Qualifying
    for q in fetch(year, rnd, "qualifying").get("QualifyingResults") or []:
        team_id = team_for(cur, q["Constructor"])
        driver_id = driver_for(cur, cache, q["Driver"], team_id)
        cur.execute(
            """INSERT INTO hfg_qualifying (race_id, driver_id, q1_time, q2_time, q3_time, grid_position)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (race_id, driver_id) DO UPDATE SET
                  q1_time=EXCLUDED.q1_time, q2_time=EXCLUDED.q2_time,
                  q3_time=EXCLUDED.q3_time, grid_position=EXCLUDED.grid_position""",
            (rid, driver_id, q.get("Q1") or None, q.get("Q2") or None, q.get("Q3") or None,
             to_int(q.get("position"))),
        )

    # Pit stops
    for ps in fetch(year, rnd, "pitstops").get("PitStops") or []:
        if ps["driverId"] not in ids:
            continue
        cur.execute(
            """INSERT INTO hfg_pit_stops (race_id, driver_id, stop_number, lap, duration)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (race_id, driver_id, stop_number) DO UPDATE SET
                  lap=EXCLUDED.lap, duration=EXCLUDED.duration""",
            (rid, ids[ps["driverId"]], to_int(ps.get("stop")) or 1, to_int(ps.get("lap")) or 0,
             parse_duration(ps.get("duration"))),
        )

    # hfg_races.is_upcoming is cleared by the trigger hfg_trg_results_mark_completed
    extra = f", sprint {len(sprint)}" if sprint else ""
    print(f"  R{rnd:>2}: {race.get('raceName', '')} - {len(results)} results{extra}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Jolpica-F1 (Ergast) -> PostgreSQL loader")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, help="load a single round")
    args = parser.parse_args()

    conn = dbs.connect()
    loaded = 0
    try:
        with conn.cursor() as cur:
            print(f"== Loading {args.season} from Jolpica-F1 ==")
            sid = sync_schedule(cur, args.season)
            conn.commit()

            if args.round is not None:
                rounds = [args.round]
            else:
                cur.execute("SELECT round FROM hfg_races WHERE season_id = %s ORDER BY round", (sid,))
                rounds = [row["round"] for row in cur.fetchall()]

            cache = load_drivers(cur)
            for rnd in rounds:
                try:
                    if load_round(cur, cache, args.season, rnd):
                        loaded += 1
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    cache = load_drivers(cur)
                    print(f"  R{rnd:>2}: failed and rolled back ({exc})")
        print(f"== Done: {loaded} rounds loaded ==")
    finally:
        conn.close()


if __name__ == "__main__":
    main()