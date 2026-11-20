
--  F1 Championship Data Analysis - Database Schema (PostgreSQL 18)
--  Author: H. Ferhan Gedik - 66623 
--  Every object of the project carries the prefix hfg_ based on thesis requirements.

--  Run (in this order):
--    psql -h 127.0.0.1 -U postgres -d hfg_f1db -f schema.sql
--    psql -h 127.0.0.1 -U postgres -d hfg_f1db -f procedures.sql

--  Normalisation: all tables conform to 3NF. No repeating groups (1NF), no attribute depends on a part of a key (2NF).


-- Table 1 - Championship seasons
CREATE TABLE IF NOT EXISTS hfg_seasons (
    season_id   SERIAL PRIMARY KEY,
    year        INTEGER NOT NULL,
    CONSTRAINT hfg_seasons_year_uq  UNIQUE (year),          -- each year only once
    CONSTRAINT hfg_seasons_year_chk CHECK (year >= 1950)
);

-- Table 2 — Teams
CREATE TABLE IF NOT EXISTS hfg_teams (
    team_id     SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    nationality VARCHAR(60),
    wiki_url    VARCHAR(255),
    CONSTRAINT hfg_teams_name_uq UNIQUE (name)
);


-- Table 3 — Race tracks
CREATE TABLE IF NOT EXISTS hfg_circuits (
    circuit_id  SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    location    VARCHAR(100),
    country     VARCHAR(60),
    wiki_url    VARCHAR(255),
    CONSTRAINT hfg_circuits_name_uq UNIQUE (name)
);

-- Table 4 — Drivers (linked to their current team via FK)
CREATE TABLE IF NOT EXISTS hfg_drivers (
    driver_id     SERIAL PRIMARY KEY,
    first_name    VARCHAR(60) NOT NULL,
    last_name     VARCHAR(60) NOT NULL,
    date_of_birth DATE,
    nationality   VARCHAR(60),
    team_id       INTEGER REFERENCES hfg_teams(team_id) ON DELETE SET NULL,
    photo_url     VARCHAR(255),
    wiki_url      VARCHAR(255)
);


-- Table 5 — Races (belong to one season and one circuit)
CREATE TABLE IF NOT EXISTS hfg_races (
    race_id     SERIAL PRIMARY KEY,
    season_id   INTEGER NOT NULL REFERENCES hfg_seasons(season_id)   ON DELETE CASCADE,
    circuit_id  INTEGER NOT NULL REFERENCES hfg_circuits(circuit_id) ON DELETE RESTRICT,
    name        VARCHAR(120) NOT NULL,
    round       INTEGER NOT NULL,
    race_date   DATE NOT NULL,
    race_time   TIME,
    is_upcoming BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT hfg_races_season_round_uq UNIQUE (season_id, round)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT hfg_races_round_chk CHECK (round >= 1)
);


-- Table 6 — Race results (one row per race and driver)
--    finish_position NULL = not classified (retired, disqualified, ...).
--    marks the one driver who set the fastest lap of the whole race.
--    A team or a driver that has results cannot be deleted (RESTRICT).
CREATE TABLE IF NOT EXISTS hfg_results (
    result_id        SERIAL PRIMARY KEY,
    race_id          INTEGER NOT NULL REFERENCES hfg_races(race_id)     ON DELETE CASCADE,
    driver_id        INTEGER NOT NULL REFERENCES hfg_drivers(driver_id) ON DELETE RESTRICT,
    team_id          INTEGER NOT NULL REFERENCES hfg_teams(team_id)     ON DELETE RESTRICT,
    grid_position    INTEGER,
    finish_position  INTEGER,
    points           NUMERIC(5,2) NOT NULL DEFAULT 0,
    status           VARCHAR(40) NOT NULL DEFAULT 'Finished',
    fastest_lap_time VARCHAR(20),
    is_fastest_lap   BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT hfg_results_race_driver_uq UNIQUE (race_id, driver_id),
    CONSTRAINT hfg_results_points_chk CHECK (points >= 0)
);


-- Table 7 — Pit stop records
CREATE TABLE IF NOT EXISTS hfg_pit_stops (
    pit_stop_id SERIAL PRIMARY KEY,
    race_id     INTEGER NOT NULL REFERENCES hfg_races(race_id)     ON DELETE CASCADE,
    driver_id   INTEGER NOT NULL REFERENCES hfg_drivers(driver_id) ON DELETE CASCADE,
    stop_number INTEGER NOT NULL,
    lap         INTEGER NOT NULL,
    duration    NUMERIC(6,3),
    CONSTRAINT hfg_pit_stops_race_driver_stop_uq UNIQUE (race_id, driver_id, stop_number)
);


-- Table 8 — Qualifying classification (Q1/Q2/Q3 times stored as text)
CREATE TABLE IF NOT EXISTS hfg_qualifying (
    qualifying_id SERIAL PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES hfg_races(race_id)     ON DELETE CASCADE,
    driver_id     INTEGER NOT NULL REFERENCES hfg_drivers(driver_id) ON DELETE CASCADE,
    q1_time       VARCHAR(20),
    q2_time       VARCHAR(20),
    q3_time       VARCHAR(20),
    grid_position INTEGER,
    CONSTRAINT hfg_qualifying_race_driver_uq UNIQUE (race_id, driver_id)
);


-- Table 9 — Application users (Werkzeug-hashed password)
CREATE TABLE IF NOT EXISTS hfg_users (
    user_id       SERIAL PRIMARY KEY,
    username      VARCHAR(40) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT hfg_users_username_uq UNIQUE (username)
);

-- Table 10 — User race reviews (rating + comment) ---- A user can review a given race only once (UNIQUE).
CREATE TABLE IF NOT EXISTS hfg_reviews (
    review_id  SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES hfg_users(user_id) ON DELETE CASCADE,
    race_id    INTEGER NOT NULL REFERENCES hfg_races(race_id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL,
    comment    TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT hfg_reviews_rating_chk CHECK (rating BETWEEN 1 AND 10),
    CONSTRAINT hfg_reviews_user_race_uq UNIQUE (user_id, race_id)
);

-- Table 11 — Sprint race results
CREATE TABLE IF NOT EXISTS hfg_sprint_results (
    sprint_result_id SERIAL PRIMARY KEY,
    race_id          INTEGER NOT NULL REFERENCES hfg_races(race_id)     ON DELETE CASCADE,
    driver_id        INTEGER NOT NULL REFERENCES hfg_drivers(driver_id) ON DELETE RESTRICT,
    team_id          INTEGER NOT NULL REFERENCES hfg_teams(team_id)     ON DELETE RESTRICT,
    grid_position    INTEGER,
    finish_position  INTEGER,
    points           NUMERIC(5,2) NOT NULL DEFAULT 0,
    status           VARCHAR(40) NOT NULL DEFAULT 'Finished',
    CONSTRAINT hfg_sprint_results_race_driver_uq UNIQUE (race_id, driver_id),
    CONSTRAINT hfg_sprint_results_points_chk CHECK (points >= 0)
);


-- Table 12 — Change log of hfg_drivers, written by a trigger --- (every INSERT / UPDATE / DELETE made through the admin panel or loaders).
CREATE TABLE IF NOT EXISTS hfg_driver_audit (
    audit_id    SERIAL PRIMARY KEY,
    driver_id   INTEGER NOT NULL,   -- no FK: the row may be deleted
    operation   VARCHAR(6) NOT NULL,
    old_data    JSONB,
    new_data    JSONB,
    changed_by  VARCHAR(63) NOT NULL DEFAULT CURRENT_USER,
    changed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT hfg_driver_audit_operation_chk
        CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'))
);

-- INDEXES
CREATE INDEX IF NOT EXISTS hfg_idx_results_driver  ON hfg_results(driver_id);
CREATE INDEX IF NOT EXISTS hfg_idx_results_team    ON hfg_results(team_id);
CREATE INDEX IF NOT EXISTS hfg_idx_sprint_driver   ON hfg_sprint_results(driver_id);
CREATE INDEX IF NOT EXISTS hfg_idx_pitstops_driver ON hfg_pit_stops(driver_id);
CREATE INDEX IF NOT EXISTS hfg_idx_qualifying_driver ON hfg_qualifying(driver_id);
CREATE INDEX IF NOT EXISTS hfg_idx_races_circuit   ON hfg_races(circuit_id);
CREATE INDEX IF NOT EXISTS hfg_idx_drivers_team    ON hfg_drivers(team_id);
CREATE INDEX IF NOT EXISTS hfg_idx_reviews_race    ON hfg_reviews(race_id);
CREATE INDEX IF NOT EXISTS hfg_idx_audit_driver    ON hfg_driver_audit(driver_id);

