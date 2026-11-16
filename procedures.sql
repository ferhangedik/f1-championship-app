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

