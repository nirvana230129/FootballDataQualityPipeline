-- Expects app.run_id and app.dq_mode.

DROP TABLE IF EXISTS tmp_cross_dq;
CREATE TEMP TABLE tmp_cross_dq (
    check_name TEXT,
    check_type TEXT,
    severity TEXT,
    status TEXT,
    canonical_match_id BIGINT,
    records_checked BIGINT,
    records_failed BIGINT,
    details JSONB
) ON COMMIT DROP;

-- Provider score arithmetic across football-data staging.
INSERT INTO tmp_cross_dq
SELECT
    'football_data_score_arithmetic',
    'contract',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'ERROR' ELSE 'WARNING' END,
    CASE WHEN COUNT(*) FILTER (WHERE NOT COALESCE(score_arithmetic_ok, FALSE)) = 0
         THEN 'PASS' ELSE 'FAIL' END,
    NULL,
    COUNT(*),
    COUNT(*) FILTER (WHERE NOT COALESCE(score_arithmetic_ok, FALSE)),
    COALESCE(
        jsonb_agg(jsonb_build_object('match_id', match_id, 'duration', duration))
            FILTER (WHERE NOT COALESCE(score_arithmetic_ok, FALSE)),
        '[]'::jsonb
    )
FROM staging.football_data_matches;

-- Per-match cross-source score rows (FAIL quarantines the match in enforce).
INSERT INTO tmp_cross_dq
SELECT
    'cross_source_score_mismatch',
    'cross_source',
    CASE WHEN current_setting('app.dq_mode') = 'enforce' THEN 'CRITICAL' ELSE 'WARNING' END,
    CASE WHEN bad THEN 'FAIL' ELSE 'PASS' END,
    canonical_match_id,
    1,
    CASE WHEN bad THEN 1 ELSE 0 END,
    jsonb_build_object(
        'canonical_match_id', canonical_match_id,
        'statsbomb', jsonb_build_array(sb_home, sb_away),
        'football_data', jsonb_build_array(fd_home, fd_away)
    )
FROM (
    SELECT
        msm_fd.canonical_match_id,
        cm.home_score AS sb_home,
        cm.away_score AS sb_away,
        fm.canonical_home_score AS fd_home,
        fm.canonical_away_score AS fd_away,
        (
            cm.home_score IS DISTINCT FROM fm.canonical_home_score
            OR cm.away_score IS DISTINCT FROM fm.canonical_away_score
        ) AS bad
    FROM core.match_source_mapping msm_fd
    JOIN core.matches cm
      ON cm.canonical_match_id = msm_fd.canonical_match_id
    JOIN staging.football_data_matches fm
      ON fm.match_id::TEXT = msm_fd.source_match_id
    WHERE msm_fd.provider = 'football_data'
      AND msm_fd.mapping_status = 'matched'
) s;

-- Kickoff drift for matched matches.
INSERT INTO tmp_cross_dq
SELECT
    'cross_source_kickoff_mismatch',
    'cross_source',
    'WARNING',
    CASE WHEN COUNT(*) FILTER (WHERE bad) = 0 THEN 'PASS' ELSE 'FAIL' END,
    NULL,
    COUNT(*),
    COUNT(*) FILTER (WHERE bad),
    COALESCE(
        jsonb_agg(jsonb_build_object(
            'canonical_match_id', canonical_match_id,
            'delta_hours', delta_hours
        )) FILTER (WHERE bad),
        '[]'::jsonb
    )
FROM (
    SELECT
        msm_fd.canonical_match_id,
        ABS(EXTRACT(EPOCH FROM (cm.kickoff_utc - fm.utc_date))) / 3600.0 AS delta_hours,
        ABS(EXTRACT(EPOCH FROM (cm.kickoff_utc - fm.utc_date))) > 3600 AS bad
    FROM core.match_source_mapping msm_fd
    JOIN core.matches cm
      ON cm.canonical_match_id = msm_fd.canonical_match_id
    JOIN staging.football_data_matches fm
      ON fm.match_id::TEXT = msm_fd.source_match_id
    WHERE msm_fd.provider = 'football_data'
      AND msm_fd.mapping_status = 'matched'
      AND cm.kickoff_utc IS NOT NULL
      AND fm.utc_date IS NOT NULL
) k;

-- Coverage summary.
INSERT INTO tmp_cross_dq
SELECT
    'mapping_coverage',
    'coverage',
    'WARNING',
    'PASS',
    NULL,
    (SELECT COUNT(*) FROM staging.football_data_matches),
    (SELECT COUNT(*) FROM staging.football_data_matches fm
     WHERE NOT EXISTS (
        SELECT 1 FROM core.match_source_mapping msm
        WHERE msm.provider = 'football_data'
          AND msm.source_match_id = fm.match_id::TEXT
          AND msm.mapping_status = 'matched'
     )),
    jsonb_build_object(
        'provider_matches', (SELECT COUNT(*) FROM staging.football_data_matches),
        'matched', (
            SELECT COUNT(*) FROM core.match_source_mapping
            WHERE provider = 'football_data' AND mapping_status = 'matched'
        ),
        'unmatched', (
            SELECT COUNT(*) FROM staging.football_data_matches fm
            WHERE NOT EXISTS (
                SELECT 1 FROM core.match_source_mapping msm
                WHERE msm.provider = 'football_data'
                  AND msm.source_match_id = fm.match_id::TEXT
            )
        ),
        'ambiguous', (
            SELECT COUNT(*) FROM core.match_source_mapping
            WHERE provider = 'football_data' AND mapping_status = 'ambiguous'
        ),
        'coverage_percent', (
            SELECT ROUND(
                100.0 * COUNT(*) FILTER (WHERE mapping_status = 'matched')
                / NULLIF((SELECT COUNT(*) FROM staging.football_data_matches), 0),
                2
            )
            FROM core.match_source_mapping
            WHERE provider = 'football_data'
        )
    );

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
    'football_data',
    'staging/core',
    'matches',
    canonical_match_id,
    check_name,
    check_type,
    severity,
    status,
    records_checked,
    records_failed,
    CASE
        WHEN records_checked = 0 THEN NULL
        ELSE records_failed::DOUBLE PRECISION / records_checked::DOUBLE PRECISION
    END,
    CASE
        WHEN jsonb_typeof(details) = 'array' THEN jsonb_build_object(
            'examples', (
                SELECT jsonb_agg(value)
                FROM (
                    SELECT value
                    FROM jsonb_array_elements(details) WITH ORDINALITY AS x(value, ord)
                    WHERE ord <= 20
                ) limited
            )
        )
        ELSE details
    END
FROM tmp_cross_dq;
