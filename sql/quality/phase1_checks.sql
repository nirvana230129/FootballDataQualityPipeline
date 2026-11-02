-- Expects:
--   app.match_id   StatsBomb source match id
--   app.run_id     UUID of current pipeline run
--   app.dq_mode    observe|enforce

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
        jsonb_agg(jsonb_build_object('event_id', event_id, 'count', cnt))
            FILTER (WHERE cnt > 1),
        '[]'::jsonb
    )
FROM (
    SELECT event_id, COUNT(*) AS cnt
    FROM staging.statsbomb_events
    WHERE match_id = current_setting('app.match_id')::BIGINT
    GROUP BY event_id
) d;

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

UPDATE monitoring.match_publication_status mps
SET
    dq_status = CASE
        WHEN EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
              AND d.status = 'FAIL'
              AND d.severity = 'CRITICAL'
              AND current_setting('app.dq_mode') = 'enforce'
        ) THEN 'FAIL'
        WHEN EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
              AND d.status = 'FAIL'
        ) THEN 'WARN'
        ELSE 'PASS'
    END,
    publication_status = CASE
        WHEN current_setting('app.dq_mode') = 'enforce'
         AND EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
              AND d.status = 'FAIL'
              AND d.severity = 'CRITICAL'
         ) THEN 'QUARANTINED'
        ELSE 'PUBLISHABLE'
    END,
    is_quarantined = CASE
        WHEN current_setting('app.dq_mode') = 'enforce'
         AND EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
              AND d.status = 'FAIL'
              AND d.severity = 'CRITICAL'
         ) THEN TRUE
        ELSE FALSE
    END,
    critical_check_count = (
        SELECT COUNT(*)
        FROM monitoring.data_quality_results d
        WHERE d.run_id = current_setting('app.run_id')::UUID
          AND d.canonical_match_id = mps.canonical_match_id
          AND d.status = 'FAIL'
          AND d.severity = 'CRITICAL'
    ),
    warning_check_count = (
        SELECT COUNT(*)
        FROM monitoring.data_quality_results d
        WHERE d.run_id = current_setting('app.run_id')::UUID
          AND d.canonical_match_id = mps.canonical_match_id
          AND d.status = 'FAIL'
          AND d.severity IN ('WARNING', 'ERROR')
    ),
    last_checked_at = NOW()
FROM core.match_source_mapping msm
WHERE msm.provider = 'statsbomb'
  AND msm.source_match_id = current_setting('app.match_id')
  AND mps.canonical_match_id = msm.canonical_match_id;
