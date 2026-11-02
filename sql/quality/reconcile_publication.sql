-- Expects:
--   app.run_id   UUID of current pipeline run
--   app.dq_mode  observe|enforce
--
-- Recomputes publication status for every match that has DQ rows in this run,
-- plus any match already present in match_publication_status that appears in
-- this run's results (including cross-source CRITICAL).

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
        WHEN EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
        ) THEN 'PASS'
        ELSE mps.dq_status
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
        WHEN EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
        ) THEN 'PUBLISHABLE'
        ELSE mps.publication_status
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
        WHEN EXISTS (
            SELECT 1
            FROM monitoring.data_quality_results d
            WHERE d.run_id = current_setting('app.run_id')::UUID
              AND d.canonical_match_id = mps.canonical_match_id
        ) THEN FALSE
        ELSE mps.is_quarantined
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
WHERE EXISTS (
    SELECT 1
    FROM monitoring.data_quality_results d
    WHERE d.run_id = current_setting('app.run_id')::UUID
      AND d.canonical_match_id = mps.canonical_match_id
);
