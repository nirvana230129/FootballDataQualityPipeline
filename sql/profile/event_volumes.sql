-- Event volume stats per match and selected event types.
WITH per_match AS (
    SELECT
        match_id,
        COUNT(*) AS all_events,
        COUNT(*) FILTER (WHERE event_type = 'Pass') AS pass_events,
        COUNT(*) FILTER (WHERE event_type = 'Shot') AS shot_events,
        COUNT(*) FILTER (WHERE event_type = 'Carry') AS carry_events,
        COUNT(*) FILTER (WHERE event_type = 'Pressure') AS pressure_events,
        COUNT(*) FILTER (WHERE event_type = 'Duel') AS duel_events
    FROM staging.statsbomb_events
    GROUP BY match_id
),
metric AS (
    SELECT match_id, 'all' AS metric, all_events AS value FROM per_match
    UNION ALL SELECT match_id, 'Pass', pass_events FROM per_match
    UNION ALL SELECT match_id, 'Shot', shot_events FROM per_match
    UNION ALL SELECT match_id, 'Carry', carry_events FROM per_match
    UNION ALL SELECT match_id, 'Pressure', pressure_events FROM per_match
    UNION ALL SELECT match_id, 'Duel', duel_events FROM per_match
)
SELECT
    metric,
    COUNT(*) AS matches,
    MIN(value) AS min_value,
    percentile_cont(0.05) WITHIN GROUP (ORDER BY value) AS p05,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY value) AS p25,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY value) AS median,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY value) AS p75,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95,
    MAX(value) AS max_value,
    (
        percentile_cont(0.75) WITHIN GROUP (ORDER BY value)
        - percentile_cont(0.25) WITHIN GROUP (ORDER BY value)
    ) AS iqr
FROM metric
GROUP BY metric
ORDER BY CASE metric
    WHEN 'all' THEN 1
    WHEN 'Pass' THEN 2
    WHEN 'Shot' THEN 3
    WHEN 'Carry' THEN 4
    WHEN 'Pressure' THEN 5
    WHEN 'Duel' THEN 6
    ELSE 99
END;
