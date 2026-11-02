from __future__ import annotations

import time
from typing import Any

import requests

STATSBOMB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
WC2022_COMPETITION_ID = 43
WC2022_SEASON_ID = 106
WC2022_CODE = "WC2022"
FINAL_MATCH_ID = 3869685

REQUEST_PAUSE_SECONDS = 0.35
MAX_RETRIES = 3


def _get_json(url: str) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=60)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"retryable status {response.status_code} for {url}",
                    response=response,
                )
            response.raise_for_status()
            time.sleep(REQUEST_PAUSE_SECONDS)
            return response.json()
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status in {429, 500, 502, 503, 504} or isinstance(
                exc, (requests.ConnectionError, requests.Timeout)
            )
            if not retryable or attempt == MAX_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"failed to fetch {url}") from last_error


def resolve_competition(competition: str) -> tuple[int, int]:
    code = competition.strip().upper()
    if code in {WC2022_CODE, "WC"}:
        return WC2022_COMPETITION_ID, WC2022_SEASON_ID
    raise ValueError(f"Unsupported competition '{competition}'. Use WC2022.")


def fetch_competition_matches(
    competition_id: int = WC2022_COMPETITION_ID,
    season_id: int = WC2022_SEASON_ID,
) -> list[dict[str, Any]]:
    url = f"{STATSBOMB_BASE}/matches/{competition_id}/{season_id}.json"
    return _get_json(url)


def list_match_ids(competition: str = WC2022_CODE) -> list[int]:
    competition_id, season_id = resolve_competition(competition)
    matches = fetch_competition_matches(competition_id, season_id)
    return sorted(int(match["match_id"]) for match in matches)


def fetch_match(match_id: int, matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = matches if matches is not None else fetch_competition_matches()
    for match in rows:
        if int(match["match_id"]) == int(match_id):
            return match
    raise ValueError(f"StatsBomb match {match_id} not found in WC 2022 open data")


def fetch_lineups(match_id: int) -> list[dict[str, Any]]:
    return _get_json(f"{STATSBOMB_BASE}/lineups/{match_id}.json")


def fetch_events(match_id: int) -> list[dict[str, Any]]:
    return _get_json(f"{STATSBOMB_BASE}/events/{match_id}.json")
