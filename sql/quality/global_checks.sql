-- Expects app.run_id. Global CRITICAL data checks (schema already verified).
-- Results have canonical_match_id IS NULL.
-- Do not run this file if schema_preflight reported FAIL.

DROP TABLE IF EXISTS tmp_global_dq;
CREATE TEMP TABLE tmp_global_dq (
    check_name TEXT,
    check_type TEXT,
    severity TEXT,
    status TEXT,
    records_checked BIGINT,
    records_failed BIGINT,
    details JSONB
) ON COMMIT DROP;

INSERT INTO tmp_global_dq
SELECT
    'zero_matches_loaded',
    'volume',
    'CRITICAL',
    CASE WHEN COUNT(*) = 0 THEN 'FAIL' ELSE 'PASS' END,
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END,
    jsonb_build_object('core_matches', COUNT(*))
FROM core.matches;

INSERT INTO tmp_global_dq
SELECT
    'missing_team_source_mapping',
    'mapping',
    'CRITICAL',
    CASE WHEN COUNT(*) = 0 THEN 'FAIL' ELSE 'PASS' END,
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END,
    jsonb_build_object('mapping_rows', COUNT(*))
FROM core.team_source_mapping;

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
    'pipeline',
    'monitoring',
    'global',
    NULL,
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
    details
FROM tmp_global_dq;
