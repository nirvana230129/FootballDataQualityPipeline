-- Expects app.match_id session setting (StatsBomb source match id).

DELETE FROM staging.statsbomb_events
WHERE match_id = current_setting('app.match_id')::BIGINT;

DELETE FROM staging.statsbomb_lineups
WHERE match_id = current_setting('app.match_id')::BIGINT;

DELETE FROM staging.statsbomb_matches
WHERE match_id = current_setting('app.match_id')::BIGINT;

INSERT INTO staging.statsbomb_matches (
    match_id,
    match_date,
    kick_off,
    competition_id,
    competition_name,
    season_id,
    season_name,
    home_team_id,
    home_team_name,
    away_team_id,
    away_team_name,
    home_score,
    away_score,
    source_batch_id,
    loaded_at
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
WHERE m.source_id = current_setting('app.match_id');

INSERT INTO staging.statsbomb_teams (team_id, team_name, source_batch_id, loaded_at)
SELECT DISTINCT team_id, team_name, source_batch_id, NOW()
FROM (
    SELECT home_team_id AS team_id, home_team_name AS team_name, source_batch_id
    FROM staging.statsbomb_matches
    WHERE match_id = current_setting('app.match_id')::BIGINT
    UNION ALL
    SELECT away_team_id, away_team_name, source_batch_id
    FROM staging.statsbomb_matches
    WHERE match_id = current_setting('app.match_id')::BIGINT
) t
ON CONFLICT (team_id) DO UPDATE
SET team_name = EXCLUDED.team_name,
    source_batch_id = EXCLUDED.source_batch_id,
    loaded_at = EXCLUDED.loaded_at;

INSERT INTO staging.statsbomb_lineups (
    match_id,
    team_id,
    player_id,
    player_name,
    jersey_number,
    source_batch_id,
    loaded_at
)
SELECT
    current_setting('app.match_id')::BIGINT,
    (team_elem ->> 'team_id')::BIGINT,
    (player_elem ->> 'player_id')::BIGINT,
    player_elem ->> 'player_name',
    NULLIF(player_elem ->> 'jersey_number', '')::INTEGER,
    l.batch_id,
    NOW()
FROM raw.statsbomb_lineups_current l
CROSS JOIN LATERAL jsonb_array_elements(l.payload) AS team_elem
CROSS JOIN LATERAL jsonb_array_elements(team_elem -> 'lineup') AS player_elem
WHERE l.source_id = current_setting('app.match_id');

INSERT INTO staging.statsbomb_players (player_id, player_name, source_batch_id, loaded_at)
SELECT DISTINCT player_id, player_name, source_batch_id, NOW()
FROM staging.statsbomb_lineups
WHERE match_id = current_setting('app.match_id')::BIGINT
ON CONFLICT (player_id) DO UPDATE
SET player_name = EXCLUDED.player_name,
    source_batch_id = EXCLUDED.source_batch_id,
    loaded_at = EXCLUDED.loaded_at;

INSERT INTO staging.statsbomb_events (
    event_id,
    match_id,
    event_index,
    period,
    minute,
    second,
    team_id,
    player_id,
    event_type,
    x,
    y,
    end_x,
    end_y,
    end_z,
    pass_recipient_id,
    pass_outcome,
    pass_length,
    is_cross,
    shot_xg,
    shot_outcome,
    carry_end_x,
    carry_end_y,
    possession,
    possession_team_id,
    source_batch_id,
    loaded_at
)
-- Deterministic dedup: raw keeps duplicate event ids; staging keeps one row
-- per event_id (lowest event_index). DQ still sees raw duplicates.
SELECT DISTINCT ON (e ->> 'id')
    e ->> 'id',
    current_setting('app.match_id')::BIGINT,
    (e ->> 'index')::INTEGER,
    (e ->> 'period')::INTEGER,
    (e ->> 'minute')::INTEGER,
    (e ->> 'second')::INTEGER,
    NULLIF(e -> 'team' ->> 'id', '')::BIGINT,
    NULLIF(e -> 'player' ->> 'id', '')::BIGINT,
    e -> 'type' ->> 'name',
    NULLIF(e -> 'location' ->> 0, '')::DOUBLE PRECISION,
    NULLIF(e -> 'location' ->> 1, '')::DOUBLE PRECISION,
    CASE
        WHEN e -> 'type' ->> 'name' = 'Pass'
            THEN NULLIF(e -> 'pass' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
        WHEN e -> 'type' ->> 'name' = 'Shot'
            THEN NULLIF(e -> 'shot' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
        WHEN e -> 'type' ->> 'name' = 'Carry'
            THEN NULLIF(e -> 'carry' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
        ELSE NULL
    END,
    CASE
        WHEN e -> 'type' ->> 'name' = 'Pass'
            THEN NULLIF(e -> 'pass' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
        WHEN e -> 'type' ->> 'name' = 'Shot'
            THEN NULLIF(e -> 'shot' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
        WHEN e -> 'type' ->> 'name' = 'Carry'
            THEN NULLIF(e -> 'carry' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
        ELSE NULL
    END,
    CASE
        WHEN e -> 'type' ->> 'name' = 'Shot'
             AND jsonb_array_length(COALESCE(e -> 'shot' -> 'end_location', '[]'::jsonb)) >= 3
            THEN NULLIF(e -> 'shot' -> 'end_location' ->> 2, '')::DOUBLE PRECISION
        ELSE NULL
    END,
    NULLIF(e -> 'pass' -> 'recipient' ->> 'id', '')::BIGINT,
    e -> 'pass' -> 'outcome' ->> 'name',
    NULLIF(e -> 'pass' ->> 'length', '')::DOUBLE PRECISION,
    CASE
        WHEN e -> 'type' ->> 'name' = 'Pass'
            THEN COALESCE((e -> 'pass' ->> 'cross')::BOOLEAN, FALSE)
        ELSE NULL
    END,
    NULLIF(e -> 'shot' ->> 'statsbomb_xg', '')::DOUBLE PRECISION,
    e -> 'shot' -> 'outcome' ->> 'name',
    CASE
        WHEN e -> 'type' ->> 'name' = 'Carry'
            THEN NULLIF(e -> 'carry' -> 'end_location' ->> 0, '')::DOUBLE PRECISION
        ELSE NULL
    END,
    CASE
        WHEN e -> 'type' ->> 'name' = 'Carry'
            THEN NULLIF(e -> 'carry' -> 'end_location' ->> 1, '')::DOUBLE PRECISION
        ELSE NULL
    END,
    NULLIF(e ->> 'possession', '')::INTEGER,
    NULLIF(e -> 'possession_team' ->> 'id', '')::BIGINT,
    r.batch_id,
    NOW()
FROM raw.statsbomb_events_current r
CROSS JOIN LATERAL jsonb_array_elements(r.payload) AS e
WHERE r.source_id = current_setting('app.match_id')
ORDER BY e ->> 'id', (e ->> 'index')::INTEGER NULLS LAST;
