from __future__ import annotations

from typing import Any

import psycopg


def resolve_matches(conn: psycopg.Connection) -> dict[str, int]:
    """
    Match football-data matches onto canonical StatsBomb matches.

    Candidate: competition + season + canonical home/away.
    Kickoff confirms; hour-scale drift is allowed as WARNING material for DQ.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                sm.match_id,
                msm.canonical_match_id,
                sm.home_team_id,
                sm.away_team_id,
                home_map.canonical_team_id AS canonical_home_team_id,
                away_map.canonical_team_id AS canonical_away_team_id,
                cm.kickoff_utc,
                sm.home_score,
                sm.away_score
            FROM staging.statsbomb_matches sm
            JOIN core.match_source_mapping msm
              ON msm.provider = 'statsbomb'
             AND msm.source_match_id = sm.match_id::TEXT
            JOIN core.matches cm
              ON cm.canonical_match_id = msm.canonical_match_id
            JOIN core.team_source_mapping home_map
              ON home_map.provider = 'statsbomb'
             AND home_map.source_team_id = sm.home_team_id::TEXT
            JOIN core.team_source_mapping away_map
              ON away_map.provider = 'statsbomb'
             AND away_map.source_team_id = sm.away_team_id::TEXT
            """
        )
        sb_rows = cur.fetchall()

        cur.execute(
            """
            SELECT
                fm.match_id,
                fm.utc_date,
                fm.home_team_id,
                fm.away_team_id,
                home_map.canonical_team_id,
                away_map.canonical_team_id,
                fm.canonical_home_score,
                fm.canonical_away_score,
                fm.regular_time_home,
                fm.regular_time_away,
                fm.extra_time_home,
                fm.extra_time_away,
                fm.penalties_home,
                fm.penalties_away,
                fm.full_time_home,
                fm.full_time_away,
                fm.duration,
                fm.score_arithmetic_ok
            FROM staging.football_data_matches fm
            LEFT JOIN core.team_source_mapping home_map
              ON home_map.provider = 'football_data'
             AND home_map.source_team_id = fm.home_team_id::TEXT
            LEFT JOIN core.team_source_mapping away_map
              ON away_map.provider = 'football_data'
             AND away_map.source_team_id = fm.away_team_id::TEXT
            """
        )
        fd_rows = cur.fetchall()

        sb_by_teams: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in sb_rows:
            item = {
                "source_match_id": row[0],
                "canonical_match_id": row[1],
                "canonical_home": row[4],
                "canonical_away": row[5],
                "kickoff_utc": row[6],
                "home_score": row[7],
                "away_score": row[8],
            }
            key = (row[4], row[5])
            sb_by_teams.setdefault(key, []).append(item)

        matched = unmatched = ambiguous = 0

        for row in fd_rows:
            (
                fd_match_id,
                utc_date,
                _home_id,
                _away_id,
                canonical_home,
                canonical_away,
                _can_home,
                _can_away,
                rt_home,
                rt_away,
                et_home,
                et_away,
                pen_home,
                pen_away,
                _ft_home,
                _ft_away,
                _duration,
                _arith_ok,
            ) = row

            if canonical_home is None or canonical_away is None:
                continue

            candidates = sb_by_teams.get((canonical_home, canonical_away), [])
            if not candidates:
                continue

            chosen = None
            status = "matched"
            if len(candidates) == 1:
                chosen = candidates[0]
            else:
                if utc_date is None:
                    continue
                ranked = sorted(
                    candidates,
                    key=lambda c: abs((c["kickoff_utc"] - utc_date).total_seconds())
                    if c["kickoff_utc"] is not None
                    else 10**12,
                )
                best = ranked[0]
                second = ranked[1]
                best_delta = abs((best["kickoff_utc"] - utc_date).total_seconds())
                second_delta = abs((second["kickoff_utc"] - utc_date).total_seconds())
                if best_delta <= 36 * 3600 and best_delta < second_delta:
                    chosen = best
                    status = "matched"
                else:
                    # Keep an ambiguous mapping against the nearest candidate for audit.
                    cur.execute(
                        """
                        INSERT INTO core.match_source_mapping (
                            canonical_match_id, provider, source_match_id, mapping_status
                        ) VALUES (%s, 'football_data', %s, 'ambiguous')
                        ON CONFLICT (provider, source_match_id) DO UPDATE
                        SET canonical_match_id = EXCLUDED.canonical_match_id,
                            mapping_status = EXCLUDED.mapping_status
                        """,
                        (best["canonical_match_id"], str(fd_match_id)),
                    )
                    continue

            if chosen is None:
                continue

            cur.execute(
                """
                INSERT INTO core.match_source_mapping (
                    canonical_match_id, provider, source_match_id, mapping_status
                ) VALUES (%s, 'football_data', %s, %s)
                ON CONFLICT (provider, source_match_id) DO UPDATE
                SET canonical_match_id = EXCLUDED.canonical_match_id,
                    mapping_status = EXCLUDED.mapping_status
                """,
                (chosen["canonical_match_id"], str(fd_match_id), status),
            )

            # Enrich core match with FD score breakdown; keep StatsBomb canonical score.
            after_home = None
            after_away = None
            if None not in (rt_home, et_home):
                after_home = rt_home + et_home
            if None not in (rt_away, et_away):
                after_away = rt_away + et_away

            cur.execute(
                """
                UPDATE core.matches
                SET score_regular_time_home = %s,
                    score_regular_time_away = %s,
                    score_extra_time_only_home = %s,
                    score_extra_time_only_away = %s,
                    score_after_extra_time_home = %s,
                    score_after_extra_time_away = %s,
                    score_penalties_home = %s,
                    score_penalties_away = %s
                WHERE canonical_match_id = %s
                """,
                (
                    rt_home,
                    rt_away,
                    et_home,
                    et_away,
                    after_home,
                    after_away,
                    pen_home,
                    pen_away,
                    chosen["canonical_match_id"],
                ),
            )
            matched += 1

        # Count FD matches with no mapping row as unmatched for reporting.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM staging.football_data_matches fm
            WHERE NOT EXISTS (
                SELECT 1
                FROM core.match_source_mapping msm
                WHERE msm.provider = 'football_data'
                  AND msm.source_match_id = fm.match_id::TEXT
            )
            """
        )
        unmatched = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE mapping_status = 'matched'),
                COUNT(*) FILTER (WHERE mapping_status = 'ambiguous')
            FROM core.match_source_mapping
            WHERE provider = 'football_data'
            """
        )
        matched, ambiguous = cur.fetchone()

    return {
        "matched": int(matched or 0),
        "unmatched": int(unmatched or 0),
        "ambiguous": int(ambiguous or 0),
    }
