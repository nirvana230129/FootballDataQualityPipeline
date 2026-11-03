"""Compare progressive-pass definitions A / B / C (docs/metrics.md)."""

from __future__ import annotations

from src.db import connect


SQL = """
WITH base AS (
    SELECT
        e.canonical_match_id AS match_id,
        e.canonical_team_id AS team_id,
        e.canonical_player_id AS player_id,
        SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2)) AS distance_before,
        SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2)) AS distance_after,
        CASE
            WHEN SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2)) = 0 THEN NULL
            ELSE (
                SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
                - SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2))
            ) / SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
        END AS progression,
        SQRT(POWER(120 - e.x, 2) + POWER(40 - e.y, 2))
            - SQRT(POWER(120 - e.end_x, 2) + POWER(40 - e.end_y, 2)) AS absolute_reduction
    FROM core.events e
    JOIN monitoring.match_publication_status mps
      ON mps.canonical_match_id = e.canonical_match_id
     AND mps.publication_status = 'PUBLISHABLE'
    WHERE e.event_type = 'Pass'
      AND e.x IS NOT NULL AND e.y IS NOT NULL
      AND e.end_x IS NOT NULL AND e.end_y IS NOT NULL
)
SELECT
    COUNT(*) FILTER (WHERE progression >= 0.20) AS n_a,
    COUNT(*) FILTER (WHERE progression >= 0.25) AS n_b,
    COUNT(*) FILTER (
        WHERE progression >= 0.25 AND absolute_reduction >= 10
    ) AS n_c,
    (SELECT COUNT(*) FROM marts.progressive_passes) AS n_marts
FROM base
"""


def test_definitions_nested_and_marts_use_b():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            n_a, n_b, n_c, n_marts = cur.fetchone()

    assert n_a >= n_b >= n_c > 0
    assert n_marts == n_b
