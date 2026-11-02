from __future__ import annotations

import psycopg

from src.transform.score import normalize_football_data_score


def load_football_data_staging(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT payload, batch_id FROM raw.football_data_teams_current LIMIT 1")
        teams_row = cur.fetchone()
        cur.execute("SELECT payload, batch_id FROM raw.football_data_matches_current LIMIT 1")
        matches_row = cur.fetchone()
        cur.execute("SELECT payload, batch_id FROM raw.football_data_standings_current LIMIT 1")
        standings_row = cur.fetchone()

        cur.execute("TRUNCATE staging.football_data_teams")
        cur.execute("TRUNCATE staging.football_data_matches")
        cur.execute("TRUNCATE staging.football_data_standings")

        teams_loaded = 0
        matches_loaded = 0
        standings_loaded = 0

        if teams_row:
            payload, batch_id = teams_row
            for team in payload.get("teams", []):
                cur.execute(
                    """
                    INSERT INTO staging.football_data_teams (
                        team_id, team_name, tla, source_batch_id, loaded_at
                    ) VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (team_id) DO UPDATE
                    SET team_name = EXCLUDED.team_name,
                        tla = EXCLUDED.tla,
                        source_batch_id = EXCLUDED.source_batch_id,
                        loaded_at = EXCLUDED.loaded_at
                    """,
                    (
                        int(team["id"]),
                        team.get("name") or team.get("shortName"),
                        team.get("tla"),
                        batch_id,
                    ),
                )
                teams_loaded += 1

        if matches_row:
            payload, batch_id = matches_row
            season_start_year = None
            filters = payload.get("filters") or {}
            if filters.get("season"):
                season_start_year = int(str(filters["season"])[:4])

            for match in payload.get("matches", []):
                score = normalize_football_data_score(match.get("score"))
                competition = match.get("competition") or {}
                season = match.get("season") or {}
                home = match.get("homeTeam") or {}
                away = match.get("awayTeam") or {}
                year = season_start_year
                if year is None and season.get("startDate"):
                    year = int(str(season["startDate"])[:4])

                cur.execute(
                    """
                    INSERT INTO staging.football_data_matches (
                        match_id, utc_date, status, stage, matchday,
                        competition_code, season_start_year,
                        home_team_id, home_team_name, away_team_id, away_team_name,
                        duration, winner,
                        full_time_home, full_time_away,
                        regular_time_home, regular_time_away,
                        extra_time_home, extra_time_away,
                        penalties_home, penalties_away,
                        canonical_home_score, canonical_away_score,
                        score_arithmetic_ok, source_batch_id, loaded_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,
                        %s,%s,
                        %s,%s,%s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s,NOW()
                    )
                    ON CONFLICT (match_id) DO UPDATE SET
                        utc_date = EXCLUDED.utc_date,
                        status = EXCLUDED.status,
                        stage = EXCLUDED.stage,
                        matchday = EXCLUDED.matchday,
                        competition_code = EXCLUDED.competition_code,
                        season_start_year = EXCLUDED.season_start_year,
                        home_team_id = EXCLUDED.home_team_id,
                        home_team_name = EXCLUDED.home_team_name,
                        away_team_id = EXCLUDED.away_team_id,
                        away_team_name = EXCLUDED.away_team_name,
                        duration = EXCLUDED.duration,
                        winner = EXCLUDED.winner,
                        full_time_home = EXCLUDED.full_time_home,
                        full_time_away = EXCLUDED.full_time_away,
                        regular_time_home = EXCLUDED.regular_time_home,
                        regular_time_away = EXCLUDED.regular_time_away,
                        extra_time_home = EXCLUDED.extra_time_home,
                        extra_time_away = EXCLUDED.extra_time_away,
                        penalties_home = EXCLUDED.penalties_home,
                        penalties_away = EXCLUDED.penalties_away,
                        canonical_home_score = EXCLUDED.canonical_home_score,
                        canonical_away_score = EXCLUDED.canonical_away_score,
                        score_arithmetic_ok = EXCLUDED.score_arithmetic_ok,
                        source_batch_id = EXCLUDED.source_batch_id,
                        loaded_at = EXCLUDED.loaded_at
                    """,
                    (
                        int(match["id"]),
                        match.get("utcDate"),
                        match.get("status"),
                        match.get("stage"),
                        match.get("matchday"),
                        competition.get("code") or "WC",
                        year,
                        home.get("id"),
                        home.get("name") or home.get("shortName"),
                        away.get("id"),
                        away.get("name") or away.get("shortName"),
                        score["duration"],
                        (match.get("score") or {}).get("winner"),
                        score["full_time_home"],
                        score["full_time_away"],
                        score["regular_time_home"],
                        score["regular_time_away"],
                        score["extra_time_home"],
                        score["extra_time_away"],
                        score["penalties_home"],
                        score["penalties_away"],
                        score["canonical_home_score"],
                        score["canonical_away_score"],
                        score["score_arithmetic_ok"],
                        batch_id,
                    ),
                )
                matches_loaded += 1

                # Ensure teams exist even if teams endpoint was partial.
                for team_id, team_name in (
                    (home.get("id"), home.get("name") or home.get("shortName")),
                    (away.get("id"), away.get("name") or away.get("shortName")),
                ):
                    if team_id is None:
                        continue
                    cur.execute(
                        """
                        INSERT INTO staging.football_data_teams (
                            team_id, team_name, source_batch_id, loaded_at
                        ) VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (team_id) DO UPDATE
                        SET team_name = COALESCE(EXCLUDED.team_name, staging.football_data_teams.team_name),
                            source_batch_id = EXCLUDED.source_batch_id,
                            loaded_at = EXCLUDED.loaded_at
                        """,
                        (int(team_id), team_name, batch_id),
                    )

        if standings_row:
            payload, batch_id = standings_row
            competition = payload.get("competition") or {}
            season = payload.get("season") or {}
            year = int(str(season.get("startDate", "2022"))[:4])
            code = competition.get("code") or "WC"
            for block in payload.get("standings", []):
                stage = block.get("stage") or "UNKNOWN"
                group_name = block.get("group") or block.get("type") or "ALL"
                for row in block.get("table", []):
                    team = row.get("team") or {}
                    cur.execute(
                        """
                        INSERT INTO staging.football_data_standings (
                            competition_code, season_start_year, stage, group_name,
                            team_id, team_name, position, played_games,
                            won, draw, lost, points, goals_for, goals_against,
                            source_batch_id, loaded_at
                        ) VALUES (
                            %s,%s,%s,%s,
                            %s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,
                            %s,NOW()
                        )
                        ON CONFLICT (
                            competition_code, season_start_year, stage, group_name, team_id
                        ) DO UPDATE SET
                            team_name = EXCLUDED.team_name,
                            position = EXCLUDED.position,
                            played_games = EXCLUDED.played_games,
                            won = EXCLUDED.won,
                            draw = EXCLUDED.draw,
                            lost = EXCLUDED.lost,
                            points = EXCLUDED.points,
                            goals_for = EXCLUDED.goals_for,
                            goals_against = EXCLUDED.goals_against,
                            source_batch_id = EXCLUDED.source_batch_id,
                            loaded_at = EXCLUDED.loaded_at
                        """,
                        (
                            code,
                            year,
                            stage,
                            group_name,
                            int(team["id"]),
                            team.get("name"),
                            row.get("position"),
                            row.get("playedGames"),
                            row.get("won"),
                            row.get("draw"),
                            row.get("lost"),
                            row.get("points"),
                            row.get("goalsFor"),
                            row.get("goalsAgainst"),
                            batch_id,
                        ),
                    )
                    standings_loaded += 1

    return {
        "teams": teams_loaded,
        "matches": matches_loaded,
        "standings": standings_loaded,
    }
