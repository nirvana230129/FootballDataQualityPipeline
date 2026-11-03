-- Expects app.run_id.
-- Schema-only checks: never SELECT FROM required business tables.

DROP TABLE IF EXISTS tmp_schema_preflight;
CREATE TEMP TABLE tmp_schema_preflight (
    check_name TEXT,
    check_type TEXT,
    severity TEXT,
    status TEXT,
    records_checked BIGINT,
    records_failed BIGINT,
    details JSONB
) ON COMMIT DROP;

INSERT INTO tmp_schema_preflight
WITH required AS (
    SELECT *
    FROM (VALUES
        ('core', 'matches', 'canonical_match_id'),
        ('core', 'match_source_mapping', 'source_match_id'),
        ('core', 'team_source_mapping', 'source_team_id'),
        ('staging', 'statsbomb_events', 'event_id'),
        ('staging', 'statsbomb_matches', 'match_id'),
        ('monitoring', 'match_publication_status', 'publication_status')
    ) AS t(schema_name, table_name, column_name)
),
missing AS (
    SELECT r.schema_name, r.table_name, r.column_name
    FROM required r
    WHERE NOT EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = r.schema_name
          AND c.table_name = r.table_name
          AND c.column_name = r.column_name
    )
)
SELECT
    'missing_required_table_or_column',
    'schema',
    'CRITICAL',
    CASE WHEN (SELECT COUNT(*) FROM missing) = 0 THEN 'PASS' ELSE 'FAIL' END,
    (SELECT COUNT(*) FROM required),
    (SELECT COUNT(*) FROM missing),
    COALESCE(
        (SELECT jsonb_agg(jsonb_build_object(
            'schema', schema_name,
            'table', table_name,
            'column', column_name
        )) FROM missing),
        '[]'::jsonb
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
FROM tmp_schema_preflight;
