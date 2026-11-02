from __future__ import annotations

import argparse
import csv
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterable

from src.db import DDL_FILES, connect, execute_sql_file
from src.extract import football_api
from src.extract.statsbomb import (
    FINAL_MATCH_ID,
    fetch_competition_matches,
    fetch_events,
    fetch_lineups,
    fetch_match,
    list_match_ids,
    resolve_competition,
)
from src.load.football_staging import load_football_data_staging
from src.load.match_resolve import resolve_matches
from src.load.publish import (
    global_gate_failed,
    rebuild_marts,
    reconcile_publication,
    run_global_checks,
)
from src.load.raw import insert_raw_payload
from src.load.seed_teams import seed_teams_from_csv
from src.visualization.box_entries import render_box_entries

ROOT = Path(__file__).resolve().parents[1]
DEMO_QUARANTINE_MATCH_ID = 999000001


def _dq_mode() -> str:
    return os.getenv("DQ_MODE", "observe").strip().lower() or "observe"


def _resolve_match_ids(args: argparse.Namespace) -> list[int]:
    if getattr(args, "match_id", None) is not None:
        return [int(args.match_id)]
    competition = getattr(args, "competition", None)
    if competition:
        match_ids = list_match_ids(competition)
        if not match_ids:
            raise SystemExit(f"No matches found for competition {competition}")
        return match_ids
    raise SystemExit("Provide --match-id or --competition WC2022")


def cmd_init(_: argparse.Namespace) -> None:
    with connect() as conn:
        for path in DDL_FILES:
            execute_sql_file(conn, path)
        conn.commit()
    print("Database schemas initialized.")


def _ingest_one(match_id: int, match_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    batch_id = uuid.uuid4()
    match = match_payload if match_payload is not None else fetch_match(match_id)
    lineups = fetch_lineups(match_id)
    events = fetch_events(match_id)

    results: dict[str, str] = {}
    with connect() as conn:
        results["matches"] = insert_raw_payload(
            conn,
            table="raw.statsbomb_matches",
            source_id=str(match_id),
            payload=match,
            batch_id=batch_id,
            entity_type="matches",
        )
        results["lineups"] = insert_raw_payload(
            conn,
            table="raw.statsbomb_lineups",
            source_id=str(match_id),
            payload=lineups,
            batch_id=batch_id,
            entity_type="lineups",
        )
        results["events"] = insert_raw_payload(
            conn,
            table="raw.statsbomb_events",
            source_id=str(match_id),
            payload=events,
            batch_id=batch_id,
            entity_type="events",
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO monitoring.pipeline_runs (
                    run_id, status, source, records_extracted, records_loaded,
                    records_skipped_same_hash, dq_mode, finished_at
                ) VALUES (
                    %s, 'SUCCESS', 'statsbomb', %s, %s, %s, %s, NOW()
                )
                """,
                (
                    batch_id,
                    3,
                    sum(1 for v in results.values() if v == "loaded"),
                    sum(1 for v in results.values() if v == "skipped_same_hash"),
                    _dq_mode(),
                ),
            )
        conn.commit()

    return {
        "match_id": match_id,
        "batch_id": str(batch_id),
        "results": results,
        "events_received": len(events),
    }


def cmd_ingest(args: argparse.Namespace) -> None:
    match_ids = _resolve_match_ids(args)
    matches_by_id: dict[int, dict[str, Any]] | None = None
    if getattr(args, "competition", None):
        competition_id, season_id = resolve_competition(args.competition)
        rows = fetch_competition_matches(competition_id, season_id)
        matches_by_id = {int(row["match_id"]): row for row in rows}

    print(f"[ingest] matches={len(match_ids)}")
    for index, match_id in enumerate(match_ids, start=1):
        payload = matches_by_id.get(match_id) if matches_by_id else None
        outcome = _ingest_one(match_id, match_payload=payload)
        results = outcome["results"]
        print(
            f"  [{index}/{len(match_ids)}] match_id={match_id} "
            f"matches={results['matches']} lineups={results['lineups']} "
            f"events={results['events']} events_received={outcome['events_received']}"
        )


def _set_match_context(cur, match_id: int, run_id: uuid.UUID | None = None) -> None:
    cur.execute("SELECT set_config('app.match_id', %s, true)", (str(match_id),))
    cur.execute("SELECT set_config('app.dq_mode', %s, true)", (_dq_mode(),))
    if run_id is not None:
        cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))


def _build_one(match_id: int) -> tuple[int, int]:
    with connect() as conn, conn.cursor() as cur:
        _set_match_context(cur, match_id)
        cur.execute((ROOT / "sql/staging/load_statsbomb_match.sql").read_text(encoding="utf-8"))
        cur.execute((ROOT / "sql/core/build_statsbomb_match.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM staging.statsbomb_events WHERE match_id = %s) AS stg_events,
                (
                    SELECT COUNT(*)
                    FROM core.events e
                    JOIN core.match_source_mapping msm
                      ON msm.canonical_match_id = e.canonical_match_id
                    WHERE msm.provider = 'statsbomb'
                      AND msm.source_match_id = %s
                ) AS core_events
            """,
            (match_id, str(match_id)),
        )
        stg_events, core_events = cur.fetchone()
        conn.commit()
    return int(stg_events), int(core_events)


def cmd_build(args: argparse.Namespace) -> None:
    match_ids = _resolve_match_ids(args)
    print(f"[build] matches={len(match_ids)}")
    for index, match_id in enumerate(match_ids, start=1):
        stg_events, core_events = _build_one(match_id)
        print(
            f"  [{index}/{len(match_ids)}] match_id={match_id} "
            f"staging_events={stg_events} core_events={core_events}"
        )


def _dq_one(
    match_id: int,
    *,
    run_id: uuid.UUID | None = None,
    conn=None,
    commit: bool = True,
) -> list[tuple[Any, ...]]:
    own_conn = conn is None
    if own_conn:
        conn = connect()
    assert conn is not None
    run = run_id or uuid.uuid4()
    try:
        with conn.cursor() as cur:
            _set_match_context(cur, match_id, run_id=run)
            cur.execute((ROOT / "sql/quality/phase1_checks.sql").read_text(encoding="utf-8"))
            cur.execute(
                """
                SELECT check_name, severity, status, records_checked, records_failed
                FROM monitoring.data_quality_results
                WHERE run_id = %s
                  AND canonical_match_id = (
                      SELECT canonical_match_id
                      FROM core.match_source_mapping
                      WHERE provider = 'statsbomb'
                        AND source_match_id = %s
                  )
                ORDER BY check_id
                """,
                (run, str(match_id)),
            )
            rows = cur.fetchall()
        if commit and own_conn:
            conn.commit()
        return rows
    finally:
        if own_conn:
            conn.close()


def cmd_dq(args: argparse.Namespace) -> uuid.UUID:
    match_ids = _resolve_match_ids(args)
    run_id = uuid.uuid4()
    mode = _dq_mode()
    print(f"[dq] matches={len(match_ids)} mode={mode} run_id={run_id}")
    fail_matches = 0
    with connect() as conn:
        for index, match_id in enumerate(match_ids, start=1):
            rows = _dq_one(match_id, run_id=run_id, conn=conn, commit=False)
            failed = [row for row in rows if row[2] == "FAIL"]
            if failed:
                fail_matches += 1
            summary = ", ".join(f"{name}:{status}" for name, _, status, _, _ in rows)
            print(f"  [{index}/{len(match_ids)}] match_id={match_id} {summary}")
        reconcile_publication(conn, run_id, mode)
        conn.commit()
    print(f"[dq] matches_with_failures={fail_matches}/{len(match_ids)}")
    return run_id


def cmd_marts(_: argparse.Namespace) -> None:
    run_id = uuid.uuid4()
    mode = _dq_mode()
    with connect() as conn:
        global_rows = run_global_checks(conn, run_id, mode)
        print(f"[marts] global gate run_id={run_id}")
        for check_name, severity, status, checked, failed, details in global_rows:
            print(
                f"  {check_name}: {status} ({severity}) "
                f"checked={checked} failed={failed} details={details}"
            )
        if global_gate_failed(global_rows):
            conn.commit()
            raise SystemExit("[marts] stop publish: global CRITICAL failed")
        stats = rebuild_marts(conn)
        conn.commit()
    print(
        "[marts] "
        f"publishable_matches={stats['publishable_matches']} "
        f"quarantined_matches={stats['quarantined_matches']} "
        f"box_entries={stats['box_entries']} "
        f"progressive_passes={stats['progressive_passes']} "
        f"possessions={stats['possessions']} "
        f"shot_possessions={stats['shot_possessions']}"
    )


def cmd_viz(args: argparse.Namespace) -> None:
    match_id = args.match_id if args.match_id is not None else FINAL_MATCH_ID
    output = ROOT / "artifacts" / f"box_entries_{match_id}.png"
    path = render_box_entries(match_id, output)
    print(f"[viz] wrote {path}")


def _write_csv(path: Path, headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(headers))
        for row in rows:
            writer.writerow(list(row))


def cmd_profile(args: argparse.Namespace) -> None:
    if args.competition:
        resolve_competition(args.competition)

    out_dir = ROOT / "artifacts" / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM raw.statsbomb_matches_current) AS raw_matches,
                (SELECT COUNT(*) FROM staging.statsbomb_matches) AS staging_matches,
                (SELECT COUNT(*) FROM core.match_source_mapping WHERE provider = 'statsbomb') AS core_matches,
                (SELECT COUNT(*) FROM staging.statsbomb_events) AS staging_events
            """
        )
        raw_matches, staging_matches, core_matches, staging_events = cur.fetchone()

        cur.execute((ROOT / "sql/profile/event_volumes.sql").read_text(encoding="utf-8"))
        volume_rows = cur.fetchall()
        volume_headers = [desc.name for desc in cur.description]

        cur.execute((ROOT / "sql/profile/coordinates.sql").read_text(encoding="utf-8"))
        coord_rows = cur.fetchall()
        coord_headers = [desc.name for desc in cur.description]

        cur.execute((ROOT / "sql/profile/types_without_location.sql").read_text(encoding="utf-8"))
        type_rows = cur.fetchall()
        type_headers = [desc.name for desc in cur.description]

    _write_csv(out_dir / "event_volumes.csv", volume_headers, volume_rows)
    _write_csv(out_dir / "coordinates.csv", coord_headers, coord_rows)
    _write_csv(out_dir / "types_without_location.csv", type_headers, type_rows)

    summary = {
        "raw_matches": raw_matches,
        "staging_matches": staging_matches,
        "core_matches": core_matches,
        "staging_events": staging_events,
        "event_volumes": [dict(zip(volume_headers, row)) for row in volume_rows],
        "coordinates": [dict(zip(coord_headers, row)) for row in coord_rows],
        "types_without_location": [dict(zip(type_headers, row)) for row in type_rows],
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print(
        f"[profile] raw_matches={raw_matches} staging_matches={staging_matches} "
        f"core_matches={core_matches} staging_events={staging_events}"
    )
    print("[profile] event volumes")
    for row in volume_rows:
        print(
            f"  {row[0]}: min={row[2]} p05={row[3]} p25={row[4]} median={row[5]} "
            f"p75={row[6]} p95={row[7]} max={row[8]} iqr={row[9]}"
        )
    print("[profile] coordinates out-of-bounds")
    for row in coord_rows:
        print(f"  {row[0]}: present={row[1]} oob={row[2]} rate={row[3]}")
    print("[profile] types with missing location (top 10)")
    for row in type_rows[:10]:
        print(f"  {row[0]}: events={row[1]} missing={row[2]} rate={row[3]}")
    print(f"[profile] wrote {summary_path}")


def cmd_ingest_football_data(args: argparse.Namespace) -> None:
    competition = (args.competition or "WC2022").upper()
    if competition not in {"WC2022", "WC"}:
        raise SystemExit("football-data ingest currently supports WC2022 only")

    batch_id = uuid.uuid4()
    print("[ingest-football-data] fetching competition/teams/matches...")
    competition_payload = football_api.fetch_competition()
    teams_payload = football_api.fetch_teams()
    matches_payload = football_api.fetch_matches()
    standings_payload = football_api.fetch_standings()

    with connect() as conn:
        results = {
            "competitions": insert_raw_payload(
                conn,
                table="raw.football_data_competitions",
                source_id="WC",
                payload=competition_payload,
                batch_id=batch_id,
                provider="football_data",
                entity_type="competitions",
            ),
            "teams": insert_raw_payload(
                conn,
                table="raw.football_data_teams",
                source_id="WC-2022",
                payload=teams_payload,
                batch_id=batch_id,
                provider="football_data",
                entity_type="teams",
            ),
            "matches": insert_raw_payload(
                conn,
                table="raw.football_data_matches",
                source_id="WC-2022",
                payload=matches_payload,
                batch_id=batch_id,
                provider="football_data",
                entity_type="matches",
            ),
        }
        if standings_payload is not None:
            results["standings"] = insert_raw_payload(
                conn,
                table="raw.football_data_standings",
                source_id="WC-2022",
                payload=standings_payload,
                batch_id=batch_id,
                provider="football_data",
                entity_type="standings",
            )
        else:
            results["standings"] = "skipped_unavailable"

        staging_counts = load_football_data_staging(conn)
        conn.commit()

    source = (matches_payload.get("filters") or {}).get("source", "api")
    print(f"[ingest-football-data] source={source} batch_id={batch_id}")
    print(f"  raw={results}")
    print(f"  staging={staging_counts}")
    print(f"  matches={len(matches_payload.get('matches', []))}")


def cmd_seed_teams(_: argparse.Namespace) -> None:
    with connect() as conn:
        stats = seed_teams_from_csv(conn)
        conn.commit()
    print(f"[seed-teams] {stats}")


def cmd_resolve_matches(_: argparse.Namespace) -> None:
    with connect() as conn:
        stats = resolve_matches(conn)
        conn.commit()
    total = stats["matched"] + stats["unmatched"] + stats["ambiguous"]
    coverage = (100.0 * stats["matched"] / total) if total else 0.0
    print(
        "[resolve-matches] "
        f"matched={stats['matched']} unmatched={stats['unmatched']} "
        f"ambiguous={stats['ambiguous']} coverage={coverage:.2f}%"
    )


def cmd_dq_cross(args: argparse.Namespace | None = None, *, run_id: uuid.UUID | None = None) -> uuid.UUID:
    run = run_id or uuid.uuid4()
    mode = _dq_mode()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run),))
        cur.execute("SELECT set_config('app.dq_mode', %s, true)", (mode,))
        cur.execute((ROOT / "sql/quality/cross_source_checks.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT check_name, severity, status, records_checked, records_failed, details
            FROM monitoring.data_quality_results
            WHERE run_id = %s
              AND check_name IN (
                  'football_data_score_arithmetic',
                  'cross_source_score_mismatch',
                  'cross_source_kickoff_mismatch',
                  'mapping_coverage'
              )
            ORDER BY check_id
            """,
            (run,),
        )
        rows = cur.fetchall()
        reconcile_publication(conn, run, mode)
        conn.commit()

    print(f"[dq-cross] run_id={run} mode={mode}")
    # Aggregate score mismatch for readable summary.
    score_rows = [r for r in rows if r[0] == "cross_source_score_mismatch"]
    other_rows = [r for r in rows if r[0] != "cross_source_score_mismatch"]
    if score_rows:
        failed = sum(1 for r in score_rows if r[2] == "FAIL")
        severity = score_rows[0][1]
        status = "FAIL" if failed else "PASS"
        print(
            f"  cross_source_score_mismatch: {status} ({severity}) "
            f"checked={len(score_rows)} failed={failed}"
        )
    for check_name, severity, status, checked, failed, details in other_rows:
        print(
            f"  {check_name}: {status} ({severity}) "
            f"checked={checked} failed={failed} details={details}"
        )
    return run


def _cleanup_demo_quarantine(conn) -> None:
    match_id = DEMO_QUARANTINE_MATCH_ID
    source_id = str(match_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT canonical_match_id
            FROM core.match_source_mapping
            WHERE provider = 'statsbomb' AND source_match_id = %s
            """,
            (source_id,),
        )
        row = cur.fetchone()
        canonical_id = row[0] if row else None

        cur.execute("DELETE FROM staging.statsbomb_events WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_lineups WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_matches WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM raw.statsbomb_events WHERE source_id = %s", (source_id,))
        cur.execute("DELETE FROM raw.statsbomb_lineups WHERE source_id = %s", (source_id,))
        cur.execute("DELETE FROM raw.statsbomb_matches WHERE source_id = %s", (source_id,))
        if canonical_id is not None:
            cur.execute("DELETE FROM core.events WHERE canonical_match_id = %s", (canonical_id,))
            cur.execute("DELETE FROM core.lineups WHERE canonical_match_id = %s", (canonical_id,))
            cur.execute(
                "DELETE FROM monitoring.match_publication_status WHERE canonical_match_id = %s",
                (canonical_id,),
            )
            cur.execute(
                "DELETE FROM core.match_source_mapping WHERE canonical_match_id = %s",
                (canonical_id,),
            )
            cur.execute("DELETE FROM core.matches WHERE canonical_match_id = %s", (canonical_id,))


def _inject_demo_quarantine_match(conn) -> None:
    """Insert a synthetic match that fails CRITICAL duplicate_event_id in enforce."""
    from src.load.raw import insert_raw_payload as _insert

    match_id = DEMO_QUARANTINE_MATCH_ID
    batch_id = uuid.uuid4()
    home_team_id = 999001
    away_team_id = 999002
    player_id = 999101

    match_payload = {
        "match_id": match_id,
        "match_date": "2022-12-01",
        "kick_off": "18:00:00.000",
        "competition": {"competition_id": 43, "competition_name": "FIFA World Cup"},
        "season": {"season_id": 106, "season_name": "2022"},
        "home_team": {"home_team_id": home_team_id, "home_team_name": "Demo Home"},
        "away_team": {"away_team_id": away_team_id, "away_team_name": "Demo Away"},
        "home_score": 1,
        "away_score": 0,
    }
    lineups_payload = [
        {
            "team_id": home_team_id,
            "team_name": "Demo Home",
            "lineup": [
                {"player_id": player_id, "player_name": "Demo Player", "jersey_number": 10}
            ],
        },
        {"team_id": away_team_id, "team_name": "Demo Away", "lineup": []},
    ]
    # Enough events to avoid volume anomaly. Duplicate id in raw → CRITICAL.
    events_payload = []
    for i in range(2100):
        events_payload.append(
            {
                "id": f"demo-event-{i}",
                "index": i,
                "period": 1,
                "minute": min(i // 60, 90),
                "second": i % 60,
                "type": {"name": "Pass"},
                "team": {"id": home_team_id},
                "player": {"id": player_id},
                "location": [60.0, 40.0],
                "pass": {
                    "end_location": [70.0, 40.0],
                    "length": 10.0,
                },
            }
        )
    events_payload.append(
        {
            "id": "demo-event-0",
            "index": 2100,
            "period": 1,
            "minute": 35,
            "second": 0,
            "type": {"name": "Pass"},
            "team": {"id": home_team_id},
            "player": {"id": player_id},
            "location": [60.0, 40.0],
            "pass": {"end_location": [70.0, 40.0], "length": 10.0},
        }
    )

    _cleanup_demo_quarantine(conn)
    _insert(
        conn,
        table="raw.statsbomb_matches",
        source_id=str(match_id),
        payload=match_payload,
        batch_id=batch_id,
        entity_type="matches",
    )
    _insert(
        conn,
        table="raw.statsbomb_lineups",
        source_id=str(match_id),
        payload=lineups_payload,
        batch_id=batch_id,
        entity_type="lineups",
    )
    _insert(
        conn,
        table="raw.statsbomb_events",
        source_id=str(match_id),
        payload=events_payload,
        batch_id=batch_id,
        entity_type="events",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.match_id', %s, true)", (str(match_id),))
        cur.execute("DELETE FROM staging.statsbomb_events WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_lineups WHERE match_id = %s", (match_id,))
        cur.execute("DELETE FROM staging.statsbomb_matches WHERE match_id = %s", (match_id,))
        # Match + lineups from raw (standard fragment), events via DISTINCT ON.
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
            SET team_name = EXCLUDED.team_name,
                source_batch_id = EXCLUDED.source_batch_id,
                loaded_at = EXCLUDED.loaded_at
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
            SET player_name = EXCLUDED.player_name,
                source_batch_id = EXCLUDED.source_batch_id,
                loaded_at = EXCLUDED.loaded_at
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
                NULLIF(e -> 'pass' -> 'end_location' ->> 0, '')::DOUBLE PRECISION,
                NULLIF(e -> 'pass' -> 'end_location' ->> 1, '')::DOUBLE PRECISION,
                NULL,
                NULL, NULL,
                NULLIF(e -> 'pass' ->> 'length', '')::DOUBLE PRECISION,
                FALSE,
                NULL, NULL, NULL, NULL,
                NULL, NULL,
                r.batch_id,
                NOW()
            FROM raw.statsbomb_events_current r
            CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e
            WHERE r.source_id = %s
            ORDER BY e ->> 'id', (e ->> 'index')::INTEGER
            """,
            (match_id, str(match_id)),
        )
        cur.execute("SELECT set_config('app.match_id', %s, true)", (str(match_id),))
        cur.execute((ROOT / "sql/core/build_statsbomb_match.sql").read_text(encoding="utf-8"))


def cmd_phase3(args: argparse.Namespace) -> None:
    cmd_init(args)
    cmd_ingest_football_data(args)
    cmd_seed_teams(args)
    cmd_resolve_matches(args)
    cmd_dq_cross(args)


def cmd_phase4(args: argparse.Namespace) -> None:
    """Match DQ + cross-source + reconcile + global gate + marts (enforce by default)."""
    previous_mode = os.environ.get("DQ_MODE")
    os.environ["DQ_MODE"] = "enforce"
    demo = bool(getattr(args, "demo_quarantine", False))
    try:
        run_id = uuid.uuid4()
        print(f"[phase4] mode=enforce run_id={run_id} demo_quarantine={demo}")

        if demo:
            with connect() as conn:
                _inject_demo_quarantine_match(conn)
                conn.commit()
            print(f"[phase4] injected demo match_id={DEMO_QUARANTINE_MATCH_ID}")

        match_ids = _resolve_match_ids(args)
        if demo and DEMO_QUARANTINE_MATCH_ID not in match_ids:
            match_ids = list(match_ids) + [DEMO_QUARANTINE_MATCH_ID]

        fail_matches = 0
        with connect() as conn:
            for index, match_id in enumerate(match_ids, start=1):
                rows = _dq_one(match_id, run_id=run_id, conn=conn, commit=False)
                failed = [row for row in rows if row[2] == "FAIL"]
                if failed:
                    fail_matches += 1
                critical = [row for row in failed if row[1] == "CRITICAL"]
                flag = " CRITICAL" if critical else ""
                print(
                    f"  [{index}/{len(match_ids)}] match_id={match_id} "
                    f"fails={len(failed)}{flag}"
                )

            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))
                cur.execute("SELECT set_config('app.dq_mode', %s, true)", ("enforce",))
                cur.execute(
                    (ROOT / "sql/quality/cross_source_checks.sql").read_text(encoding="utf-8")
                )

            pub = reconcile_publication(conn, run_id, "enforce")
            print(
                f"[phase4] publication publishable={pub['publishable']} "
                f"quarantined={pub['quarantined']} total={pub['total']}"
            )
            print(f"[phase4] matches_with_failures={fail_matches}/{len(match_ids)}")

            global_rows = run_global_checks(conn, run_id, "enforce")
            for check_name, severity, status, checked, failed, details in global_rows:
                print(
                    f"  global {check_name}: {status} ({severity}) "
                    f"checked={checked} failed={failed}"
                )
            if global_gate_failed(global_rows):
                conn.commit()
                raise SystemExit("[phase4] stop publish: global CRITICAL failed")

            stats = rebuild_marts(conn)
            conn.commit()

        print(
            "[phase4] marts "
            f"publishable={stats['publishable_matches']} "
            f"quarantined={stats['quarantined_matches']} "
            f"box_entries={stats['box_entries']}"
        )

        if demo:
            with connect() as conn:
                _cleanup_demo_quarantine(conn)
                # Restore publication for remaining matches after demo cleanup.
                rebuild_marts(conn)
                conn.commit()
            print(f"[phase4] cleaned demo match_id={DEMO_QUARANTINE_MATCH_ID}")
    finally:
        if previous_mode is None:
            os.environ.pop("DQ_MODE", None)
        else:
            os.environ["DQ_MODE"] = previous_mode


def cmd_run(args: argparse.Namespace) -> None:
    if args.match_id is None and not args.competition:
        raise SystemExit("Provide --match-id or --competition WC2022")

    cmd_init(args)
    cmd_ingest(args)
    cmd_build(args)
    cmd_dq(args)
    cmd_marts(args)

    viz_args = argparse.Namespace(
        match_id=args.match_id if args.match_id is not None else FINAL_MATCH_ID
    )
    cmd_viz(viz_args)

    if args.competition:
        cmd_profile(args)


def _add_scope_args(parser: argparse.ArgumentParser, *, require_one: bool = False) -> None:
    parser.add_argument("--match-id", type=int, default=None)
    parser.add_argument("--competition", type=str, default=None)
    if require_one:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create database schemas and config tables")
    p_init.set_defaults(func=cmd_init)

    p_ingest = sub.add_parser("ingest", help="Download StatsBomb payloads into raw")
    _add_scope_args(p_ingest)
    p_ingest.set_defaults(func=cmd_ingest)

    p_ingest_fd = sub.add_parser(
        "ingest-football-data",
        help="Ingest football-data.org WC2022 (API or bootstrap fixture)",
    )
    p_ingest_fd.add_argument("--competition", type=str, default="WC2022")
    p_ingest_fd.set_defaults(func=cmd_ingest_football_data)

    p_seed = sub.add_parser("seed-teams", help="Load manual team source mapping seed")
    p_seed.set_defaults(func=cmd_seed_teams)

    p_resolve = sub.add_parser("resolve-matches", help="Match football-data matches to core")
    p_resolve.set_defaults(func=cmd_resolve_matches)

    p_build = sub.add_parser("build", help="Build staging and core")
    _add_scope_args(p_build)
    p_build.set_defaults(func=cmd_build)

    p_dq = sub.add_parser("dq", help="Run StatsBomb data quality checks")
    _add_scope_args(p_dq)
    p_dq.set_defaults(func=cmd_dq)

    p_dq_cross = sub.add_parser("dq-cross", help="Run cross-source DQ checks")
    p_dq_cross.set_defaults(func=cmd_dq_cross)

    p_marts = sub.add_parser("marts", help="Rebuild analytics marts")
    p_marts.set_defaults(func=cmd_marts)

    p_viz = sub.add_parser("viz", help="Render box entries map")
    p_viz.add_argument("--match-id", type=int, default=FINAL_MATCH_ID)
    p_viz.set_defaults(func=cmd_viz)

    p_profile = sub.add_parser("profile", help="Profile volumes, coordinates, and event types")
    p_profile.add_argument("--competition", type=str, default="WC2022")
    p_profile.set_defaults(func=cmd_profile)

    p_phase3 = sub.add_parser("phase3", help="Run football-data integration steps")
    p_phase3.add_argument("--competition", type=str, default="WC2022")
    p_phase3.set_defaults(func=cmd_phase3)

    p_phase4 = sub.add_parser(
        "phase4",
        help="Enforce DQ, reconcile publication, global gate, rebuild marts",
    )
    p_phase4.add_argument("--competition", type=str, default="WC2022")
    p_phase4.add_argument("--match-id", type=int, default=None)
    p_phase4.add_argument(
        "--demo-quarantine",
        action="store_true",
        help="Inject a synthetic CRITICAL match, show quarantine, then clean up",
    )
    p_phase4.set_defaults(func=cmd_phase4)

    p_run = sub.add_parser("run", help="Full StatsBomb pipeline for one match or WC2022")
    _add_scope_args(p_run)
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
