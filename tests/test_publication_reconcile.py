"""Publication reconcile keeps earlier CRITICAL after a later PASS-only run."""

from __future__ import annotations

import uuid

from src.db import connect
from src.load.publish import reconcile_publication


def test_later_cross_pass_does_not_clear_match_critical():
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO core.teams (team_name)
                VALUES ('Rec Home'), ('Rec Away')
                RETURNING canonical_team_id
                """
            )
            home_id, away_id = [r[0] for r in cur.fetchall()]
            cur.execute(
                """
                INSERT INTO core.matches (
                    canonical_home_team_id, canonical_away_team_id, home_score, away_score
                )
                VALUES (%s, %s, 1, 0)
                RETURNING canonical_match_id
                """,
                (home_id, away_id),
            )
            match_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO monitoring.match_publication_status (
                    canonical_match_id, dq_status, publication_status, is_quarantined,
                    critical_check_count, warning_check_count
                )
                VALUES (%s, 'PENDING', 'PUBLISHABLE', FALSE, 0, 0)
                """,
                (match_id,),
            )
            # Run A: match-level CRITICAL FAIL (duplicate).
            cur.execute(
                """
                INSERT INTO monitoring.data_quality_results (
                    run_id, canonical_match_id, check_name, check_type,
                    severity, status, records_checked, records_failed
                )
                VALUES (%s, %s, 'duplicate_event_id', 'duplicate', 'CRITICAL', 'FAIL', 2, 1)
                """,
                (run_a, match_id),
            )
        reconcile_publication(conn, run_a, "enforce")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT publication_status, is_quarantined
                FROM monitoring.match_publication_status
                WHERE canonical_match_id = %s
                """,
                (match_id,),
            )
            status, quarantined = cur.fetchone()
            assert status == "QUARANTINED"
            assert quarantined is True

            # Run B: only cross-source PASS for the same match (old Airflow shape).
            cur.execute(
                """
                INSERT INTO monitoring.data_quality_results (
                    run_id, canonical_match_id, check_name, check_type,
                    severity, status, records_checked, records_failed
                )
                VALUES (
                    %s, %s, 'cross_source_score_mismatch', 'cross_source',
                    'CRITICAL', 'PASS', 1, 0
                )
                """,
                (run_b, match_id),
            )
        reconcile_publication(conn, run_b, "enforce")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT publication_status, is_quarantined, critical_check_count
                FROM monitoring.match_publication_status
                WHERE canonical_match_id = %s
                """,
                (match_id,),
            )
            status, quarantined, critical_count = cur.fetchone()
            assert status == "QUARANTINED"
            assert quarantined is True
            assert critical_count == 1

            cur.execute(
                "DELETE FROM monitoring.data_quality_results WHERE canonical_match_id = %s",
                (match_id,),
            )
            cur.execute(
                "DELETE FROM monitoring.match_publication_status WHERE canonical_match_id = %s",
                (match_id,),
            )
            cur.execute("DELETE FROM core.matches WHERE canonical_match_id = %s", (match_id,))
            cur.execute(
                "DELETE FROM core.teams WHERE canonical_team_id IN (%s, %s)",
                (home_id, away_id),
            )
        conn.commit()
