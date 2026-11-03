CREATE SCHEMA IF NOT EXISTS marts;

CREATE TABLE IF NOT EXISTS marts.box_entries (
    match_id        BIGINT NOT NULL,
    team_id         BIGINT NOT NULL,
    player_id       BIGINT,
    action_type     TEXT NOT NULL,
    is_cross        BOOLEAN NOT NULL DEFAULT FALSE,
    start_x         DOUBLE PRECISION,
    start_y         DOUBLE PRECISION,
    end_x           DOUBLE PRECISION,
    end_y           DOUBLE PRECISION,
    successful      BOOLEAN
);

CREATE TABLE IF NOT EXISTS marts.progressive_passes (
    match_id            BIGINT NOT NULL,
    team_id             BIGINT NOT NULL,
    player_id           BIGINT,
    start_x             DOUBLE PRECISION,
    start_y             DOUBLE PRECISION,
    end_x               DOUBLE PRECISION,
    end_y               DOUBLE PRECISION,
    start_zone          TEXT,
    end_zone            TEXT,
    distance_before     DOUBLE PRECISION,
    distance_after      DOUBLE PRECISION,
    progression         DOUBLE PRECISION,
    absolute_reduction  DOUBLE PRECISION,
    definition_used     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marts.possessions (
    possession_id       INTEGER NOT NULL,
    match_id            BIGINT NOT NULL,
    team_id             BIGINT NOT NULL,
    start_x             DOUBLE PRECISION,
    start_y             DOUBLE PRECISION,
    start_zone          TEXT,
    end_x               DOUBLE PRECISION,
    end_y               DOUBLE PRECISION,
    end_zone            TEXT,
    event_count         INTEGER,
    pass_count          INTEGER,
    duration            DOUBLE PRECISION,
    has_shot            BOOLEAN,
    has_goal            BOOLEAN,
    total_xg            DOUBLE PRECISION,
    PRIMARY KEY (match_id, possession_id)
);

DO $$
DECLARE
    pk_cols TEXT;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY array_position(c.conkey, a.attnum))
      INTO pk_cols
    FROM pg_constraint c
    JOIN pg_attribute a
      ON a.attrelid = c.conrelid
     AND a.attnum = ANY (c.conkey)
    WHERE c.conname = 'possessions_pkey'
      AND c.conrelid = 'marts.possessions'::regclass;

    IF pk_cols IS DISTINCT FROM 'match_id,possession_id' THEN
        TRUNCATE marts.possessions, marts.shot_possessions;
        IF pk_cols IS NOT NULL THEN
            ALTER TABLE marts.possessions DROP CONSTRAINT possessions_pkey;
        END IF;
        ALTER TABLE marts.possessions
            ADD CONSTRAINT possessions_pkey PRIMARY KEY (match_id, possession_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS marts.shot_possessions (
    start_zone              TEXT PRIMARY KEY,
    possessions             BIGINT NOT NULL,
    shot_possessions        BIGINT NOT NULL,
    shot_conversion_rate    DOUBLE PRECISION,
    total_xg                DOUBLE PRECISION,
    avg_xg                  DOUBLE PRECISION
);
