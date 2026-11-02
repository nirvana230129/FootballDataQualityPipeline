from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from src.db import ROOT

load_dotenv(ROOT / ".env")

BASE_URL = "https://api.football-data.org/v4"
WC_CODE = "WC"
WC_SEASON = 2022
REQUEST_PAUSE_SECONDS = 6.5
MAX_RETRIES = 3
BOOTSTRAP_DIR = ROOT / "data" / "football_data"


def _api_key() -> str:
    key = os.getenv("FOOTBALL_DATA_ORG_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FOOTBALL_DATA_ORG_API_KEY is not set in .env")
    return key


def _load_bootstrap(name: str) -> Any:
    path = BOOTSTRAP_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Bootstrap fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    headers = {"X-Auth-Token": _api_key()}
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)
            if response.status_code == 403:
                raise PermissionError(f"403 restricted for {url}")
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"retryable status {response.status_code} for {url}",
                    response=response,
                )
            response.raise_for_status()
            time.sleep(REQUEST_PAUSE_SECONDS)
            return response.json()
        except PermissionError:
            raise
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status in {429, 500, 502, 503, 504} or isinstance(
                exc, (requests.ConnectionError, requests.Timeout)
            )
            if not retryable or attempt == MAX_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"failed to fetch {url}") from last_error


def fetch_competition(code: str = WC_CODE) -> dict[str, Any]:
    try:
        return _get_json(f"/competitions/{code}")
    except PermissionError:
        return _load_bootstrap("wc2022_competition.json")


def fetch_matches(code: str = WC_CODE, season: int = WC_SEASON) -> dict[str, Any]:
    """
    Free-tier football-data.org currently restricts historical WC 2022 matches.
    On 403, load the local v4-shaped bootstrap fixture under data/football_data/.
    """
    try:
        return _get_json(f"/competitions/{code}/matches", params={"season": season})
    except PermissionError:
        if code == WC_CODE and int(season) == WC_SEASON:
            payload = _load_bootstrap("wc2022_matches.json")
            payload.setdefault("filters", {})["source"] = "bootstrap_fixture"
            return payload
        raise


def fetch_teams(code: str = WC_CODE, season: int = WC_SEASON) -> dict[str, Any]:
    try:
        return _get_json(f"/competitions/{code}/teams", params={"season": season})
    except PermissionError:
        if code == WC_CODE and int(season) == WC_SEASON:
            return _load_bootstrap("wc2022_teams.json")
        # Derive from matches bootstrap if teams endpoint restricted.
        matches = fetch_matches(code, season)
        teams: dict[int, dict[str, Any]] = {}
        for match in matches.get("matches", []):
            for side in ("homeTeam", "awayTeam"):
                team = match.get(side) or {}
                if team.get("id") is not None:
                    teams[int(team["id"])] = {
                        "id": int(team["id"]),
                        "name": team.get("name") or team.get("shortName"),
                        "shortName": team.get("shortName"),
                        "tla": team.get("tla"),
                    }
        return {
            "competition": matches.get("competition") or {"code": code},
            "season": {"startDate": f"{season}-01-01"},
            "teams": list(teams.values()),
            "filters": {"source": "derived_from_matches"},
        }


def fetch_standings(code: str = WC_CODE, season: int = WC_SEASON) -> dict[str, Any] | None:
    try:
        return _get_json(f"/competitions/{code}/standings", params={"season": season})
    except PermissionError:
        return None
