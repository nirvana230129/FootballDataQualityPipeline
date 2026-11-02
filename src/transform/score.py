from __future__ import annotations

from typing import Any


def _side_score(node: Any, *keys: str) -> int | None:
    if not isinstance(node, dict):
        return None
    for key in keys:
        if key in node and node[key] is not None:
            return int(node[key])
    return None


def extract_score_pair(score_node: Any) -> tuple[int | None, int | None]:
    """Read home/away goals from football-data score sub-object."""
    if not isinstance(score_node, dict):
        return None, None
    home = _side_score(score_node, "home", "homeTeam")
    away = _side_score(score_node, "away", "awayTeam")
    return home, away


def normalize_football_data_score(score: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize football-data.org v4 score node.

    Canonical score excludes penalty shootout goals:
      REGULAR / EXTRA_TIME -> fullTime
      PENALTY_SHOOTOUT     -> regularTime + extraTime
    """
    score = score or {}
    duration = (score.get("duration") or "REGULAR").upper()

    ft_home, ft_away = extract_score_pair(score.get("fullTime"))
    rt_home, rt_away = extract_score_pair(score.get("regularTime"))
    et_home, et_away = extract_score_pair(score.get("extraTime"))
    pen_home, pen_away = extract_score_pair(score.get("penalties"))

    if duration == "PENALTY_SHOOTOUT":
        if None in (rt_home, rt_away, et_home, et_away):
            raise ValueError("PENALTY_SHOOTOUT requires regularTime and extraTime")
        canonical_home = rt_home + et_home
        canonical_away = rt_away + et_away
    else:
        if ft_home is None or ft_away is None:
            raise ValueError(f"{duration} requires fullTime score")
        canonical_home = ft_home
        canonical_away = ft_away

    arithmetic_ok = check_score_arithmetic(
        duration=duration,
        full_time=(ft_home, ft_away),
        regular_time=(rt_home, rt_away),
        extra_time=(et_home, et_away),
        penalties=(pen_home, pen_away),
    )

    after_et_home = None
    after_et_away = None
    if None not in (rt_home, rt_away, et_home, et_away):
        after_et_home = rt_home + et_home
        after_et_away = rt_away + et_away

    return {
        "duration": duration,
        "full_time_home": ft_home,
        "full_time_away": ft_away,
        "regular_time_home": rt_home,
        "regular_time_away": rt_away,
        "extra_time_home": et_home,
        "extra_time_away": et_away,
        "penalties_home": pen_home,
        "penalties_away": pen_away,
        "canonical_home_score": canonical_home,
        "canonical_away_score": canonical_away,
        "score_after_extra_time_home": after_et_home,
        "score_after_extra_time_away": after_et_away,
        "score_arithmetic_ok": arithmetic_ok,
    }


def check_score_arithmetic(
    *,
    duration: str,
    full_time: tuple[int | None, int | None],
    regular_time: tuple[int | None, int | None],
    extra_time: tuple[int | None, int | None],
    penalties: tuple[int | None, int | None],
) -> bool:
    ft_home, ft_away = full_time
    rt_home, rt_away = regular_time
    et_home, et_away = extra_time
    pen_home, pen_away = penalties
    duration = duration.upper()

    if duration == "REGULAR":
        if None in (rt_home, rt_away):
            return True
        return (ft_home, ft_away) == (rt_home, rt_away)

    if duration == "EXTRA_TIME":
        if None in (rt_home, rt_away, et_home, et_away, ft_home, ft_away):
            return False
        return (ft_home, ft_away) == (rt_home + et_home, rt_away + et_away)

    if duration == "PENALTY_SHOOTOUT":
        if None in (
            rt_home,
            rt_away,
            et_home,
            et_away,
            pen_home,
            pen_away,
            ft_home,
            ft_away,
        ):
            return False
        return (ft_home, ft_away) == (
            rt_home + et_home + pen_home,
            rt_away + et_away + pen_away,
        )

    return False
