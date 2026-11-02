from __future__ import annotations

import json
import uuid
from pathlib import Path

from src.db import connect
from src.load.publish import reconcile_publication
from src.load.raw import insert_raw_payload

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CORRUPTED_MATCH_ID = 888000001


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_corrupted_match(conn) -> None:
    match_id = CORRUPTED_MATCH_ID
    batch_id = uuid.uuid4()
    match = _load_json(FIXTURES / "corrupted" / "match.json")
    lineups = _load_json(FIXTURES / "corrupted" / "lineups.json")
    events = _load_json(FIXTURES / "corrupted" / "events.json")

    insert_raw_payload(
        conn,
        table="raw.statsbomb_matches",
        source_id=str(match_id),
        payload=match,
        batch_id=batch_id,
        entity_type="matches",
    )
    insert_raw_payload(
        conn,
        table="raw.statsbomb_lineups",
        source_id=str(match_id),
        payload=lineups,
        batch_id=batch_id,
        entity_type="lineups",
    )
    insert_raw_payload(
        conn,
        table="raw.statsbomb_events",
        source_id=str(match_id),
        payload=events,
        batch_id=batch_id,
        entity_type="events",
    )

    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.match_id', %s, true)", (str(match_id),))
        cur.execute("DELETE FROM staging.statsbomb_events WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_lineups WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_matches WHERE match_id = %s", (match_id,))
        # Match + lineups + DISTINCT ON events (raw keeps duplicate id).
        cur.execute(
            """
            INSERT INTO staging.statsbomb_matches (
                match_id, match_date, kick_off, competition_id, competition_name,
                season_id, season_name, home_team_id, home_team_name,
                away_team_id, away_team_name, home_score, away_score,
                source_batch_id, loaded_at
            )
            SELECT
                (m.payload ->> 'match_id')::BIGINT,
                (m.payload ->> 'match_date')::DATE,
                m.payload ->> 'kick_off',
                (m.payload -> 'competition' ->> 'competition_id')::BIGINT,
                m.payload -> 'competition' ->> 'competition_name',
                (m.payload -> 'season' ->> 'season_id')::BIGINT,
                m.payload -> 'season' ->> 'season_name',
                (m.payload -> 'home_team' ->> 'home_team_id')::BIGINT,
                m.payload -> 'home_team' ->> 'home_team_name',
                (m.payload -> 'away_team' ->> 'away_team_id')::BIGINT,
                m.payload -> 'away_team' ->> 'away_team_name',
                (m.payload ->> 'home_score')::INTEGER,
                (m.payload ->> 'away_score')::INTEGER,
                m.batch_id,
                NOW()
            FROM raw.statsbomb_matches_current m
            WHERE m.source_id = %s
            """,
            (str(match_id),),
        )
        cur.execute(
            """
            INSERT INTO staging.statsbomb_teams (team_id, team_name, source_batch_id, loaded_at)
            SELECT DISTINCT team_id, team_name, source_batch_id, NOW()
            FROM (
                SELECT home_team_id AS team_id, home_team_name AS team_name, source_batch_id
                FROM staging.statsbomb_matches WHERE match_id = %s
                UNION ALL
                SELECT away_team_id, away_team_name, source_batch_id
                FROM staging.statsbomb_matches WHERE match_id = %s
            ) t
            ON CONFLICT (team_id) DO UPDATE
            SET team_name = EXCLUDED.team_name
            """,
            (match_id, match_id),
        )
        cur.execute(
            """
            INSERT INTO staging.statsbomb_lineups (
                match_id, team_id, player_id, player_name, jersey_number,
                source_batch_id, loaded_at
            )
            SELECT
                %s,
                (team_elem ->> 'team_id')::BIGINT,
                (player_elem ->> 'player_id')::BIGINT,
                player_elem ->> 'player_name',
                NULLIF(player_elem ->> 'jersey_number', '')::INTEGER,
                l.batch_id,
                NOW()
            FROM raw.statsbomb_lineups_current l
            CROSS JOIN LATERAL jsonb_array_elements(l.payload) AS team_elem
            CROSS JOIN LATERAL jsonb_array_elements(team_elem -> 'lineup') AS player_elem
            WHERE l.source_id = %s
            """,
            (match_id, str(match_id)),
        )
        cur.execute(
            """
            INSERT INTO staging.statsbomb_players (player_id, player_name, source_batch_id, loaded_at)
            SELECT DISTINCT player_id, player_name, source_batch_id, NOW()
            FROM staging.statsbomb_lineups
            WHERE match_id = %s
            ON CONFLICT (player_id) DO UPDATE
            SET player_name = EXCLUDED.player_name
            """,
            (match_id,),
        )
        cur.execute(
            """
            INSERT INTO staging.statsbomb_events (
                event_id, match_id, event_index, period, minute, second,
                team_id, player_id, event_type, x, y, end_x, end_y, end_z,
                pass_recipient_id, pass_outcome, pass_length, is_cross,
                shot_xg, shot_outcome, carry_end_x, carry_end_y,
                possession, possession_team_id, source_batch_id, loaded_at
            )
            SELECT DISTINCT ON (e ->> 'id')
                e ->> 'id',
                %s,
                (e ->> 'index')::INTEGER,
                (e ->> 'period')::INTEGER,
                (e ->> 'minute')::INTEGER,
                (e ->> 'second')::INTEGER,
                NULLIF(e -> 'team' ->> 'id', '')::BIGINT,
                NULLIF(e -> 'player' ->> 'id', '')::BIGINT,
                e -> 'type' ->> 'name',
                NULLIF(e -> 'location' ->> 0, '')::DOUBLE PRECISION,
                NULLIF(e -> 'location' ->> 1, '')::DOUBLE PRECISION,
                CASE
                    WHEN e -> 'type' ->> 'name' = 'Pass'
                        THEN NULLIF(e -> 'pass' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
                    WHEN e -> 'type' ->> 'name' = 'Shot'
                        THEN NULLIF(e -> 'shot' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
                    WHEN e -> 'type' ->> 'name' = 'Carry'
                        THEN NULLIF(e -> 'carry' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
                END,
                CASE
                    WHEN e -> 'type' ->> 'name' = 'Pass'
                        THEN NULLIF(e -> 'pass' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
                    WHEN e -> 'type' ->> 'name' = 'Shot'
                        THEN NULLIF(e -> 'shot' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
                    WHEN e -> 'type' ->> 'name' = 'Carry'
                        THEN NULLIF(e -> 'carry' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
                END,
                CASE
                    WHEN e -> 'type' ->> 'name' = 'Shot'
                         AND jsonb_array_length(COALESCE(e -> 'shot' -> 'end_location', '[]'::jsonb)) >= 3
                        THEN NULLIF(e -> 'shot' -> 'end_location' ->> 2, '')::DOUBLE PRECISION
                END,
                NULLIF(e -> 'pass' -> 'recipient' ->> 'id', '')::BIGINT,
                e -> 'pass' -> 'outcome' ->> 'name',
                NULLIF(e -> 'pass' ->> 'length', '')::DOUBLE PRECISION,
                CASE WHEN e -> 'type' ->> 'name' = 'Pass'
                    THEN COALESCE((e -> 'pass' ->> 'cross')::BOOLEAN, FALSE) END,
                NULLIF(e -> 'shot' ->> 'statsbomb_xg', '')::DOUBLE PRECISION,
                e -> 'shot' -> 'outcome' ->> 'name',
                CASE WHEN e -> 'type' ->> 'name' = 'Carry'
                    THEN NULLIF(e -> 'carry' -> 'end_location' ->> 0, '')::DOUBLE PRECISION END,
                CASE WHEN e -> 'type' ->> 'name' = 'Carry'
                    THEN NULLIF(e -> 'carry' -> 'end_location' ->> 1, '')::DOUBLE PRECISION END,
                NULLIF(e ->> 'possession', '')::INTEGER,
                NULLIF(e -> 'possession_team' ->> 'id', '')::BIGINT,
                r.batch_id,
                NOW()
            FROM raw.statsbomb_events_current r
            CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e
            WHERE r.source_id = %s
            ORDER BY e ->> 'id', (e ->> 'index')::INTEGER
            """,
            (match_id, str(match_id)),
        )
        cur.execute((ROOT / "sql/core/build_statsbomb_match.sql").read_text(encoding="utf-8"))


def _detected_pairs(conn, run_id: uuid.UUID) -> set[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT check_name, details
            FROM monitoring.data_quality_results
            WHERE run_id = %s AND status = 'FAIL'
            """,
            (run_id,),
        )
        pairs: set[tuple[str, str]] = set()
        for check_name, details in cur.fetchall():
            examples = (details or {}).get("examples") if isinstance(details, dict) else None
            if not examples:
                pairs.add((check_name, "*"))
                continue
            for example in examples:
                if not isinstance(example, dict):
                    pairs.add((check_name, str(example)))
                    continue
                key = (
                    example.get("event_id")
                    or example.get("player_id")
                    or example.get("team_id")
                    or example.get("canonical_match_id")
                    or example.get("layer")
                    or "*"
                )
                pairs.add((check_name, str(key)))
    return pairs


def test_corrupted_fixture_detects_expected_anomalies():
    """Assert expected (check_name, key) pairs are a subset of detected failures."""
    expected = {
        ("duplicate_event_id", "evt-0"),
        ("event_team_not_in_match", "evt-unknown-team"),
        ("validate_event_location", "evt-oob"),
        ("player_not_in_squad", "evt-missing-player"),
        ("pass_required_fields", "evt-null-pass"),
        ("event_count_raw_staging_core", "*"),
        ("event_volume_anomaly", "*"),
    }

    run_id = uuid.uuid4()
    conn = connect()
    try:
        conn.autocommit = False
        _load_corrupted_match(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.match_id', %s, true)", (str(CORRUPTED_MATCH_ID),))
            cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))
            cur.execute("SELECT set_config('app.dq_mode', %s, true)", ("enforce",))
            cur.execute((ROOT / "sql/quality/phase1_checks.sql").read_text(encoding="utf-8"))
        detected = _detected_pairs(conn, run_id)
        missing = expected - detected
        assert not missing, f"missing detections: {missing}; detected={detected}"

        reconcile_publication(conn, run_id, "enforce")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT publication_status, is_quarantined
                FROM monitoring.match_publication_status mps
                JOIN core.match_source_mapping msm
                  ON msm.canonical_match_id = mps.canonical_match_id
                WHERE msm.provider = 'statsbomb'
                  AND msm.source_match_id = %s
                """,
                (str(CORRUPTED_MATCH_ID),),
            )
            status, quarantined = cur.fetchone()
        assert status == "QUARANTINED"
        assert quarantined is True
    finally:
        conn.rollback()
        conn.close()


def test_global_gate_zero_matches_fails():
    """Global CRITICAL fails when core.matches is empty (isolated transaction)."""
    run_id = uuid.uuid4()
    conn = connect()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Isolate: delete all matches in this transaction only.
            cur.execute("DELETE FROM monitoring.match_publication_status")
            cur.execute("DELETE FROM core.events")
            cur.execute("DELETE FROM core.lineups")
            cur.execute("DELETE FROM core.match_source_mapping")
            cur.execute("DELETE FROM core.matches")
            cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))
            cur.execute("SELECT set_config('app.dq_mode', %s, true)", ("observe",))
            cur.execute((ROOT / "sql/quality/global_checks.sql").read_text(encoding="utf-8"))
            cur.execute(
                """
                SELECT status FROM monitoring.data_quality_results
                WHERE run_id = %s AND check_name = 'zero_matches_loaded'
                """,
                (run_id,),
            )
            status = cur.fetchone()[0]
        assert status == "FAIL"
    finally:
        conn.rollback()
        conn.close()
