CREATE SCHEMA IF NOT EXISTS core;

CREATE SEQUENCE IF NOT EXISTS core.canonical_team_id_seq;
CREATE SEQUENCE IF NOT EXISTS core.canonical_player_id_seq;
CREATE SEQUENCE IF NOT EXISTS core.canonical_match_id_seq;

CREATE TABLE IF NOT EXISTS core.competitions (
    competition_id      BIGINT PRIMARY KEY,
    competition_name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core.seasons (
    season_id           BIGINT PRIMARY KEY,
    season_name         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core.teams (
    canonical_team_id   BIGINT PRIMARY KEY DEFAULT nextval('core.canonical_team_id_seq'),
    team_name           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core.players (
    canonical_player_id BIGINT PRIMARY KEY DEFAULT nextval('core.canonical_player_id_seq'),
    player_name         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core.team_source_mapping (
    canonical_team_id   BIGINT NOT NULL REFERENCES core.teams (canonical_team_id),
    provider            TEXT NOT NULL,
    source_team_id      TEXT NOT NULL,
    source_name         TEXT,
    mapping_method      TEXT NOT NULL DEFAULT 'manual_seed',
    mapping_status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, source_team_id)
);

CREATE TABLE IF NOT EXISTS core.matches (
    canonical_match_id          BIGINT PRIMARY KEY DEFAULT nextval('core.canonical_match_id_seq'),
    competition_id              BIGINT REFERENCES core.competitions (competition_id),
    season_id                   BIGINT REFERENCES core.seasons (season_id),
    canonical_home_team_id      BIGINT REFERENCES core.teams (canonical_team_id),
    canonical_away_team_id      BIGINT REFERENCES core.teams (canonical_team_id),
    kickoff_utc                 TIMESTAMPTZ,
    source_match_date           DATE,
    source_kickoff              TEXT,
    source_timezone             TEXT,
    home_score                  INTEGER,
    away_score                  INTEGER,
    score_regular_time_home     INTEGER,
    score_regular_time_away     INTEGER,
    score_extra_time_only_home  INTEGER,
    score_extra_time_only_away  INTEGER,
    score_after_extra_time_home INTEGER,
    score_after_extra_time_away INTEGER,
    score_penalties_home        INTEGER,
    score_penalties_away        INTEGER
);

ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_regular_time_home INTEGER;
ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_regular_time_away INTEGER;
ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_extra_time_only_home INTEGER;
ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_extra_time_only_away INTEGER;
ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_after_extra_time_home INTEGER;
ALTER TABLE core.matches
    ADD COLUMN IF NOT EXISTS score_after_extra_time_away INTEGER;

CREATE TABLE IF NOT EXISTS core.team_keys (
    canonical_team_key  TEXT PRIMARY KEY,
    canonical_team_id   BIGINT NOT NULL UNIQUE REFERENCES core.teams (canonical_team_id)
);

CREATE TABLE IF NOT EXISTS core.match_source_mapping (
    canonical_match_id  BIGINT NOT NULL REFERENCES core.matches (canonical_match_id),
    provider            TEXT NOT NULL,
    source_match_id     TEXT NOT NULL,
    mapping_status      TEXT NOT NULL DEFAULT 'matched',
    PRIMARY KEY (provider, source_match_id)
);

CREATE TABLE IF NOT EXISTS core.player_source_mapping (
    canonical_player_id BIGINT NOT NULL REFERENCES core.players (canonical_player_id),
    provider            TEXT NOT NULL,
    source_player_id    TEXT NOT NULL,
    source_name         TEXT,
    PRIMARY KEY (provider, source_player_id)
);

CREATE TABLE IF NOT EXISTS core.lineups (
    canonical_match_id  BIGINT NOT NULL REFERENCES core.matches (canonical_match_id),
    canonical_team_id   BIGINT NOT NULL REFERENCES core.teams (canonical_team_id),
    canonical_player_id BIGINT NOT NULL REFERENCES core.players (canonical_player_id),
    jersey_number       INTEGER,
    PRIMARY KEY (canonical_match_id, canonical_team_id, canonical_player_id)
);

CREATE TABLE IF NOT EXISTS core.events (
    event_id                TEXT NOT NULL,
    canonical_match_id      BIGINT NOT NULL REFERENCES core.matches (canonical_match_id),
    source_match_id         BIGINT NOT NULL,
    event_index             INTEGER,
    period                  INTEGER,
    minute                  INTEGER,
    second                  INTEGER,
    canonical_team_id       BIGINT REFERENCES core.teams (canonical_team_id),
    canonical_player_id     BIGINT REFERENCES core.players (canonical_player_id),
    event_type              TEXT,
    x                       DOUBLE PRECISION,
    y                       DOUBLE PRECISION,
    end_x                   DOUBLE PRECISION,
    end_y                   DOUBLE PRECISION,
    end_z                   DOUBLE PRECISION,
    pass_recipient_id       BIGINT,
    pass_outcome            TEXT,
    pass_length             DOUBLE PRECISION,
    is_cross                BOOLEAN,
    shot_xg                 DOUBLE PRECISION,
    shot_outcome            TEXT,
    carry_end_x             DOUBLE PRECISION,
    carry_end_y             DOUBLE PRECISION,
    possession                      INTEGER,
    possession_team_id              BIGINT,
    canonical_possession_team_id    BIGINT REFERENCES core.teams (canonical_team_id),
    PRIMARY KEY (canonical_match_id, event_id)
);

ALTER TABLE core.events
    ADD COLUMN IF NOT EXISTS canonical_possession_team_id BIGINT
        REFERENCES core.teams (canonical_team_id);

CREATE INDEX IF NOT EXISTS idx_core_events_match
    ON core.events (canonical_match_id);
CREATE INDEX IF NOT EXISTS idx_core_events_type
    ON core.events (canonical_match_id, event_type);
