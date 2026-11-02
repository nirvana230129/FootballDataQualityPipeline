from __future__ import annotations

from typing import Any

import requests

STATSBOMB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
WC2022_COMPETITION_ID = 43
WC2022_SEASON_ID = 106


def _get_json(url: str) -> Any:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_competition_matches(
    competition_id: int = WC2022_COMPETITION_ID,
    season_id: int = WC2022_SEASON_ID,
) -> list[dict[str, Any]]:
    url = f"{STATSBOMB_BASE}/matches/{competition_id}/{season_id}.json"
    return _get_json(url)


def fetch_match(match_id: int) -> dict[str, Any]:
    matches = fetch_competition_matches()
    for match in matches:
        if match["match_id"] == match_id:
            return match
    raise ValueError(f"StatsBomb match {match_id} not found in WC 2022 open data")


def fetch_lineups(match_id: int) -> list[dict[str, Any]]:
    return _get_json(f"{STATSBOMB_BASE}/lineups/{match_id}.json")


def fetch_events(match_id: int) -> list[dict[str, Any]]:
    return _get_json(f"{STATSBOMB_BASE}/events/{match_id}.json")
