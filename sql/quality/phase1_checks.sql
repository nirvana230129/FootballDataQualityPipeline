-- Expects:
--   app.match_id   StatsBomb source match id
--   app.run_id     UUID of current pipeline run
--   app.dq_mode    observe|enforce

DROP TABLE IF EXISTS tmp_dq_results;
CREATE TEMP TABLE tmp_dq_results (
    check_name TEXT,
    check_type TEXT,
    severity TEXT,
    status TEXT,
    records_checked BIGINT,
    records_failed BIGINT,
    details JSONB
) ON COMMIT DROP;

WITH raw_count AS (
    SELECT jsonb_array_length(payload) AS n
    FROM raw.statsbomb_events_current
    WHERE source_id = current_setting('app.match_id')
),
stg_count AS (
    SELECT COUNT(*) AS n
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
),
core_count AS (
    SELECT COUNT(*) AS n
    FROM core.events e
    JOIN core.match_source_mapping msm
      ON msm.canonical_match_id = e.canonical_match_id
    WHERE msm.provider = 'statsbomb'
      AND msm.source_match_id = current_setting('app.match_id')
)
INSERT INTO tmp_dq_results
SELECT
    'event_count_raw_staging_core',
    'volume',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'CRITICAL' ELSE 'WARNING' END,
    CASE
        WHEN COALESCE((SELECT n FROM raw_count), -1)
           = COALESCE((SELECT n FROM stg_count), -2)
         AND COALESCE((SELECT n FROM stg_count), -2)
           = COALESCE((SELECT n FROM core_count), -3)
        THEN 'PASS'
        ELSE 'FAIL'
    END,
    COALESCE((SELECT n FROM raw_count), 0),
    CASE
        WHEN COALESCE((SELECT n FROM raw_count), -1)
           = COALESCE((SELECT n FROM stg_count), -2)
         AND COALESCE((SELECT n FROM stg_count), -2)
           = COALESCE((SELECT n FROM core_count), -3)
        THEN 0
        ELSE 1
    END,
    jsonb_build_object(
        'raw', (SELECT n FROM raw_count),
        'staging', (SELECT n FROM stg_count),
        'core', (SELECT n FROM core_count)
    );

INSERT INTO tmp_dq_results
SELECT
    'duplicate_event_id',
    'duplicate',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'CRITICAL' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE cnt > 1) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE cnt > 1),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'count', cnt, 'layer', layer))
            FILTER (WHERE cnt > 1),
        '[]'::jsonb
    )
FROM (
    SELECT event_id, COUNT(*) AS cnt, 'staging' AS layer
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
    GROUP BY event_id
    UNION ALL
    SELECT e ->> 'id' AS event_id, COUNT(*) AS cnt, 'raw' AS layer
    FROM raw.statsbomb_events_current r
    CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e
    WHERE r.source_id = current_setting('app.match_id')
    GROUP BY e ->> 'id'
) d;

INSERT INTO tmp_dq_results
SELECT
    'possession_team_unique',
    'consistency',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE team_cnt > 1) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE team_cnt > 1),
    COALESCE(
        jsonb_agg(jsonb_build_object(
            'possession', possession,
            'possession_team_ids', team_ids,
            'team_count', team_cnt
        )) FILTER (WHERE team_cnt > 1),
        '[]'::jsonb
    )
FROM (
    SELECT
        NULLIF(e ->> 'possession', '')::INTEGER AS possession,
        COUNT(DISTINCT NULLIF(e -> 'possession_team' ->> 'id', '')::BIGINT) AS team_cnt,
        jsonb_agg(DISTINCT NULLIF(e -> 'possession_team' ->> 'id', '')::BIGINT)
            FILTER (WHERE NULLIF(e -> 'possession_team' ->> 'id', '') IS NOT NULL) AS team_ids
    FROM raw.statsbomb_events_current r
    CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e
    WHERE r.source_id = current_setting('app.match_id')
      AND NULLIF(e ->> 'possession', '') IS NOT NULL
    GROUP BY NULLIF(e ->> 'possession', '')::INTEGER
) p;

INSERT INTO tmp_dq_results
SELECT
    'pass_required_fields',
    'conditional_null',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id)) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        (end_x IS NULL OR end_y IS NULL OR pass_length IS NULL) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Pass'
) p;

INSERT INTO tmp_dq_results
SELECT
    'shot_required_fields',
    'conditional_null',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id)) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        (shot_xg IS NULL OR end_x IS NULL OR end_y IS NULL) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Shot'
) s;

INSERT INTO tmp_dq_results
SELECT
    'event_team_not_in_match',
    'football_rule',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'team_id', team_id))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        e.event_id,
        e.team_id,
        e.team_id IS NOT NULL
        AND e.team_id NOT IN (m.home_team_id, m.away_team_id) AS bad
    FROM staging.statsbomb_events e
    JOIN staging.statsbomb_matches m
      ON m.match_id = e.match_id
    WHERE e.match_id = current_setting('app.match_id')::BIGINT
) t;

INSERT INTO tmp_dq_results
SELECT
    'player_not_in_squad',
    'football_rule',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'player_id', player_id))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        e.event_id,
        e.player_id,
        e.player_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM staging.statsbomb_lineups l
            WHERE l.match_id = e.match_id
              AND l.player_id = e.player_id
        ) AS bad
    FROM staging.statsbomb_events e
    WHERE e.match_id = current_setting('app.match_id')::BIGINT
) p;

INSERT INTO tmp_dq_results
SELECT
    'duplicate_event_index',
    'duplicate',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'CRITICAL' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE cnt > 1) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE cnt > 1),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_index', event_index, 'count', cnt))
            FILTER (WHERE cnt > 1),
        '[]'::jsonb
    )
FROM (
    SELECT event_index, COUNT(*) AS cnt
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_index IS NOT NULL
    GROUP BY event_index
) d;

INSERT INTO tmp_dq_results
SELECT
    'carry_required_fields',
    'conditional_null',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id)) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        (carry_end_x IS NULL OR carry_end_y IS NULL) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Carry'
) c;

INSERT INTO tmp_dq_results
SELECT
    'validate_event_location',
    'bounds',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*) FILTER (WHERE x IS NOT NULL AND y IS NOT NULL),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'x', x, 'y', y))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        x,
        y,
        x IS NOT NULL AND y IS NOT NULL
        AND (x < 0 OR x > 120 OR y < 0 OR y > 80) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
) loc;

INSERT INTO tmp_dq_results
SELECT
    'validate_pass_end_location',
    'bounds',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*) FILTER (WHERE end_x IS NOT NULL AND end_y IS NOT NULL),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'end_x', end_x, 'end_y', end_y))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        end_x,
        end_y,
        end_x IS NOT NULL AND end_y IS NOT NULL
        AND (end_x < 0 OR end_x > 120 OR end_y < 0 OR end_y > 80) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Pass'
) p;

INSERT INTO tmp_dq_results
SELECT
    'validate_carry_end_location',
    'bounds',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*) FILTER (WHERE carry_end_x IS NOT NULL AND carry_end_y IS NOT NULL),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object(
            'event_id', event_id,
            'carry_end_x', carry_end_x,
            'carry_end_y', carry_end_y
        )) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        carry_end_x,
        carry_end_y,
        carry_end_x IS NOT NULL AND carry_end_y IS NOT NULL
        AND (
            carry_end_x < 0 OR carry_end_x > 120
            OR carry_end_y < 0 OR carry_end_y > 80
        ) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Carry'
) c;

INSERT INTO tmp_dq_results
SELECT
    'validate_shot_end_location',
    'bounds',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*) FILTER (WHERE end_x IS NOT NULL AND end_y IS NOT NULL),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'end_x', end_x, 'end_y', end_y))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        end_x,
        end_y,
        end_x IS NOT NULL AND end_y IS NOT NULL
        AND (end_x < 0 OR end_x > 120 OR end_y < 0 OR end_y > 80) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Shot'
) s;

INSERT INTO tmp_dq_results
SELECT
    'event_time_bounds',
    'bounds',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object(
            'event_id', event_id,
            'minute', minute,
            'second', second,
            'period', period
        )) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        minute,
        second,
        period,
        (minute IS NOT NULL AND minute < 0)
        OR (second IS NOT NULL AND second < 0)
        OR (period IS NOT NULL AND period NOT IN (1, 2, 3, 4, 5)) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
) t;

INSERT INTO tmp_dq_results
SELECT
    'shot_xg_range',
    'range',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*) FILTER (WHERE shot_xg IS NOT NULL),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object('event_id', event_id, 'shot_xg', shot_xg))
            FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        event_id,
        shot_xg,
        shot_xg IS NOT NULL AND (shot_xg < 0 OR shot_xg > 1) AS bad
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
      AND event_type = 'Shot'
) x;

INSERT INTO tmp_dq_results
SELECT
    'event_volume_anomaly',
    'volume',
    'WARNING',
    CASE WHEN COUNT(*) < 2076.75 THEN 'FAIL' ELSE 'PASS' END,
    COUNT(*),
    CASE WHEN COUNT(*) < 2076.75 THEN 1 ELSE 0 END,
    jsonb_build_object(
        'event_count', COUNT(*),
        'threshold', 2076.75,
        'rule', 'Q1 - 3 * IQR from WC2022 profile'
    )
FROM staging.statsbomb_events
WHERE match_id = current_setting('app.match_id')::BIGINT;

INSERT INTO monitoring.data_quality_results (
    run_id,
    source,
    schema_name,
    table_name,
    canonical_match_id,
    check_name,
    check_type,
    severity,
    status,
    records_checked,
    records_failed,
    failure_rate,
    details
)
SELECT
    current_setting('app.run_id')::UUID,
    'statsbomb',
    'staging/core',
    'events',
    msm.canonical_match_id,
    r.check_name,
    r.check_type,
    r.severity,
    r.status,
    r.records_checked,
    r.records_failed,
    CASE
        WHEN r.records_checked = 0 THEN NULL
        ELSE r.records_failed::DOUBLE PRECISION / r.records_checked::DOUBLE PRECISION
    END,
    CASE
        WHEN jsonb_typeof(r.details) = 'array'
            THEN jsonb_build_object('examples', (
                SELECT jsonb_agg(value)
                FROM (
                    SELECT value
                    FROM jsonb_array_elements(r.details) WITH ORDINALITY AS x(value, ord)
                    WHERE ord <= 20
                ) limited
            ))
        ELSE r.details
    END
FROM tmp_dq_results r
JOIN core.match_source_mapping msm
  ON msm.provider = 'statsbomb'
 AND msm.source_match_id = current_setting('app.match_id');

-- Publication status is reconciled after all match + cross-source checks
-- via sql/quality/reconcile_publication.sql.
