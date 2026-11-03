-- Expects:
--   app.run_id   UUID of current pipeline run
--   app.dq_mode  observe|enforce
--
-- Updates publication for every match that has DQ rows in the current run.
-- Status is derived from the *latest* result of each (match, check_name)
-- across all runs, so a later cross-source PASS cannot clear an earlier
-- match-level CRITICAL FAIL.

WITH latest_checks AS (
    SELECT DISTINCT ON (d.canonical_match_id, d.check_name)
        d.canonical_match_id,
        d.check_name,
        d.status,
        d.severity
    FROM monitoring.data_quality_results d
    WHERE d.canonical_match_id IS NOT NULL
    ORDER BY d.canonical_match_id, d.check_name, d.check_id DESC
),
match_rollup AS (
    SELECT
        canonical_match_id,
        COUNT(*) FILTER (
            WHERE status = 'FAIL' AND severity = 'CRITICAL'
        ) AS critical_fail_count,
        COUNT(*) FILTER (
            WHERE status = 'FAIL' AND severity IN ('WARNING', 'ERROR')
        ) AS warning_fail_count,
        COUNT(*) FILTER (WHERE status = 'FAIL') AS any_fail_count,
        COUNT(*) AS check_count
    FROM latest_checks
    GROUP BY canonical_match_id
)
UPDATE monitoring.match_publication_status mps
SET
    dq_status = CASE
        WHEN mr.critical_fail_count > 0
         AND current_setting('app.dq_mode') = 'enforce'
            THEN 'FAIL'
        WHEN mr.any_fail_count > 0
            THEN 'WARN'
        WHEN mr.check_count > 0
            THEN 'PASS'
        ELSE mps.dq_status
    END,
    publication_status = CASE
        WHEN current_setting('app.dq_mode') = 'enforce'
         AND mr.critical_fail_count > 0
            THEN 'QUARANTINED'
        WHEN mr.check_count > 0
            THEN 'PUBLISHABLE'
        ELSE mps.publication_status
    END,
    is_quarantined = CASE
        WHEN current_setting('app.dq_mode') = 'enforce'
         AND mr.critical_fail_count > 0
            THEN TRUE
        WHEN mr.check_count > 0
            THEN FALSE
        ELSE mps.is_quarantined
    END,
    critical_check_count = COALESCE(mr.critical_fail_count, 0),
    warning_check_count = COALESCE(mr.warning_fail_count, 0),
    last_checked_at = NOW()
FROM match_rollup mr
WHERE mps.canonical_match_id = mr.canonical_match_id
  AND EXISTS (
      SELECT 1
      FROM monitoring.data_quality_results d
      WHERE d.run_id = current_setting('app.run_id')::UUID
        AND d.canonical_match_id = mps.canonical_match_id
  );
