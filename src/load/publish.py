from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from psycopg import Connection

ROOT = Path(__file__).resolve().parents[2]


def _set_run_context(cur, run_id: uuid.UUID, dq_mode: str) -> None:
    cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))
    cur.execute("SELECT set_config('app.dq_mode', %s, true)", (dq_mode,))


def run_global_checks(conn: Connection, run_id: uuid.UUID, dq_mode: str) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        _set_run_context(cur, run_id, dq_mode)
        cur.execute((ROOT / "sql/quality/global_checks.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT check_name, severity, status, records_checked, records_failed, details
            FROM monitoring.data_quality_results
            WHERE run_id = %s
              AND canonical_match_id IS NULL
              AND check_name IN (
                  'missing_required_table_or_column',
                  'zero_matches_loaded',
                  'missing_team_source_mapping'
              )
            ORDER BY check_id
            """,
            (run_id,),
        )
        return cur.fetchall()


def reconcile_publication(conn: Connection, run_id: uuid.UUID, dq_mode: str) -> dict[str, int]:
    with conn.cursor() as cur:
        _set_run_context(cur, run_id, dq_mode)
        cur.execute((ROOT / "sql/quality/reconcile_publication.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE publication_status = 'PUBLISHABLE') AS publishable,
                COUNT(*) FILTER (WHERE publication_status = 'QUARANTINED') AS quarantined,
                COUNT(*) AS total
            FROM monitoring.match_publication_status
            """
        )
        publishable, quarantined, total = cur.fetchone()
    return {
        "publishable": int(publishable or 0),
        "quarantined": int(quarantined or 0),
        "total": int(total or 0),
    }


def global_gate_failed(rows: list[tuple[Any, ...]]) -> bool:
    return any(status == "FAIL" and severity == "CRITICAL" for _, severity, status, *_ in rows)


def rebuild_marts(conn: Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/marts/rebuild_phase1.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM marts.box_entries) AS box_entries,
                (SELECT COUNT(*) FROM marts.progressive_passes) AS progressive_passes,
                (SELECT COUNT(*) FROM marts.possessions) AS possessions,
                (SELECT COUNT(*) FROM marts.shot_possessions) AS shot_possessions,
                (
                    SELECT COUNT(*)
                    FROM monitoring.match_publication_status
                    WHERE publication_status = 'PUBLISHABLE'
                ) AS publishable_matches,
                (
                    SELECT COUNT(*)
                    FROM monitoring.match_publication_status
                    WHERE publication_status = 'QUARANTINED'
                ) AS quarantined_matches
            """
        )
        row = cur.fetchone()
    keys = (
        "box_entries",
        "progressive_passes",
        "possessions",
        "shot_possessions",
        "publishable_matches",
        "quarantined_matches",
    )
    return {key: int(value or 0) for key, value in zip(keys, row)}
