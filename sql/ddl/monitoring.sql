CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.pipeline_runs (
    run_id              UUID PRIMARY KEY,
    dag_id              TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL,
    source              TEXT,
    records_extracted   BIGINT,
    records_loaded      BIGINT,
    records_skipped_same_hash BIGINT,
    error_message       TEXT,
    dq_mode             TEXT
);

CREATE TABLE IF NOT EXISTS monitoring.data_quality_results (
    check_id            BIGSERIAL PRIMARY KEY,
    run_id              UUID NOT NULL,
    source              TEXT,
    schema_name         TEXT,
    table_name          TEXT,
    canonical_match_id  BIGINT,
    check_name          TEXT NOT NULL,
    check_type          TEXT,
    severity            TEXT NOT NULL,
    status              TEXT NOT NULL,
    records_checked     BIGINT,
    records_failed      BIGINT,
    failure_rate        DOUBLE PRECISION,
    executed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details             JSONB
);

CREATE TABLE IF NOT EXISTS monitoring.match_publication_status (
    canonical_match_id      BIGINT PRIMARY KEY,
    dq_status               TEXT,
    publication_status      TEXT NOT NULL DEFAULT 'PUBLISHABLE',
    is_quarantined          BOOLEAN NOT NULL DEFAULT FALSE,
    critical_check_count    INTEGER NOT NULL DEFAULT 0,
    warning_check_count     INTEGER NOT NULL DEFAULT 0,
    last_checked_at         TIMESTAMPTZ
);
