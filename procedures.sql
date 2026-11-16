--  F1 Championship Data Analysis - Database Schema (PostgreSQL 18)
--  Author: H. Ferhan Gedik - 66623 
--  Every object of the project carries the prefix hfg_ based on thesis requirements.


-- 1 - VIEW
-- Points scored by each driver at each round: Grand Prix points plus sprint points. A FULL JOIN keeps a driver who scored in only one of the two sessions.
CREATE OR REPLACE VIEW hfg_v_round_points AS
SELECT COALESCE(res.race_id,   spr.race_id)   AS race_id,
       COALESCE(res.driver_id, spr.driver_id) AS driver_id,
       COALESCE(res.team_id,   spr.team_id)   AS team_id,
       COALESCE(res.points, 0)                AS race_points,
       COALESCE(spr.points, 0)                AS sprint_points,
       COALESCE(res.points, 0) + COALESCE(spr.points, 0) AS points
FROM hfg_results res
FULL JOIN hfg_sprint_results spr
       ON spr.race_id = res.race_id AND spr.driver_id = res.driver_id;



-- 2 - FUNCTIONS (read-only, used by the standings and dashboard pages)

CREATE OR REPLACE FUNCTION hfg_fn_driver_standings(p_season_id INTEGER)
RETURNS TABLE (
    "position"    BIGINT,
    driver_id     INTEGER,
    first_name    VARCHAR,
    last_name     VARCHAR,
    team          VARCHAR,
    points        NUMERIC,
    sprint_points NUMERIC,
    wins          BIGINT,
    podiums       BIGINT,
    races         BIGINT
)
LANGUAGE sql STABLE AS $$
    WITH season_points AS (
        SELECT vp.driver_id,
               SUM(vp.points)        AS points,
               SUM(vp.sprint_points) AS sprint_points
        FROM hfg_v_round_points vp
        JOIN hfg_races r ON r.race_id = vp.race_id
        WHERE r.season_id = p_season_id
        GROUP BY vp.driver_id
    ),
    gp_record AS (
        SELECT res.driver_id,
               COUNT(*) FILTER (WHERE res.finish_position = 1)  AS wins,
               COUNT(*) FILTER (WHERE res.finish_position <= 3) AS podiums,
               COUNT(*)                                         AS races
        FROM hfg_results res
        JOIN hfg_races r ON r.race_id = res.race_id
        WHERE r.season_id = p_season_id
        GROUP BY res.driver_id
    ),
    season_team AS (
        SELECT DISTINCT ON (vp.driver_id) vp.driver_id, vp.team_id
        FROM hfg_v_round_points vp
        JOIN hfg_races r ON r.race_id = vp.race_id
        WHERE r.season_id = p_season_id
        ORDER BY vp.driver_id, r.round DESC
    )
    SELECT RANK() OVER (ORDER BY sp.points DESC, COALESCE(gp.wins, 0) DESC),
           d.driver_id, d.first_name, d.last_name, t.name,
           sp.points, sp.sprint_points,
           COALESCE(gp.wins, 0), COALESCE(gp.podiums, 0), COALESCE(gp.races, 0)
    FROM season_points sp
    JOIN hfg_drivers d       ON d.driver_id = sp.driver_id
    LEFT JOIN gp_record gp   ON gp.driver_id = sp.driver_id
    LEFT JOIN season_team st ON st.driver_id = sp.driver_id
    LEFT JOIN hfg_teams t    ON t.team_id = st.team_id
    ORDER BY sp.points DESC, COALESCE(gp.wins, 0) DESC, d.last_name;
$$;

-- Constructor standings of one season: every race and sprint point grouped by the team the points were scored for.
CREATE OR REPLACE FUNCTION hfg_fn_constructor_standings(p_season_id INTEGER)
RETURNS TABLE (
    "position"  BIGINT,
    team_id     INTEGER,
    name        VARCHAR,
    nationality VARCHAR,
    points      NUMERIC,
    wins        BIGINT,
    podiums     BIGINT
)
LANGUAGE sql STABLE AS $$
    WITH team_points AS (
        SELECT vp.team_id, SUM(vp.points) AS points
        FROM hfg_v_round_points vp
        JOIN hfg_races r ON r.race_id = vp.race_id
        WHERE r.season_id = p_season_id
        GROUP BY vp.team_id
    ),
    gp_record AS (
        SELECT res.team_id,
               COUNT(*) FILTER (WHERE res.finish_position = 1)  AS wins,
               COUNT(*) FILTER (WHERE res.finish_position <= 3) AS podiums
        FROM hfg_results res
        JOIN hfg_races r ON r.race_id = res.race_id
        WHERE r.season_id = p_season_id
        GROUP BY res.team_id
    )
    SELECT RANK() OVER (ORDER BY tp.points DESC, COALESCE(gp.wins, 0) DESC),
           t.team_id, t.name, t.nationality, tp.points,
           COALESCE(gp.wins, 0), COALESCE(gp.podiums, 0)
    FROM team_points tp
    JOIN hfg_teams t ON t.team_id = tp.team_id
    LEFT JOIN gp_record gp ON gp.team_id = tp.team_id
    ORDER BY tp.points DESC, COALESCE(gp.wins, 0) DESC, t.name;
$$;


-- 3 - STORED PROCEDURES (data insertion, update and deletion)
CREATE OR REPLACE PROCEDURE hfg_sp_create_driver(
    p_first_name    VARCHAR,
    p_last_name     VARCHAR,
    p_date_of_birth DATE,
    p_nationality   VARCHAR,
    p_team_id       INTEGER,
    p_photo_url     VARCHAR,
    p_wiki_url      VARCHAR,
    p_actor         VARCHAR,
    INOUT p_driver_id INTEGER DEFAULT NULL
)
LANGUAGE plpgsql AS $$
BEGIN
    IF COALESCE(TRIM(p_first_name), '') = '' OR COALESCE(TRIM(p_last_name), '') = '' THEN
        RAISE EXCEPTION 'First name and last name are required.';
    END IF;
    IF p_date_of_birth IS NOT NULL AND p_date_of_birth > CURRENT_DATE THEN
        RAISE EXCEPTION 'Date of birth cannot be in the future.';
    END IF;
    IF p_team_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM hfg_teams WHERE team_id = p_team_id) THEN
        RAISE EXCEPTION 'Team % does not exist.', p_team_id;
    END IF;

    PERFORM set_config('hfg.user', COALESCE(p_actor, ''), true);

    INSERT INTO hfg_drivers (first_name, last_name, date_of_birth, nationality,
                             team_id, photo_url, wiki_url)
    VALUES (TRIM(p_first_name), TRIM(p_last_name), p_date_of_birth,
            NULLIF(TRIM(p_nationality), ''), p_team_id,
            NULLIF(TRIM(p_photo_url), ''), NULLIF(TRIM(p_wiki_url), ''))
    RETURNING driver_id INTO p_driver_id;
END;
$$;

CREATE OR REPLACE PROCEDURE hfg_sp_update_driver(
    p_driver_id     INTEGER,
    p_first_name    VARCHAR,
    p_last_name     VARCHAR,
    p_date_of_birth DATE,
    p_nationality   VARCHAR,
    p_team_id       INTEGER,
    p_photo_url     VARCHAR,
    p_wiki_url      VARCHAR,
    p_actor         VARCHAR
)
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM hfg_drivers WHERE driver_id = p_driver_id) THEN
        RAISE EXCEPTION 'Driver % does not exist.', p_driver_id;
    END IF;
    IF COALESCE(TRIM(p_first_name), '') = '' OR COALESCE(TRIM(p_last_name), '') = '' THEN
        RAISE EXCEPTION 'First name and last name are required.';
    END IF;
    IF p_date_of_birth IS NOT NULL AND p_date_of_birth > CURRENT_DATE THEN
        RAISE EXCEPTION 'Date of birth cannot be in the future.';
    END IF;
    IF p_team_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM hfg_teams WHERE team_id = p_team_id) THEN
        RAISE EXCEPTION 'Team % does not exist.', p_team_id;
    END IF;

    PERFORM set_config('hfg.user', COALESCE(p_actor, ''), true);

    UPDATE hfg_drivers
       SET first_name    = TRIM(p_first_name),
           last_name     = TRIM(p_last_name),
           date_of_birth = p_date_of_birth,
           nationality   = NULLIF(TRIM(p_nationality), ''),
           team_id       = p_team_id,
           photo_url     = NULLIF(TRIM(p_photo_url), ''),
           wiki_url      = NULLIF(TRIM(p_wiki_url), '')
     WHERE driver_id = p_driver_id;
END;
$$;

-- A driver who has race or sprint results cannot be deleted, because the championship tables are computed from those results. For other drivers the audit trigger keeps a copy of the deleted row.
CREATE OR REPLACE PROCEDURE hfg_sp_delete_driver(p_driver_id INTEGER, p_actor VARCHAR)
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM hfg_drivers WHERE driver_id = p_driver_id) THEN
        RAISE EXCEPTION 'Driver % does not exist.', p_driver_id;
    END IF;
    IF EXISTS (SELECT 1 FROM hfg_results WHERE driver_id = p_driver_id)
       OR EXISTS (SELECT 1 FROM hfg_sprint_results WHERE driver_id = p_driver_id) THEN
        RAISE EXCEPTION 'A driver with race results cannot be deleted.';
    END IF;

    PERFORM set_config('hfg.user', COALESCE(p_actor, ''), true);

    DELETE FROM hfg_drivers WHERE driver_id = p_driver_id;
END;
$$;


CREATE OR REPLACE PROCEDURE hfg_sp_save_review(
    p_user_id INTEGER,
    p_race_id INTEGER,
    p_rating  INTEGER,
    p_comment TEXT
)
LANGUAGE plpgsql AS $$
BEGIN
    IF p_rating IS NULL OR p_rating NOT BETWEEN 1 AND 10 THEN
        RAISE EXCEPTION 'Rating must be between 1 and 10.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM hfg_races WHERE race_id = p_race_id) THEN
        RAISE EXCEPTION 'Race % does not exist.', p_race_id;
    END IF;

    INSERT INTO hfg_reviews (user_id, race_id, rating, comment)
    VALUES (p_user_id, p_race_id, p_rating, NULLIF(TRIM(p_comment), ''))
    ON CONFLICT (user_id, race_id) DO UPDATE
       SET rating     = EXCLUDED.rating,
           comment    = EXCLUDED.comment,
           created_at = CURRENT_TIMESTAMP;
END;
$$;


-- A user can delete only their own review -- the administrator can delete all.
CREATE OR REPLACE PROCEDURE hfg_sp_delete_review(
    p_review_id INTEGER,
    p_user_id   INTEGER,
    p_is_admin  BOOLEAN
)
LANGUAGE plpgsql AS $$
DECLARE
    v_owner INTEGER;
BEGIN
    SELECT user_id INTO v_owner FROM hfg_reviews WHERE review_id = p_review_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Review % does not exist.', p_review_id;
    END IF;
    IF v_owner <> p_user_id AND NOT p_is_admin THEN
        RAISE EXCEPTION 'You can only delete your own review.';
    END IF;

    DELETE FROM hfg_reviews WHERE review_id = p_review_id;
END;
$$;


-- 4. TRIGGERS

-- 4a. A race that receives a result has been held: clear its is_upcoming flag.
CREATE OR REPLACE FUNCTION hfg_fn_mark_race_completed()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE hfg_races SET is_upcoming = FALSE
     WHERE race_id = NEW.race_id AND is_upcoming;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER hfg_trg_results_mark_completed
AFTER INSERT ON hfg_results
FOR EACH ROW EXECUTE FUNCTION hfg_fn_mark_race_completed();

-- 4b. hfg_drivers.team_id is the driver's CURRENT team: when a result is stored for the driver's most recent race and the team differs, move the driver.
-- Loading an older season therefore never overwrites the current team.
CREATE OR REPLACE FUNCTION hfg_fn_sync_current_team()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM hfg_results res
        JOIN hfg_races r_other ON r_other.race_id = res.race_id
        JOIN hfg_races r_new   ON r_new.race_id   = NEW.race_id
        WHERE res.driver_id = NEW.driver_id
          AND r_other.race_date > r_new.race_date
    ) THEN
        UPDATE hfg_drivers SET team_id = NEW.team_id
         WHERE driver_id = NEW.driver_id
           AND team_id IS DISTINCT FROM NEW.team_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER hfg_trg_results_sync_team
AFTER INSERT OR UPDATE OF team_id ON hfg_results
FOR EACH ROW EXECUTE FUNCTION hfg_fn_sync_current_team();

-- 4c. Rule: a race can only be reviewed after it has taken place.
CREATE OR REPLACE FUNCTION hfg_fn_check_review_race()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM hfg_races WHERE race_id = NEW.race_id AND is_upcoming) THEN
        RAISE EXCEPTION 'Reviews can only be posted for races that have already taken place.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER hfg_trg_reviews_completed_race
BEFORE INSERT OR UPDATE ON hfg_reviews
FOR EACH ROW EXECUTE FUNCTION hfg_fn_check_review_race();

-- 4d. Audit trail: every change to hfg_drivers is copied to hfg_driver_audit as JSON (old and new row). 
-- changed_by is the application user set by the stored procedures, or the database role for changes made by the loaders.
CREATE OR REPLACE FUNCTION hfg_fn_audit_driver()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_actor VARCHAR := COALESCE(NULLIF(current_setting('hfg.user', true), ''), CURRENT_USER);
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO hfg_driver_audit (driver_id, operation, new_data, changed_by)
        VALUES (NEW.driver_id, TG_OP, to_jsonb(NEW), v_actor);
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO hfg_driver_audit (driver_id, operation, old_data, new_data, changed_by)
        VALUES (NEW.driver_id, TG_OP, to_jsonb(OLD), to_jsonb(NEW), v_actor);
        RETURN NEW;
    ELSE
        INSERT INTO hfg_driver_audit (driver_id, operation, old_data, changed_by)
        VALUES (OLD.driver_id, TG_OP, to_jsonb(OLD), v_actor);
        RETURN OLD;
    END IF;
END;
$$;

CREATE OR REPLACE TRIGGER hfg_trg_drivers_audit
AFTER INSERT OR UPDATE OR DELETE ON hfg_drivers
FOR EACH ROW EXECUTE FUNCTION hfg_fn_audit_driver();