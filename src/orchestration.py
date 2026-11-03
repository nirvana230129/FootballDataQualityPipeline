"""Thin wrappers for Airflow DAG tasks over existing CLI commands.

Business rules stay in src.pipeline / SQL — this module only routes calls.
"""

from __future__ import annotations

import argparse
from typing import Any


def _ns(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _call(fn, args: argparse.Namespace) -> None:
    """Run a cmd_* function; turn SystemExit into a normal exception for Airflow."""
    try:
        fn(args)
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return
        raise RuntimeError(f"pipeline step failed with exit code {code}") from exc


def run_init() -> None:
    from src.pipeline import cmd_init

    _call(cmd_init, _ns())


def run_extract(provider: str, competition: str = "WC2022") -> None:
    """Ingest raw (+ football-data staging) for a provider."""
    provider = provider.strip().lower()
    if provider in {"statsbomb", "sb"}:
        from src.pipeline import cmd_ingest

        _call(cmd_ingest, _ns(match_id=None, competition=competition))
        return
    if provider in {"football_data", "football-data", "fd"}:
        from src.pipeline import cmd_ingest_football_data

        _call(cmd_ingest_football_data, _ns(competition=competition))
        return
    raise ValueError(f"Unknown provider: {provider}")


def run_sql_step(step: str, competition: str = "WC2022") -> None:
    """Run a SQL-heavy pipeline step by name."""
    step = step.strip().lower()
    if step == "build":
        from src.pipeline import cmd_build

        _call(cmd_build, _ns(match_id=None, competition=competition))
        return
    if step in {"seed-teams", "seed_teams"}:
        from src.pipeline import cmd_seed_teams

        _call(cmd_seed_teams, _ns())
        return
    if step in {"resolve-matches", "resolve_matches"}:
        from src.pipeline import cmd_resolve_matches

        _call(cmd_resolve_matches, _ns())
        return
    if step == "marts":
        from src.pipeline import cmd_marts

        _call(cmd_marts, _ns())
        return
    raise ValueError(f"Unknown sql step: {step}")


def run_dq(competition: str = "WC2022") -> None:
    """Match DQ + cross-source DQ under one run_id, then one publication reconcile."""
    from src.pipeline import _resolve_match_ids, run_match_and_cross_dq

    match_ids = _resolve_match_ids(_ns(match_id=None, competition=competition))
    run_match_and_cross_dq(match_ids, run_cross=True, reconcile=True)


def run_resolve_entities() -> None:
    run_sql_step("seed-teams")
    run_sql_step("resolve-matches")
