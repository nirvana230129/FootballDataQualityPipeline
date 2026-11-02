CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.statsbomb_matches (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL DEFAULT 'statsbomb',
    entity_type     TEXT NOT NULL DEFAULT 'matches',
    source_id       TEXT NOT NULL,
    payload         JSONB NOT NULL,
    record_hash     TEXT NOT NULL,
    batch_id        UUID NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, entity_type, source_id, record_hash)
);

CREATE TABLE IF NOT EXISTS raw.statsbomb_lineups (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL DEFAULT 'statsbomb',
    entity_type     TEXT NOT NULL DEFAULT 'lineups',
    source_id       TEXT NOT NULL,
    payload         JSONB NOT NULL,
    record_hash     TEXT NOT NULL,
    batch_id        UUID NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, entity_type, source_id, record_hash)
);

CREATE TABLE IF NOT EXISTS raw.statsbomb_events (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL DEFAULT 'statsbomb',
    entity_type     TEXT NOT NULL DEFAULT 'events',
    source_id       TEXT NOT NULL,
    payload         JSONB NOT NULL,
    record_hash     TEXT NOT NULL,
    batch_id        UUID NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, entity_type, source_id, record_hash)
);

CREATE OR REPLACE VIEW raw.statsbomb_matches_current AS
SELECT DISTINCT ON (provider, entity_type, source_id)
    *
FROM raw.statsbomb_matches
ORDER BY provider, entity_type, source_id, loaded_at DESC, id DESC;

CREATE OR REPLACE VIEW raw.statsbomb_lineups_current AS
SELECT DISTINCT ON (provider, entity_type, source_id)
    *
FROM raw.statsbomb_lineups
ORDER BY provider, entity_type, source_id, loaded_at DESC, id DESC;

CREATE OR REPLACE VIEW raw.statsbomb_events_current AS
SELECT DISTINCT ON (provider, entity_type, source_id)
    *
FROM raw.statsbomb_events
ORDER BY provider, entity_type, source_id, loaded_at DESC, id DESC;
