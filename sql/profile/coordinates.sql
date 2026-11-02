-- Out-of-bounds coordinate rates for location fields.
WITH base AS (
    SELECT
        event_type,
        x,
        y,
        end_x,
        end_y,
        carry_end_x,
        carry_end_y
    FROM staging.statsbomb_events
),
checks AS (
    SELECT
        'event.location' AS field_name,
        COUNT(*) FILTER (WHERE x IS NOT NULL AND y IS NOT NULL) AS present,
        COUNT(*) FILTER (
            WHERE x IS NOT NULL AND y IS NOT NULL
              AND (x < 0 OR x > 120 OR y < 0 OR y > 80)
        ) AS out_of_bounds
    FROM base
    UNION ALL
    SELECT
        'pass.end_location',
        COUNT(*) FILTER (
            WHERE event_type = 'Pass' AND end_x IS NOT NULL AND end_y IS NOT NULL
        ),
        COUNT(*) FILTER (
            WHERE event_type = 'Pass'
              AND end_x IS NOT NULL AND end_y IS NOT NULL
              AND (end_x < 0 OR end_x > 120 OR end_y < 0 OR end_y > 80)
        )
    FROM base
    UNION ALL
    SELECT
        'carry.end_location',
        COUNT(*) FILTER (
            WHERE event_type = 'Carry'
              AND carry_end_x IS NOT NULL AND carry_end_y IS NOT NULL
        ),
        COUNT(*) FILTER (
            WHERE event_type = 'Carry'
              AND carry_end_x IS NOT NULL AND carry_end_y IS NOT NULL
              AND (
                  carry_end_x < 0 OR carry_end_x > 120
                  OR carry_end_y < 0 OR carry_end_y > 80
              )
        )
    FROM base
    UNION ALL
    SELECT
        'shot.end_location',
        COUNT(*) FILTER (
            WHERE event_type = 'Shot' AND end_x IS NOT NULL AND end_y IS NOT NULL
        ),
        COUNT(*) FILTER (
            WHERE event_type = 'Shot'
              AND end_x IS NOT NULL AND end_y IS NOT NULL
              AND (end_x < 0 OR end_x > 120 OR end_y < 0 OR end_y > 80)
        )
    FROM base
)
SELECT
    field_name,
    present,
    out_of_bounds,
    CASE
        WHEN present = 0 THEN NULL
        ELSE out_of_bounds::DOUBLE PRECISION / present::DOUBLE PRECISION
    END AS out_of_bounds_rate
FROM checks
ORDER BY field_name;
