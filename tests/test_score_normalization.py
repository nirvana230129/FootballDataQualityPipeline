from __future__ import annotations

import json
from pathlib import Path

from src.transform.score import check_score_arithmetic, normalize_football_data_score

ROOT = Path(__file__).resolve().parents[1]


def test_euro1996_documentation_example():
    score = {
        "winner": "HOME_TEAM",
        "duration": "PENALTY_SHOOTOUT",
        "fullTime": {"homeTeam": 7, "awayTeam": 6},
        "regularTime": {"homeTeam": 1, "awayTeam": 1},
        "extraTime": {"homeTeam": 0, "awayTeam": 0},
        "penalties": {"homeTeam": 6, "awayTeam": 5},
    }
    result = normalize_football_data_score(score)
    assert result["canonical_home_score"] == 1
    assert result["canonical_away_score"] == 1
    assert result["penalties_home"] == 6
    assert result["penalties_away"] == 5
    assert result["score_arithmetic_ok"] is True


def test_wc2022_final_from_bootstrap_fixture():
    matches = json.loads(
        (ROOT / "data/football_data/wc2022_matches.json").read_text(encoding="utf-8")
    )["matches"]
    final = next(m for m in matches if m.get("stage") == "FINAL")
    result = normalize_football_data_score(final["score"])
    assert result["canonical_home_score"] == 3
    assert result["canonical_away_score"] == 3
    assert result["penalties_home"] == 4
    assert result["penalties_away"] == 2
    assert result["full_time_home"] == 7
    assert result["full_time_away"] == 5
    assert result["score_arithmetic_ok"] is True


def test_regular_time_uses_full_time():
    score = {
        "duration": "REGULAR",
        "fullTime": {"home": 2, "away": 1},
    }
    result = normalize_football_data_score(score)
    assert result["canonical_home_score"] == 2
    assert result["canonical_away_score"] == 1
    assert result["score_arithmetic_ok"] is True


def test_arithmetic_helper_penalty_formula():
    assert check_score_arithmetic(
        duration="PENALTY_SHOOTOUT",
        full_time=(7, 5),
        regular_time=(2, 2),
        extra_time=(1, 1),
        penalties=(4, 2),
    )
