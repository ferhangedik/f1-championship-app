# F1 Championship Data Analysis

> Engineering diploma project — Akademia Finansów i Biznesu Vistula.

A full-stack web application that collects real Formula 1 data (from the **Jolpica-F1 / Ergast** API and the **FastF1** library),
stores it in a normalised **PostgreSQL 18** relational database, and presents it through an
interactive **Flask** web interface (Bootstrap 5 + Chart.js).


## Tech stack
- **Backend:** Python 3.14, Flask (application factory + blueprints)
- **Database:** PostgreSQL 18, raw parameterised SQL via **psycopg v3**
- **Data sources:** the Jolpica-F1 / Ergast API (`ergast_loader.py`, main loader) and FastF1 (`data_loader.py`, driver photos and cross-checks)
- **Server-side SQL:** view, standings functions, stored procedures and triggers (`procedures.sql`)
- **Frontend:** HTML, Bootstrap 5, Chart.js, custom dark F1 theme
- **Auth:** Werkzeug password hashing, Flask sessions

## Requirements
- Python 3.14 and PostgreSQL 18 (Windows)
- Install Python packages: `python -m pip install -r requirements.txt`

## Database setup
The connection uses host **`127.0.0.1`** (not `localhost`) on port **5432**, database **`hfg_f1db`**,
user `postgres`. With local `trust` authentication no password is needed (see `.env`).

```powershell
# 1) Start the PostgreSQL server (no Windows service is registered):
& "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" start `
    -D "C:\Program Files\PostgreSQL\18\data" -l "$PWD\..\pg_server.log" -w

# 2) Create the database (once) and the schema:
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -h 127.0.0.1 -U postgres hfg_f1db
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres -d hfg_f1db -f schema.sql

# 3) Create the view, functions, stored procedures and triggers (after schema.sql):
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -U postgres -d hfg_f1db -f procedures.sql
```

## Load data (Jolpica-F1 / Ergast — main loader)
```powershell
python ergast_loader.py --season 2025             # sync the calendar, load every round with results
python ergast_loader.py --season 2026             # current season
python ergast_loader.py --season 2026 --round 16  # one round
```
The loader first aligns the stored calendar with the official one (races added or moved
mid-season shift the round numbers), then loads race results, **sprint results**, qualifying
and pit stops. Sprint points count towards the championship, so the standings add them to the
Grand Prix points. Database triggers mark a race as completed when its results arrive and keep
each driver's current team up to date. Re-run it after every race weekend.

## Driver photos and cross-check (FastF1)
```powershell
python data_loader.py --season 2026 --round 20 --photos-only   # only the headshot photos
python data_loader.py --season 2025 --round 1                  # full weekend from FastF1 (second source)
```
`--photos-only` stores nothing but `photo_url`; without it the script upserts the results of
that weekend from FastF1, which overwrites the values stored by `ergast_loader.py`.
FastF1 returns the headshot photos only after signing in with an account that has an active
F1 TV subscription; without it no photos are stored and the driver pages show an icon instead.
A photo address can also be entered by hand in the admin panel (Photo URL).

## Run the app
```powershell
# If PostgreSQL is not running (no Windows service registered), start it first:
.\start_db.bat            # or use the pg_ctl command above

python app.py             # http://127.0.0.1:8080
```
- Default admin account: **username `admin`, password `admin123`** (admin-only panel at `/admin/`).
  Recreate or change it any time with `python create_admin.py admin <newpassword>`.
- Register normal accounts at `/auth/register` to post race reviews.

## Pages
`/` (dashboard) · `/standings/` · `/races/` · `/races/<id>` · `/drivers/` · `/drivers/<id>` ·
`/compare/` · `/compare/teammates` · `/analytics/` · `/calendar/` · `/search` ·
`/auth/login` · `/auth/register` · `/admin/`

## Going online (your own domain) -- AI Generated
See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a full step-by-step guide to deploy on an Ubuntu VPS
with Gunicorn + Nginx + PostgreSQL and free HTTPS (Let's Encrypt). `wsgi.py` is the production
entry point (`gunicorn wsgi:app`).

## Project layout
```
app.py              # create_app(), registers blueprints, error handlers
wsgi.py             # production entry point (gunicorn wsgi:app) -- AI Generated
serve.py            # single-process runner (preview / simple run) -- AI Generated
db.py               # psycopg v3 helper (get_db/query/execute)
db_standalone.py    # connection for CLI scripts
data_loader.py      # FastF1 -> PostgreSQL (driver photos, second source)
create_admin.py     # create/update the admin (or any) user
schema.sql          # full DDL (12 tables, constraints, indexes)
procedures.sql      # view, standings functions, stored procedures, triggers
ergast_loader.py    # Jolpica/Ergast -> PostgreSQL main loader (incl. sprints)
helpers.py          # auth decorators
routes/             # 10 feature blueprints (home, standings, races, drivers,
                    #   compare, analytics, calendar, auth, reviews, admin) + common.py
templates/          # base.html + page templates (dashboard, search, teammates, errors, ...) -- HTML structures are AI generated
static/css/style.css, static/favicon.svg
start_db.bat        # start local PostgreSQL (Windows)
DEPLOYMENT.md       # VPS deployment guide -- AI Generated
tests/              # functional, database and performance tests
```


## Tests
```powershell
python tests\functional_tests.py   # 37 functional, security and database tests
python tests\performance.py        # query and page timings (the app must be running)
```