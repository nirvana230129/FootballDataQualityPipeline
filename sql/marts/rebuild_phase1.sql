-- Rebuild phase-1 marts for PUBLISHABLE matches only.

TRUNCATE marts.box_entries;
TRUNCATE marts.progressive_passes;
TRUNCATE marts.possessions;
TRUNCATE marts.shot_possessions;

CREATE OR REPLACE FUNCTION pg_temp.zone_name(px DOUBLE PRECISION, py DOUBLE PRECISION)
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
    SELECT z.zone_name
    FROM config.pitch_zones z
    WHERE px >= z.x_min
      AND (px < z.x_max OR (z.x_max = 120 AND px <= 120))
      AND py >= z.y_min
      AND (py < z.y_max OR (z.y_max = 80 AND py <= 80))
    ORDER BY z.zone_id
    LIMIT 1;
$$;

INSERT INTO marts.box_entries (
    match_id,
    team_id,
    player_id,
    action_type,
    is_cross,
    start_x,
    start_y,
    end_x,
    end_y,
    successful
)
SELECT
    e.canonical_match_id,
    e.canonical_team_id,
    e.canonical_player_id,
    'PASS',
    COALESCE(e.is_cross, FALSE),
    e.x,
    e.y,
    e.end_x,
    e.end_y,
    (e.pass_outcome IS NULL)
FROM core.events e
JOIN monitoring.match_publication_status mps
  ON mps.canonical_match_id = e.canonical_match_id
 AND mps.publication_status = 'PUBLISHABLE'
WHERE e.event_type = 'Pass'
  AND e.x IS NOT NULL
  AND e.y IS NOT NULL
  AND e.end_x IS NOT NULL
  AND e.end_y IS NOT NULL
  AND NOT (e.x >= 102 AND e.y BETWEEN 18 AND 62)
  AND (e.end_x >= 102 AND e.end_y BETWEEN 18 AND 62);

INSERT INTO marts.box_entries (
    match_id,
    team_id,
    player_id,
    action_type,
    is_cross,
    start_x,
    start_y,
    end_x,
    end_y,
    successful
)
SELECT
    e.canonical_match_id,
    e.canonical_team_id,
    e.canonical_player_id,
    'CARRY',
    FALSE,
    e.x,
    e.y,
    e.carry_end_x,
    e.carry_end_y,
    TRUE
FROM core.events e
JOIN monitoring.match_publication_status mps
  ON mps.canonical_match_id = e.canonical_match_id
 AND mps.publication_status = 'PUBLISHABLE'
WHERE e.event_type = 'Carry'
  AND e.x IS NOT NULL
  AND e.y IS NOT NULL
  AND e.carry_end_x IS NOT NULL
  AND e.carry_end_y IS NOT NULL
  AND NOT (e.x >= 102 AND e.y BETWEEN 18 AND 62)
  AND (e.carry_end_x >= 102 AND e.carry_end_y BETWEEN 18 AND 62);

INSERT INTO marts.progressive_passes (
    match_id,
    team_id,
    player_id,
    start_x,
    start_y,
    end_x,
    end_y,
    start_zone,
    end_zone,
    distance_before,
    distance_after,
    progression,
    absolute_reduction,
    definition_used
)
SELECT
    e.canonical_match_id,
    e.canonical_team_id,
    e.canonical_player_id,
    e.x,
    e.y,
    e.end_x,
    e.end_y,
    pg_temp.zone_name(e.x, e.y),
    pg_temp.zone_name(e.end_x, e.end_y),
    distance_before,
    distance_after,
    progression,
    absolute_reduction,
    'B'
FROM (
    SELECT
        e.*,
        SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2)) AS distance_before,
        SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2)) AS distance_after,
        CASE
            WHEN SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2)) = 0 THEN NULL
            ELSE (
                SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
                - SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2))
            ) / SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
        END AS progression,
        SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
            - SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2)) AS absolute_reduction
    FROM core.events e
    JOIN monitoring.match_publication_status mps
      ON mps.canonical_match_id = e.canonical_match_id
     AND mps.publication_status = 'PUBLISHABLE'
    WHERE e.event_type = 'Pass'
      AND e.x IS NOT NULL
      AND e.y IS NOT NULL
      AND e.end_x IS NOT NULL
      AND e.end_y IS NOT NULL
) e
WHERE e.progression >= 0.25;

WITH analytical AS (
    SELECT
        e.canonical_match_id,
        e.possession,
        e.canonical_team_id AS team_id,
        e.event_id,
        e.event_index,
        e.event_type,
        e.x,
        e.y,
        e.shot_xg,
        e.shot_outcome,
        e.minute,
        e.second
    FROM core.events e
    JOIN monitoring.match_publication_status mps
      ON mps.canonical_match_id = e.canonical_match_id
     AND mps.publication_status = 'PUBLISHABLE'
    WHERE e.possession IS NOT NULL
      AND e.event_type NOT IN ('Starting XI', 'Half Start', 'Half End', 'Tactical Shift')
),
ordered AS (
    SELECT
        *,
        FIRST_VALUE(x) OVER w AS start_x,
        FIRST_VALUE(y) OVER w AS start_y,
        LAST_VALUE(x) OVER w AS end_x,
        LAST_VALUE(y) OVER w AS end_y,
        COUNT(*) OVER w AS event_count,
        COUNT(*) FILTER (WHERE event_type = 'Pass') OVER w AS pass_count,
        BOOL_OR(event_type = 'Shot') OVER w AS has_shot,
        BOOL_OR(event_type = 'Shot' AND shot_outcome = 'Goal') OVER w AS has_goal,
        COALESCE(SUM(shot_xg) OVER w, 0) AS total_xg,
        MIN(minute * 60 + second) OVER w AS start_sec,
        MAX(minute * 60 + second) OVER w AS end_sec,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_match_id, possession, team_id
            ORDER BY event_index
        ) AS rn
    FROM analytical
    WINDOW w AS (
        PARTITION BY canonical_match_id, possession, team_id
        ORDER BY event_index
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
)
INSERT INTO marts.possessions (
    possession_id,
    match_id,
    team_id,
    start_x,
    start_y,
    start_zone,
    end_x,
    end_y,
    end_zone,
    event_count,
    pass_count,
    duration,
    has_shot,
    has_goal,
    total_xg
)
SELECT
    possession,
    canonical_match_id,
    team_id,
    start_x,
    start_y,
    pg_temp.zone_name(start_x, start_y),
    end_x,
    end_y,
    pg_temp.zone_name(end_x, end_y),
    event_count,
    pass_count,
    GREATEST(end_sec - start_sec, 0)::DOUBLE PRECISION,
    has_shot,
    has_goal,
    total_xg
FROM ordered
WHERE rn = 1;

INSERT INTO marts.shot_possessions (
    start_zone,
    possessions,
    shot_possessions,
    shot_conversion_rate,
    total_xg,
    avg_xg
)
SELECT
    COALESCE(start_zone, 'UNKNOWN') AS start_zone,
    COUNT(*) AS possessions,
    COUNT(*) FILTER (WHERE has_shot) AS shot_possessions,
    COUNT(*) FILTER (WHERE has_shot)::DOUBLE PRECISION / NULLIF(COUNT(*), 0),
    COALESCE(SUM(total_xg) FILTER (WHERE has_shot), 0),
    AVG(total_xg) FILTER (WHERE has_shot)
FROM marts.possessions
GROUP BY COALESCE(start_zone, 'UNKNOWN');
