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
        cur.execute((ROOT / "sql/staging/load_statsbomb_match.sql").read_text(encoding="utf-8"))
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
    from src.load.publish import run_global_checks

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
        rows = run_global_checks(conn, run_id, "observe")
        by_name = {r[0]: r[2] for r in rows}
        assert by_name["missing_required_table_or_column"] == "PASS"
        assert by_name["zero_matches_loaded"] == "FAIL"
    finally:
        conn.rollback()
        conn.close()


def test_schema_preflight_missing_relation_fails_without_crash():
    """Missing required table yields FAIL row; data checks are skipped."""
    from src.load.publish import run_global_checks

    run_id = uuid.uuid4()
    conn = connect()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE core.matches RENAME TO matches_hidden_for_test")
        rows = run_global_checks(conn, run_id, "observe")
        by_name = {r[0]: r for r in rows}
        assert "missing_required_table_or_column" in by_name
        assert by_name["missing_required_table_or_column"][2] == "FAIL"
        assert "zero_matches_loaded" not in by_name
    finally:
        conn.rollback()
        conn.close()
