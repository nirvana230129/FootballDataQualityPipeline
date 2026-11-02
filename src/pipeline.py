from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from src.db import DDL_FILES, connect, execute_sql_file
from src.extract.statsbomb import fetch_events, fetch_lineups, fetch_match
from src.load.raw import insert_raw_payload
from src.visualization.box_entries import render_box_entries

ROOT = Path(__file__).resolve().parents[1]


def _dq_mode() -> str:
    return os.getenv("DQ_MODE", "observe").strip().lower() or "observe"


def cmd_init(_: argparse.Namespace) -> None:
    with connect() as conn:
        for path in DDL_FILES:
            execute_sql_file(conn, path)
        conn.commit()
    print("Database schemas initialized.")


def cmd_ingest(args: argparse.Namespace) -> None:
    match_id = args.match_id
    batch_id = uuid.uuid4()
    match = fetch_match(match_id)
    lineups = fetch_lineups(match_id)
    events = fetch_events(match_id)

    results = {}
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

    print(f"[ingest] match_id={match_id} batch_id={batch_id}")
    print(f"  matches={results['matches']} lineups={results['lineups']} events={results['events']}")
    print(f"  events_received={len(events)}")


def _set_match_context(cur, match_id: int, run_id: uuid.UUID | None = None) -> None:
    cur.execute("SELECT set_config('app.match_id', %s, true)", (str(match_id),))
    cur.execute("SELECT set_config('app.dq_mode', %s, true)", (_dq_mode(),))
    if run_id is not None:
        cur.execute("SELECT set_config('app.run_id', %s, true)", (str(run_id),))


def cmd_build(args: argparse.Namespace) -> None:
    match_id = args.match_id
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
    print(f"[build] match_id={match_id} staging_events={stg_events} core_events={core_events}")


def cmd_dq(args: argparse.Namespace) -> None:
    match_id = args.match_id
    run_id = uuid.uuid4()
    with connect() as conn, conn.cursor() as cur:
        _set_match_context(cur, match_id, run_id=run_id)
        cur.execute((ROOT / "sql/quality/phase1_checks.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT check_name, severity, status, records_checked, records_failed
            FROM monitoring.data_quality_results
            WHERE run_id = %s
            ORDER BY check_id
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        conn.commit()

    print(f"[dq] match_id={match_id} run_id={run_id} mode={_dq_mode()}")
    for check_name, severity, status, checked, failed in rows:
        print(f"  {check_name}: {status} ({severity}) checked={checked} failed={failed}")


def cmd_marts(_: argparse.Namespace) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute((ROOT / "sql/marts/rebuild_phase1.sql").read_text(encoding="utf-8"))
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM marts.box_entries) AS box_entries,
                (SELECT COUNT(*) FROM marts.progressive_passes) AS progressive_passes,
                (SELECT COUNT(*) FROM marts.possessions) AS possessions,
                (SELECT COUNT(*) FROM marts.shot_possessions) AS shot_possessions
            """
        )
        box_entries, progressive_passes, possessions, shot_possessions = cur.fetchone()
        conn.commit()
    print(
        "[marts] "
        f"box_entries={box_entries} "
        f"progressive_passes={progressive_passes} "
        f"possessions={possessions} "
        f"shot_possessions={shot_possessions}"
    )


def cmd_viz(args: argparse.Namespace) -> None:
    match_id = args.match_id
    output = ROOT / "artifacts" / f"box_entries_{match_id}.png"
    path = render_box_entries(match_id, output)
    print(f"[viz] wrote {path}")


def cmd_run(args: argparse.Namespace) -> None:
    if args.match_id is None and args.competition:
        raise SystemExit("Phase 1 supports --match-id. Full competition run comes in phase 2.")
    if args.match_id is None:
        raise SystemExit("--match-id is required for phase 1 run")

    cmd_init(args)
    cmd_ingest(args)
    cmd_build(args)
    cmd_dq(args)
    cmd_marts(args)
    cmd_viz(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create database schemas and config tables")
    p_init.set_defaults(func=cmd_init)

    p_ingest = sub.add_parser("ingest", help="Download StatsBomb payloads into raw")
    p_ingest.add_argument("--match-id", type=int, required=True)
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build", help="Build staging and core for a match")
    p_build.add_argument("--match-id", type=int, required=True)
    p_build.set_defaults(func=cmd_build)

    p_dq = sub.add_parser("dq", help="Run phase-1 data quality checks")
    p_dq.add_argument("--match-id", type=int, required=True)
    p_dq.set_defaults(func=cmd_dq)

    p_marts = sub.add_parser("marts", help="Rebuild analytics marts")
    p_marts.set_defaults(func=cmd_marts)

    p_viz = sub.add_parser("viz", help="Render box entries map")
    p_viz.add_argument("--match-id", type=int, required=True)
    p_viz.set_defaults(func=cmd_viz)

    p_run = sub.add_parser("run", help="Full phase-1 vertical slice")
    p_run.add_argument("--match-id", type=int, default=None)
    p_run.add_argument("--competition", type=str, default=None)
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
