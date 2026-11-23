#tests/functional_tests.py — Functional and database tests of the application.
""""
Runs the Flask application in-process (Flask test client) against the real hfg_f1db database and checks the behaviour of every page, the authentication and
authorisation rules, the review and driver-management workflows (including invalid input), the database constraints and triggers, and the correctness of
the computed standings against the official Jolpica-F1 / Ergast data.

Everything the tests create is removed again at the end; constraint and trigger tests run inside transactions that are rolled back.

    python tests/functional_tests.py            # prints a table, writes results.json
"""

import json
import os
import sys
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from app import create_app
import db_standalone as dbs

# Test account used only by this script (created and deleted by it)
TEST_USER = "test_member"
TEST_PASSWORD = "test-member-pass"
ADMIN_USER = "admin"
ADMIN_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "admin123")

results = []


def record(tid, area, description, expected, actual, passed):
    tid = f"T{len(results) + 1:02d}"  # numbered in execution order
    results.append({"id": tid, "area": area, "description": description,
                    "expected": expected, "actual": actual, "passed": bool(passed)})
    print(f"{tid:<5} {'PASS' if passed else 'FAIL'}  {description}  ->  {actual}")


def one(sql, params=()):
    with dbs.connect() as conn:
        return conn.execute(sql, params).fetchone()


def text_of(resp):
    return resp.get_data(as_text=True)


def post(client, url, data=None, **kw):
    """POST like the browser does: with the session's anti-CSRF token."""
    with client.session_transaction() as sess:
        token = sess.setdefault("_csrf", "test-csrf-token")
    data = dict(data or {})
    data["csrf_token"] = token
    return client.post(url, data=data, **kw)


def login(client, user, password):
    return post(client, "/auth/login", {"username": user, "password": password},
                follow_redirects=True)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def main():
    app = create_app()
    app.config["TESTING"] = True

    completed = one("""SELECT r.race_id FROM hfg_races r JOIN hfg_seasons s USING (season_id)
                       WHERE NOT r.is_upcoming ORDER BY s.year DESC, r.round LIMIT 1""")["race_id"]
    upcoming = one("SELECT race_id FROM hfg_races WHERE is_upcoming ORDER BY race_date LIMIT 1")["race_id"]
    driver = one("SELECT driver_id FROM hfg_drivers ORDER BY driver_id LIMIT 1")["driver_id"]

    # Pages
    anon = app.test_client()
    pages = ["/", "/standings/", "/races/", f"/races/{completed}", "/drivers/",
             f"/drivers/{driver}", "/compare/?driver1=1&driver2=2", "/compare/teammates",
             "/analytics/", "/calendar/", "/search?q=monaco", "/auth/login", "/auth/register"]
    codes = {u: anon.get(u).status_code for u in pages}
    ok = all(c == 200 for c in codes.values())
    record("T01", "Pages", f"All {len(pages)} public pages respond", "HTTP 200 for every page",
           "all 200" if ok else str(codes), ok)

    r = anon.get("/no-such-page")
    record("T02", "Pages", "Unknown URL", "HTTP 404, themed error page",
           f"HTTP {r.status_code}", r.status_code == 404 and "F1" in text_of(r))
    r = anon.get("/races/999999")
    record("T03", "Pages", "Race id that does not exist", "HTTP 404", f"HTTP {r.status_code}",
           r.status_code == 404)

    # Authentication
    r = anon.get("/admin/")
    record("T04", "Authorisation", "Anonymous visitor opens /admin/", "Redirect to login",
           f"HTTP {r.status_code} -> {r.headers.get('Location')}",
           r.status_code == 302 and "/auth/login" in r.headers.get("Location", ""))

    r = post(anon, "/auth/register", data={"username": "ab", "password": "x"}, follow_redirects=True)
    record("T05", "Registration", "Username of 2 characters, password of 1", "Rejected with message",
           "rejected" if "at least 3" in text_of(r) else "accepted", "at least 3" in text_of(r))

    r = post(anon, "/auth/register", data={"username": ADMIN_USER, "password": "whatever"},
                  follow_redirects=True)
    record("T06", "Registration", "Username that already exists", "Rejected: name taken",
           "rejected" if "already taken" in text_of(r) else "accepted", "already taken" in text_of(r))

    r = post(anon, "/auth/register", data={"username": TEST_USER, "password": TEST_PASSWORD},
                  follow_redirects=True)
    row = one("SELECT password_hash FROM hfg_users WHERE username = %s", (TEST_USER,))
    hashed = bool(row) and row["password_hash"].startswith("scrypt:") and TEST_PASSWORD not in row["password_hash"]
    record("T07", "Registration", "Valid registration", "Account stored with a salted hash",
           "stored, scrypt hash" if hashed else "not stored", hashed)

    r = login(anon, TEST_USER, "wrong-password")
    record("T08", "Authentication", "Log in with a wrong password", "Rejected, generic message",
           "rejected" if "Invalid username or password" in text_of(r) else "accepted",
           "Invalid username or password" in text_of(r))

    r = post(anon, "/auth/login?next=//evil.example.com",
                  data={"username": TEST_USER, "password": TEST_PASSWORD})
    loc = r.headers.get("Location", "")
    record("T09", "Authentication", "Log in with an external ?next= target",
           "Logged in, redirected inside the site only", f"-> {loc}",
           r.status_code == 302 and "evil" not in loc)

    member = anon  # now logged in as the test member
    r = member.get("/admin/", follow_redirects=True)
    record("T10", "Authorisation", "Member (not admin) opens /admin/", "Access refused",
           "refused" if "restricted to the administrator" in text_of(r) else "allowed",
           "restricted to the administrator" in text_of(r))

    # Reviews
    r = post(member, f"/reviews/race/{upcoming}", data={"rating": 8, "comment": "early"},
                    follow_redirects=True)
    msg = "already taken place"
    record("T11", "Reviews", "Review of a race not yet held", "Rejected by trigger",
           "rejected" if msg in text_of(r) else "accepted", msg in text_of(r))

    for tid, rating in (("T12", 0), ("T13", 11)):
        r = post(member, f"/reviews/race/{completed}", data={"rating": rating}, follow_redirects=True)
        ok = "between 1 and 10" in text_of(r)
        record(tid, "Reviews", f"Rating {rating}", "Rejected by procedure",
               "rejected" if ok else "accepted", ok)

    post(member, f"/reviews/race/{completed}", data={"rating": 9, "comment": "Great race"})
    post(member, f"/reviews/race/{completed}", data={"rating": 7, "comment": "Second thoughts"})
    row = one("""SELECT COUNT(*) AS n, MAX(rating) AS rating FROM hfg_reviews rv JOIN hfg_users u USING (user_id)
                 WHERE u.username = %s AND rv.race_id = %s""", (TEST_USER, completed))
    record("T14", "Reviews", "Valid review, then resubmitted", "One review, updated to the new rating",
           f"{row['n']} review(s), rating {row['rating']}", row["n"] == 1 and row["rating"] == 7)

    admin = app.test_client()
    login(admin, ADMIN_USER, ADMIN_PASSWORD)
    post(admin, f"/reviews/race/{completed}", data={"rating": 10, "comment": "Admin review"})
    admin_review = one("""SELECT review_id FROM hfg_reviews rv JOIN hfg_users u USING (user_id)
                          WHERE u.username = %s AND rv.race_id = %s""", (ADMIN_USER, completed))
    r = post(member, f"/reviews/{admin_review['review_id']}/delete", follow_redirects=True)
    ok = "only delete your own review" in text_of(r)
    record("T15", "Reviews", "Member deletes another user's review", "Refused by procedure",
           "refused" if ok else "deleted", ok)

    own = one("""SELECT review_id FROM hfg_reviews rv JOIN hfg_users u USING (user_id)
                 WHERE u.username = %s AND rv.race_id = %s""", (TEST_USER, completed))
    post(member, f"/reviews/{own['review_id']}/delete")
    gone = one("SELECT 1 AS x FROM hfg_reviews WHERE review_id = %s", (own["review_id"],)) is None
    record("T16", "Reviews", "Member deletes own review", "Review removed",
           "removed" if gone else "still present", gone)
    post(admin, f"/reviews/{admin_review['review_id']}/delete")

    # Driver management
    cases = [
        ("T17", "Empty first name", {"first_name": " ", "last_name": "Tester"}, "are required"),
        ("T18", "Date of birth in the future",
         {"first_name": "Test", "last_name": "Tester", "date_of_birth": "2099-01-01"}, "in the future"),
        ("T19", "Malformed date of birth",
         {"first_name": "Test", "last_name": "Tester", "date_of_birth": "31-31-2000"},
         "must be a valid date"),
    ]
    for tid, label, form, msg in cases:
        r = post(admin, "/admin/drivers/new", data=form, follow_redirects=True)
        ok = msg in text_of(r)
        record(tid, "Admin CRUD", label, "Rejected with message", "rejected" if ok else "accepted", ok)

    team = one("SELECT team_id FROM hfg_teams ORDER BY team_id LIMIT 1")["team_id"]
    post(admin, "/admin/drivers/new", data={"first_name": "Test", "last_name": "Tester",
                                           "nationality": "POL", "team_id": team})
    new = one("SELECT driver_id FROM hfg_drivers WHERE first_name='Test' AND last_name='Tester'")
    post(admin, f"/admin/drivers/{new['driver_id']}/edit",
               data={"first_name": "Test", "last_name": "Tester", "nationality": "TUR", "team_id": team})
    post(admin, f"/admin/drivers/{new['driver_id']}/delete")
    with dbs.connect() as conn:
        ops = [r["operation"] for r in conn.execute(
            """SELECT operation FROM hfg_driver_audit WHERE driver_id = %s AND changed_by = 'admin'
               ORDER BY audit_id""", (new["driver_id"],)).fetchall()]
    record("T20", "Admin CRUD", "Create, edit and delete a driver",
           "Three audit rows by 'admin'", ", ".join(ops), ops == ["INSERT", "UPDATE", "DELETE"])

    r = post(admin, f"/admin/drivers/{new['driver_id']}/delete", follow_redirects=True)
    ok = "does not exist" in text_of(r)
    record("T21", "Admin CRUD", "Delete a driver that no longer exists", "Rejected with message",
           "rejected" if ok else "no message", ok)

    # Security
    r = admin.post("/admin/drivers/new", data={"first_name": "Forged", "last_name": "Request"})
    forged = one("SELECT 1 AS x FROM hfg_drivers WHERE first_name = 'Forged'")
    record("T22", "Security", "POST without the anti-CSRF token (forged request)",
           "Rejected with HTTP 400, nothing stored",
           f"HTTP {r.status_code}, stored: {bool(forged)}", r.status_code == 400 and not forged)

    before = one("SELECT COUNT(*) AS n FROM hfg_drivers")["n"]
    r = anon.get("/search?q=%27%3B%20DROP%20TABLE%20drivers%3B%20--")
    after = one("SELECT COUNT(*) AS n FROM hfg_drivers")["n"]
    record("T23", "Security", "SQL injection string in search", "Treated as text, no damage",
           f"HTTP {r.status_code}, drivers {before} -> {after}", r.status_code == 200 and before == after)

    # Constraints and triggers
    def expect_error(tid, label, sql, params, err):
        with dbs.connect() as conn:
            try:
                conn.execute(sql, params)
                outcome, ok = "accepted", False
            except err as exc:
                outcome, ok = type(exc).__name__, True
            conn.rollback()
        record(tid, "Database", label, f"Rejected ({err.__name__})", outcome, ok)

    sample = one("SELECT race_id, driver_id, team_id FROM hfg_results LIMIT 1")
    expect_error("T24", "CHECK: review rating 11",
                 "INSERT INTO hfg_reviews (user_id, race_id, rating) VALUES (1, %s, 11)", (completed,),
                 psycopg.errors.CheckViolation)
    expect_error("T25", "UNIQUE: second result for the same driver and race",
                 "INSERT INTO hfg_results (race_id, driver_id, team_id) VALUES (%s, %s, %s)",
                 (sample["race_id"], sample["driver_id"], sample["team_id"]),
                 psycopg.errors.UniqueViolation)
    expect_error("T26", "FOREIGN KEY: result for a race that does not exist",
                 "INSERT INTO hfg_results (race_id, driver_id, team_id) VALUES (999999, %s, %s)",
                 (sample["driver_id"], sample["team_id"]), psycopg.errors.ForeignKeyViolation)

    with dbs.connect() as conn:
        conn.execute("INSERT INTO hfg_results (race_id, driver_id, team_id) VALUES (%s, %s, %s)",
                     (upcoming, sample["driver_id"], sample["team_id"]))
        flag = conn.execute("SELECT is_upcoming FROM hfg_races WHERE race_id = %s", (upcoming,)).fetchone()
        conn.rollback()
    record("T27", "Database", "Trigger: first result of an upcoming race", "Race marked as completed",
           f"is_upcoming = {flag['is_upcoming']}", flag["is_upcoming"] is False)

    with dbs.connect() as conn:
        d = conn.execute("""SELECT d.driver_id, d.team_id FROM hfg_drivers d
                            WHERE d.team_id IS NOT NULL LIMIT 1""").fetchone()
        other = conn.execute("SELECT team_id FROM hfg_teams WHERE team_id <> %s LIMIT 1",
                             (d["team_id"],)).fetchone()["team_id"]
        conn.execute("INSERT INTO hfg_results (race_id, driver_id, team_id) VALUES (%s, %s, %s) "
                     "ON CONFLICT (race_id, driver_id) DO UPDATE SET team_id = EXCLUDED.team_id",
                     (upcoming, d["driver_id"], other))
        moved = conn.execute("SELECT team_id FROM hfg_drivers WHERE driver_id = %s",
                             (d["driver_id"],)).fetchone()["team_id"]
        conn.rollback()
    record("T28", "Database", "Trigger: result for a new team in the latest race",
           "Driver's current team updated", "updated" if moved == other else "unchanged", moved == other)

    # Standings vs official data
    with dbs.connect() as conn:
        for tid, year in (("T29", 2025), ("T30", 2026)):
            sid = conn.execute("SELECT season_id FROM hfg_seasons WHERE year = %s", (year,)).fetchone()["season_id"]
            ours = {norm(r["last_name"]): (float(r["points"]), int(r["wins"]))
                    for r in conn.execute("SELECT * FROM hfg_fn_driver_standings(%s)", (sid,)).fetchall()}
            last_round = conn.execute(
                "SELECT MAX(round) AS r FROM hfg_races WHERE season_id = %s AND NOT is_upcoming",
                (sid,)).fetchone()["r"]
            url = f"https://api.jolpi.ca/ergast/f1/{year}/{last_round}/driverstandings.json?limit=100"
            req = urllib.request.Request(url, headers={"User-Agent": "f1-thesis-tests"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                lst = json.loads(resp.read())["MRData"]["StandingsTable"]["StandingsLists"][0]
            official = {norm(s["Driver"]["familyName"]): (float(s["points"]), int(s["wins"]))
                        for s in lst["DriverStandings"]}
            same = sum(1 for k, v in official.items() if ours.get(k) == v)
            record(tid, "Correctness",
                   f"{year} driver standings vs official (after round {lst['round']})",
                   "Points and wins equal for every driver",
                   f"{same}/{len(official)} drivers equal", same == len(official) == len(ours))

    # Password and deletion rules
    r = post(app.test_client(), "/auth/register",
             data={"username": "test_short_pw", "password": "1234567"}, follow_redirects=True)
    stored = one("SELECT 1 AS x FROM hfg_users WHERE username = 'test_short_pw'") is not None
    ok = "at least 8" in text_of(r) and not stored
    record("T31", "Registration", "Password of 7 characters", "Rejected with message",
           "rejected" if ok else "accepted", ok)

    used_circuit = one("SELECT circuit_id FROM hfg_races LIMIT 1")["circuit_id"]
    expect_error("T32", "RESTRICT: delete a team that has results",
                 "DELETE FROM hfg_teams WHERE team_id = %s", (sample["team_id"],),
                 psycopg.errors.RestrictViolation)
    expect_error("T33", "RESTRICT: delete a driver who has results",
                 "DELETE FROM hfg_drivers WHERE driver_id = %s", (sample["driver_id"],),
                 psycopg.errors.RestrictViolation)
    expect_error("T34", "RESTRICT: delete a circuit that has races",
                 "DELETE FROM hfg_circuits WHERE circuit_id = %s", (used_circuit,),
                 psycopg.errors.RestrictViolation)
    expect_error("T35", "UNIQUE: second team with the same name",
                 "INSERT INTO hfg_teams (name) SELECT name FROM hfg_teams LIMIT 1", (),
                 psycopg.errors.UniqueViolation)
    expect_error("T36", "UNIQUE: second circuit with the same name",
                 "INSERT INTO hfg_circuits (name) SELECT name FROM hfg_circuits LIMIT 1", (),
                 psycopg.errors.UniqueViolation)

    # The (season_id, round) constraint is deferred: the clash is detected at COMMIT
    with dbs.connect() as conn:
        two = conn.execute("""SELECT race_id, round FROM hfg_races
                              WHERE season_id = (SELECT MAX(season_id) FROM hfg_races)
                              ORDER BY round LIMIT 2""").fetchall()
        conn.execute("UPDATE hfg_races SET round = %s WHERE race_id = %s",
                     (two[1]["round"], two[0]["race_id"]))
        try:
            conn.commit()
            outcome, ok = "committed", False
        except psycopg.errors.UniqueViolation:
            outcome, ok = "UniqueViolation at COMMIT", True
    record("T37", "Database", "DEFERRED UNIQUE: two races with the same round in a season",
           "Rejected when the transaction commits", outcome, ok)

    # Clean up
    with dbs.connect() as conn:
        conn.execute("DELETE FROM hfg_users WHERE username IN (%s, 'test_short_pw')", (TEST_USER,))
        conn.commit()

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} tests passed")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())