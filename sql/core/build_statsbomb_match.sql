-- Expects app.match_id session setting (StatsBomb source match id).

INSERT INTO core.competitions (competition_id, competition_name)
SELECT competition_id, competition_name
FROM staging.statsbomb_matches
WHERE match_id = current_setting('app.match_id')::BIGINT
ON CONFLICT (competition_id) DO UPDATE
SET competition_name = EXCLUDED.competition_name;

INSERT INTO core.seasons (season_id, season_name)
SELECT season_id, season_name
FROM staging.statsbomb_matches
WHERE match_id = current_setting('app.match_id')::BIGINT
ON CONFLICT (season_id) DO UPDATE
SET season_name = EXCLUDED.season_name;

CREATE TEMP TABLE tmp_new_teams ON COMMIT DROP AS
SELECT
    t.team_id,
    t.team_name,
    nextval('core.canonical_team_id_seq') AS canonical_team_id
FROM staging.statsbomb_teams t
WHERE NOT EXISTS (
    SELECT 1
    FROM core.team_source_mapping m
    WHERE m.provider = 'statsbomb'
      AND m.source_team_id = t.team_id::TEXT
);

INSERT INTO core.teams (canonical_team_id, team_name)
SELECT canonical_team_id, team_name
FROM tmp_new_teams;

INSERT INTO core.team_source_mapping (
    canonical_team_id,
    provider,
    source_team_id,
    source_name,
    mapping_method,
    mapping_status
)
SELECT
    canonical_team_id,
    'statsbomb',
    team_id::TEXT,
    team_name,
    'manual_seed',
    'confirmed'
FROM tmp_new_teams;

CREATE TEMP TABLE tmp_new_players ON COMMIT DROP AS
SELECT
    p.player_id,
    p.player_name,
    nextval('core.canonical_player_id_seq') AS canonical_player_id
FROM staging.statsbomb_players p
WHERE NOT EXISTS (
    SELECT 1
    FROM core.player_source_mapping m
    WHERE m.provider = 'statsbomb'
      AND m.source_player_id = p.player_id::TEXT
);

INSERT INTO core.players (canonical_player_id, player_name)
SELECT canonical_player_id, player_name
FROM tmp_new_players;

INSERT INTO core.player_source_mapping (
    canonical_player_id,
    provider,
    source_player_id,
    source_name
)
SELECT
    canonical_player_id,
    'statsbomb',
    player_id::TEXT,
    player_name
FROM tmp_new_players;

DELETE FROM core.events e
USING core.match_source_mapping msm
WHERE e.canonical_match_id = msm.canonical_match_id
  AND msm.provider = 'statsbomb'
  AND msm.source_match_id = current_setting('app.match_id');

DELETE FROM core.lineups l
USING core.match_source_mapping msm
WHERE l.canonical_match_id = msm.canonical_match_id
  AND msm.provider = 'statsbomb'
  AND msm.source_match_id = current_setting('app.match_id');

CREATE TEMP TABLE tmp_match_target ON COMMIT DROP AS
SELECT msm.canonical_match_id
FROM core.match_source_mapping msm
WHERE msm.provider = 'statsbomb'
  AND msm.source_match_id = current_setting('app.match_id');

INSERT INTO core.matches (
    competition_id,
    season_id,
    canonical_home_team_id,
    canonical_away_team_id,
    kickoff_utc,
    source_match_date,
    source_kickoff,
    source_timezone,
    home_score,
    away_score
)
SELECT
    m.competition_id,
    m.season_id,
    home_map.canonical_team_id,
    away_map.canonical_team_id,
    ((m.match_date::TEXT || ' ' || LEFT(m.kick_off, 8))::TIMESTAMP
        AT TIME ZONE 'Asia/Qatar'),
    m.match_date,
    m.kick_off,
    'Asia/Qatar',
    m.home_score,
    m.away_score
FROM staging.statsbomb_matches m
JOIN core.team_source_mapping home_map
  ON home_map.provider = 'statsbomb'
 AND home_map.source_team_id = m.home_team_id::TEXT
JOIN core.team_source_mapping away_map
  ON away_map.provider = 'statsbomb'
 AND away_map.source_team_id = m.away_team_id::TEXT
WHERE m.match_id = current_setting('app.match_id')::BIGINT
  AND NOT EXISTS (SELECT 1 FROM tmp_match_target);

INSERT INTO core.match_source_mapping (
    canonical_match_id,
    provider,
    source_match_id,
    mapping_status
)
SELECT
    cm.canonical_match_id,
    'statsbomb',
    current_setting('app.match_id'),
    'matched'
FROM core.matches cm
JOIN staging.statsbomb_matches sm
  ON sm.match_id = current_setting('app.match_id')::BIGINT
JOIN core.team_source_mapping home_map
  ON home_map.provider = 'statsbomb'
 AND home_map.source_team_id = sm.home_team_id::TEXT
 AND home_map.canonical_team_id = cm.canonical_home_team_id
JOIN core.team_source_mapping away_map
  ON away_map.provider = 'statsbomb'
 AND away_map.source_team_id = sm.away_team_id::TEXT
 AND away_map.canonical_team_id = cm.canonical_away_team_id
WHERE NOT EXISTS (
    SELECT 1
    FROM core.match_source_mapping msm
    WHERE msm.provider = 'statsbomb'
      AND msm.source_match_id = current_setting('app.match_id')
)
ORDER BY cm.canonical_match_id DESC
LIMIT 1;

UPDATE core.matches cm
SET
    competition_id = m.competition_id,
    season_id = m.season_id,
    canonical_home_team_id = home_map.canonical_team_id,
    canonical_away_team_id = away_map.canonical_team_id,
    kickoff_utc = ((m.match_date::TEXT || ' ' || LEFT(m.kick_off, 8))::TIMESTAMP
        AT TIME ZONE 'Asia/Qatar'),
    source_match_date = m.match_date,
    source_kickoff = m.kick_off,
    source_timezone = 'Asia/Qatar',
    home_score = m.home_score,
    away_score = m.away_score
FROM staging.statsbomb_matches m
JOIN core.team_source_mapping home_map
  ON home_map.provider = 'statsbomb'
 AND home_map.source_team_id = m.home_team_id::TEXT
JOIN core.team_source_mapping away_map
  ON away_map.provider = 'statsbomb'
 AND away_map.source_team_id = m.away_team_id::TEXT
JOIN core.match_source_mapping msm
  ON msm.provider = 'statsbomb'
 AND msm.source_match_id = current_setting('app.match_id')
WHERE m.match_id = current_setting('app.match_id')::BIGINT
  AND cm.canonical_match_id = msm.canonical_match_id;

INSERT INTO core.lineups (
    canonical_match_id,
    canonical_team_id,
    canonical_player_id,
    jersey_number
)
SELECT
    msm.canonical_match_id,
    tm.canonical_team_id,
    pm.canonical_player_id,
    l.jersey_number
FROM staging.statsbomb_lineups l
JOIN core.match_source_mapping msm
  ON msm.provider = 'statsbomb'
 AND msm.source_match_id = l.match_id::TEXT
JOIN core.team_source_mapping tm
  ON tm.provider = 'statsbomb'
 AND tm.source_team_id = l.team_id::TEXT
JOIN core.player_source_mapping pm
  ON pm.provider = 'statsbomb'
 AND pm.source_player_id = l.player_id::TEXT
WHERE l.match_id = current_setting('app.match_id')::BIGINT;

INSERT INTO core.events (
    event_id,
    canonical_match_id,
    source_match_id,
    event_index,
    period,
    minute,
    second,
    canonical_team_id,
    canonical_player_id,
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
    canonical_possession_team_id
)
SELECT
    e.event_id,
    msm.canonical_match_id,
    e.match_id,
    e.event_index,
    e.period,
    e.minute,
    e.second,
    tm.canonical_team_id,
    pm.canonical_player_id,
    e.event_type,
    e.x,
    e.y,
    e.end_x,
    e.end_y,
    e.end_z,
    e.pass_recipient_id,
    e.pass_outcome,
    e.pass_length,
    e.is_cross,
    e.shot_xg,
    e.shot_outcome,
    e.carry_end_x,
    e.carry_end_y,
    e.possession,
    e.possession_team_id,
    ptm.canonical_team_id
FROM staging.statsbomb_events e
JOIN core.match_source_mapping msm
  ON msm.provider = 'statsbomb'
 AND msm.source_match_id = e.match_id::TEXT
LEFT JOIN core.team_source_mapping tm
  ON tm.provider = 'statsbomb'
 AND tm.source_team_id = e.team_id::TEXT
LEFT JOIN core.team_source_mapping ptm
  ON ptm.provider = 'statsbomb'
 AND ptm.source_team_id = e.possession_team_id::TEXT
LEFT JOIN core.player_source_mapping pm
  ON pm.provider = 'statsbomb'
 AND pm.source_player_id = e.player_id::TEXT
WHERE e.match_id = current_setting('app.match_id')::BIGINT;

INSERT INTO monitoring.match_publication_status (
    canonical_match_id,
    dq_status,
    publication_status,
    is_quarantined,
    critical_check_count,
    warning_check_count,
    last_checked_at
)
SELECT
    msm.canonical_match_id,
    'PENDING',
    'PUBLISHABLE',
    FALSE,
    0,
    0,
    NULL
FROM core.match_source_mapping msm
WHERE msm.provider = 'statsbomb'
  AND msm.source_match_id = current_setting('app.match_id')
ON CONFLICT (canonical_match_id) DO NOTHING;
