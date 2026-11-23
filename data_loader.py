"""
data_loader.py — Alternative loader based on the FastF1 library.

The main loader of the project is ergast_loader.py. This script reads the same
sessions through FastF1 (timing data of Formula 1) and is used
  - to add the drivers' official headshot photos, which the Jolpica-F1 API
    does not provide, and
  - as a second, independent source for checking the loaded results.

It writes to the same tables with the same upsert logic, so both loaders can
be run in any order. Races that are already in the calendar are not changed;
their results, sprint results, qualifying and pit-stop laps are stored.

Usage:
    python data_loader.py --season 2026 --round 1     # one race weekend
    python data_loader.py --season 2025 --all         # a whole season (slow)
    python data_loader.py --season 2026 --round 20 --photos-only
                                                      # only the drivers' photos;
                                                      # results stay as loaded by
                                                      # ergast_loader.py

Notes:
- FastF1 keeps downloaded sessions in cache/, so a session is fetched only once.
- FastF1 gives no reliable pit-stop duration, so it is stored as NULL.
- hfg_drivers.team_id (current team) is maintained by the trigger
  hfg_trg_results_sync_team, so loading an older season never overwrites it.
"""

import argparse
import os
import unicodedata
import warnings
from datetime import date

import db_standalone as dbs

warnings.filterwarnings("ignore")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
NOT_CLASSIFIED = ("R", "D", "E", "W", "F", "N")   # retired, disqualified, excluded, ...


# Conversion helpers
def norm(s):
    """Lowercase and strip accents, so 'Hülkenberg' == 'Hulkenberg', 'Pérez' == 'Perez'."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def fmt_lap(td):
    """pandas Timedelta -> 'M:SS.mmm' text; None if empty."""
    import pandas as pd
    if td is None or pd.isna(td) or td.total_seconds() <= 0:
        return None
    total = td.total_seconds()
    return f"{int(total // 60)}:{total % 60:06.3f}"


def to_int(val):
    import pandas as pd
    try:
        return None if val is None or pd.isna(val) else int(val)
    except (ValueError, TypeError):
        return None


def to_float(val):
    import pandas as pd
    try:
        return None if val is None or pd.isna(val) else float(val)
    except (ValueError, TypeError):
        return None


# Find the stored row or create it
def team_for(cur, name):
    name = name or "Unknown"
    cur.execute(
        """INSERT INTO hfg_teams (name) VALUES (%s)
           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
           RETURNING team_id""",
        (name,),
    )
    return cur.fetchone()["team_id"]


def driver_for(cur, first_name, last_name, team_id, photo_url):
    """Match a driver accent-insensitively by last name and first name, where one
    first name may contain the other ('Kimi' and 'Andrea Kimi'); insert if missing.
    The headshot photo is stored when FastF1 provides one."""
    cur.execute("SELECT driver_id, first_name, last_name FROM hfg_drivers")
    first, last = norm(first_name), norm(last_name)
    for row in cur.fetchall():
        f = norm(row["first_name"])
        if norm(row["last_name"]) == last and (f == first or first in f or f in first):
            if photo_url:
                cur.execute(
                    """UPDATE hfg_drivers SET photo_url = %s
                       WHERE driver_id = %s AND photo_url IS DISTINCT FROM %s""",
                    (photo_url, row["driver_id"], photo_url),
                )
            return row["driver_id"]
    cur.execute(
        """INSERT INTO hfg_drivers (first_name, last_name, team_id, photo_url)
           VALUES (%s, %s, %s, %s) RETURNING driver_id""",
        (first_name, last_name, team_id, photo_url),
    )
    return cur.fetchone()["driver_id"]


def race_for(cur, season_id, event):
    """Return (race_id, is_upcoming). A race missing from the calendar is inserted."""
    import pandas as pd
    rnd = int(event["RoundNumber"])
    cur.execute("SELECT race_id FROM hfg_races WHERE season_id = %s AND round = %s", (season_id, rnd))
    row = cur.fetchone()
    start = event.get("Session5DateUtc")
    start = None if start is None or pd.isna(start) else pd.Timestamp(start)
    race_date = start.date() if start is not None else pd.Timestamp(event["EventDate"]).date()
    if row:
        return row["race_id"], race_date > date.today()

    location, country = event.get("Location"), event.get("Country")
    cur.execute("SELECT circuit_id FROM hfg_circuits WHERE location = %s AND country = %s",
                (location, country))
    circuit = cur.fetchone()
    if not circuit:
        cur.execute(
            """INSERT INTO hfg_circuits (name, location, country) VALUES (%s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
               RETURNING circuit_id""",
            (f"{location} Circuit" if location else event["EventName"], location, country),
        )
        circuit = cur.fetchone()
    cur.execute(
        """INSERT INTO hfg_races (season_id, circuit_id, name, round, race_date, race_time)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING race_id""",
        (season_id, circuit["circuit_id"], event["EventName"], rnd, race_date,
         start.time() if start is not None else None),
    )
    return cur.fetchone()["race_id"], race_date > date.today()


# One race weekend
def load_round(cur, ff1, year, season_id, event):
    import pandas as pd

    rnd = int(event["RoundNumber"])
    race_id, upcoming = race_for(cur, season_id, event)
    print(f"  Round {rnd:>2}: {event['EventName']}{' [upcoming]' if upcoming else ''}")
    if upcoming:
        return  # calendar entry only

    # Race results and pit-stop laps
    session = ff1.get_session(year, rnd, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    laps = session.laps
    best = laps.pick_fastest() if len(laps) else None
    best_driver = best["Driver"] if best is not None and not pd.isna(best["LapTime"]) else None

    for _, r in session.results.iterrows():
        team_id = team_for(cur, r.get("TeamName"))
        driver_id = driver_for(cur, r.get("FirstName") or "", r.get("LastName") or "",
                               team_id, r.get("HeadshotUrl") or None)
        finish = to_int(r.get("Position"))
        if str(r.get("ClassifiedPosition") or "") in NOT_CLASSIFIED:
            finish = None
        own = laps.pick_drivers(r["DriverNumber"]) if len(laps) else laps
        own_best = own.pick_fastest() if len(own) else None
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
            (race_id, driver_id, team_id, to_int(r.get("GridPosition")), finish,
             to_float(r.get("Points")) or 0, r.get("Status") or "Finished",
             fmt_lap(own_best["LapTime"]) if own_best is not None else None,
             r.get("Abbreviation") == best_driver),
        )
        for stop, (_, lap) in enumerate(own[own["PitInTime"].notna()].iterrows(), start=1):
            cur.execute(
                """INSERT INTO hfg_pit_stops (race_id, driver_id, stop_number, lap, duration)
                   VALUES (%s,%s,%s,%s,NULL)
                   ON CONFLICT (race_id, driver_id, stop_number) DO UPDATE SET lap=EXCLUDED.lap""",
                (race_id, driver_id, stop, to_int(lap["LapNumber"]) or 0),
            )

    # Sprint (sprint weekends only)
    if "sprint" in str(event.get("EventFormat") or "").lower():
        sprint = ff1.get_session(year, rnd, "S")
        sprint.load(laps=False, telemetry=False, weather=False, messages=False)
        for _, r in sprint.results.iterrows():
            team_id = team_for(cur, r.get("TeamName"))
            driver_id = driver_for(cur, r.get("FirstName") or "", r.get("LastName") or "",
                                   team_id, r.get("HeadshotUrl") or None)
            finish = to_int(r.get("Position"))
            if str(r.get("ClassifiedPosition") or "") in NOT_CLASSIFIED:
                finish = None
            cur.execute(
                """INSERT INTO hfg_sprint_results
                     (race_id, driver_id, team_id, grid_position, finish_position, points, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (race_id, driver_id) DO UPDATE SET
                      team_id=EXCLUDED.team_id, grid_position=EXCLUDED.grid_position,
                      finish_position=EXCLUDED.finish_position, points=EXCLUDED.points,
                      status=EXCLUDED.status""",
                (race_id, driver_id, team_id, to_int(r.get("GridPosition")), finish,
                 to_float(r.get("Points")) or 0, r.get("Status") or "Finished"),
            )

    # Qualifying
    quali = ff1.get_session(year, rnd, "Q")
    quali.load(laps=False, telemetry=False, weather=False, messages=False)
    for _, q in quali.results.iterrows():
        team_id = team_for(cur, q.get("TeamName"))
        driver_id = driver_for(cur, q.get("FirstName") or "", q.get("LastName") or "",
                               team_id, q.get("HeadshotUrl") or None)
        cur.execute(
            """INSERT INTO hfg_qualifying (race_id, driver_id, q1_time, q2_time, q3_time, grid_position)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (race_id, driver_id) DO UPDATE SET
                  q1_time=EXCLUDED.q1_time, q2_time=EXCLUDED.q2_time,
                  q3_time=EXCLUDED.q3_time, grid_position=EXCLUDED.grid_position""",
            (race_id, driver_id, fmt_lap(q.get("Q1")), fmt_lap(q.get("Q2")), fmt_lap(q.get("Q3")),
             to_int(q.get("Position"))),
        )


def load_photos(cur, ff1, year, event):
    """Store the drivers' headshot URLs of one race weekend and nothing else.

    Results, qualifying and pit stops stay exactly as the main loader
    (ergast_loader.py) stored them; drivers missing from the database are skipped.
    """
    import pandas as pd

    rnd = int(event["RoundNumber"])
    if pd.Timestamp(event["EventDate"]).date() > date.today():
        return 0
    session = ff1.get_session(year, rnd, "R")
    session.load(laps=False, telemetry=False, weather=False, messages=False)

    cur.execute("SELECT driver_id, first_name, last_name FROM hfg_drivers")
    stored = cur.fetchall()
    updated = 0
    for _, r in session.results.iterrows():
        url = r.get("HeadshotUrl") or None
        if not url:
            continue
        first, last = norm(str(r.get("FirstName") or "")), norm(str(r.get("LastName") or ""))
        for row in stored:
            f = norm(row["first_name"])
            if norm(row["last_name"]) == last and (f == first or first in f or f in first):
                cur.execute(
                    """UPDATE hfg_drivers SET photo_url = %s
                       WHERE driver_id = %s AND photo_url IS DISTINCT FROM %s""",
                    (url, row["driver_id"], url),
                )
                updated += cur.rowcount
                break
    print(f"  Round {rnd:>2}: {event['EventName']} - {updated} photo(s) updated")
    return updated


def main():
    parser = argparse.ArgumentParser(description="FastF1 -> PostgreSQL loader")
    parser.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    parser.add_argument("--all", action="store_true", help="load all races of the season")
    parser.add_argument("--round", type=int, help="load only one race (round)")
    parser.add_argument("--photos-only", action="store_true",
                        help="only store the drivers' headshot photos; leave all results unchanged")
    args = parser.parse_args()
    if not args.all and args.round is None:
        parser.error("specify --all or --round <N>")

    os.makedirs(CACHE_DIR, exist_ok=True)
    import fastf1 as ff1          # imported late: it loads pandas and is slow to start
    ff1.Cache.enable_cache(CACHE_DIR)

    print(f"== Loading {args.season} with FastF1 ==")
    schedule = ff1.get_event_schedule(args.season, include_testing=False)
    conn = dbs.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hfg_seasons (year) VALUES (%s)
                   ON CONFLICT (year) DO UPDATE SET year = EXCLUDED.year
                   RETURNING season_id""",
                (args.season,),
            )
            season_id = cur.fetchone()["season_id"]
            for _, event in schedule.iterrows():
                rnd = int(event["RoundNumber"])
                if rnd == 0 or (args.round is not None and rnd != args.round):
                    continue
                try:
                    if args.photos_only:
                        load_photos(cur, ff1, args.season, event)
                    else:
                        load_round(cur, ff1, args.season, season_id, event)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    print(f"  ! round {rnd} skipped: {exc}")
        print("== Done ==")
    finally:
        conn.close()


if __name__ == "__main__":
    main()