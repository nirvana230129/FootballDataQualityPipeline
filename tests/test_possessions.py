"""Possession mart uses possession_team, not event team (Pressure stays inside)."""

from __future__ import annotations

import uuid

from src.db import connect
from src.load.publish import rebuild_marts


def test_pressure_does_not_split_possession():
    match_key = f"poss-test-{uuid.uuid4().hex[:8]}"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO core.teams (team_name)
                VALUES ('Poss Home'), ('Poss Away')
                RETURNING canonical_team_id
                """
            )
            home_id, away_id = [row[0] for row in cur.fetchall()]
            cur.execute(
                """
                INSERT INTO core.matches (
                    canonical_home_team_id, canonical_away_team_id, home_score, away_score
                )
                VALUES (%s, %s, 0, 0)
                RETURNING canonical_match_id
                """,
                (home_id, away_id),
            )
            match_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO core.match_source_mapping (
                    canonical_match_id, provider, source_match_id, mapping_status
                )
                VALUES (%s, 'statsbomb', %s, 'matched')
                """,
                (match_id, match_key),
            )
            cur.execute(
                """
                INSERT INTO monitoring.match_publication_status (
                    canonical_match_id, dq_status, publication_status, is_quarantined,
                    critical_check_count, warning_check_count
                )
                VALUES (%s, 'PASS', 'PUBLISHABLE', FALSE, 0, 0)
                """,
                (match_id,),
            )
            # Pass(A), Pressure(B), Shot(A) — same StatsBomb possession.
            events = [
                ("evt-pass", 1, "Pass", home_id, 60.0, 40.0, 0.0),
                ("evt-pressure", 2, "Pressure", away_id, None, None, None),
                ("evt-shot", 3, "Shot", home_id, 105.0, 40.0, 0.15),
            ]
            for event_id, idx, etype, team_id, x, y, xg in events:
                cur.execute(
                    """
                    INSERT INTO core.events (
                        event_id, canonical_match_id, source_match_id, event_index,
                        period, minute, second, canonical_team_id, event_type,
                        x, y, shot_xg, shot_outcome, possession,
                        possession_team_id, canonical_possession_team_id
                    )
                    VALUES (
                        %s, %s, 0, %s, 1, 10, %s, %s, %s,
                        %s, %s, %s, %s, 42, %s, %s
                    )
                    """,
                    (
                        event_id,
                        match_id,
                        idx,
                        idx,
                        team_id,
                        etype,
                        x,
                        y,
                        xg,
                        "Goal" if etype == "Shot" else None,
                        home_id,  # source possession_team id unused in mart
                        home_id,
                    ),
                )

        rebuild_marts(conn)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT team_id, event_count, has_shot, has_goal, start_x, end_x
                FROM marts.possessions
                WHERE match_id = %s AND possession_id = 42
                """,
                (match_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            team_id, event_count, has_shot, has_goal, start_x, end_x = rows[0]
            assert team_id == home_id
            assert event_count == 3
            assert has_shot is True
            assert has_goal is True
            assert start_x == 60.0
            assert end_x == 105.0

            cur.execute(
                "DELETE FROM monitoring.match_publication_status WHERE canonical_match_id = %s",
                (match_id,),
            )
            cur.execute("DELETE FROM core.events WHERE canonical_match_id = %s", (match_id,))
            cur.execute(
                "DELETE FROM core.match_source_mapping WHERE canonical_match_id = %s",
                (match_id,),
            )
            cur.execute("DELETE FROM core.matches WHERE canonical_match_id = %s", (match_id,))
            cur.execute(
                "DELETE FROM core.teams WHERE canonical_team_id IN (%s, %s)",
                (home_id, away_id),
            )
        rebuild_marts(conn)
        conn.commit()
