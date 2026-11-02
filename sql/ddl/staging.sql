CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.statsbomb_matches (
    match_id            BIGINT PRIMARY KEY,
    match_date          DATE,
    kick_off            TEXT,
    competition_id      BIGINT,
    competition_name    TEXT,
    season_id           BIGINT,
    season_name         TEXT,
    home_team_id        BIGINT,
    home_team_name      TEXT,
    away_team_id        BIGINT,
    away_team_name      TEXT,
    home_score          INTEGER,
    away_score          INTEGER,
    source_batch_id     UUID,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.statsbomb_teams (
    team_id             BIGINT PRIMARY KEY,
    team_name           TEXT NOT NULL,
    source_batch_id     UUID,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.statsbomb_players (
    player_id           BIGINT PRIMARY KEY,
    player_name         TEXT NOT NULL,
    source_batch_id     UUID,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.statsbomb_lineups (
    match_id            BIGINT NOT NULL,
    team_id             BIGINT NOT NULL,
    player_id           BIGINT NOT NULL,
    player_name         TEXT,
    jersey_number       INTEGER,
    source_batch_id     UUID,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (match_id, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS staging.statsbomb_events (
    event_id            TEXT NOT NULL,
    match_id            BIGINT NOT NULL,
    event_index         INTEGER,
    period              INTEGER,
    minute              INTEGER,
    second              INTEGER,
    team_id             BIGINT,
    player_id           BIGINT,
    event_type          TEXT,
    x                   DOUBLE PRECISION,
    y                   DOUBLE PRECISION,
    end_x               DOUBLE PRECISION,
    end_y               DOUBLE PRECISION,
    end_z               DOUBLE PRECISION,
    pass_recipient_id   BIGINT,
    pass_outcome        TEXT,
    pass_length         DOUBLE PRECISION,
    is_cross            BOOLEAN,
    shot_xg             DOUBLE PRECISION,
    shot_outcome        TEXT,
    carry_end_x         DOUBLE PRECISION,
    carry_end_y         DOUBLE PRECISION,
    possession          INTEGER,
    possession_team_id  BIGINT,
    source_batch_id     UUID,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (match_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_stg_sb_events_match
    ON staging.statsbomb_events (match_id);
CREATE INDEX IF NOT EXISTS idx_stg_sb_events_type
    ON staging.statsbomb_events (match_id, event_type);
