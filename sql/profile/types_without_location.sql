-- Event types and how often location is missing.
SELECT
    event_type,
    COUNT(*) AS events,
    COUNT(*) FILTER (WHERE x IS NULL OR y IS NULL) AS missing_location,
    COUNT(*) FILTER (WHERE x IS NULL OR y IS NULL)::DOUBLE PRECISION
        / NULLIF(COUNT(*), 0) AS missing_location_rate
FROM staging.statsbomb_events
GROUP BY event_type
ORDER BY missing_location_rate DESC NULLS LAST, events DESC;
