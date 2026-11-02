CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS config.pitch_settings (
    key     TEXT PRIMARY KEY,
    value   DOUBLE PRECISION NOT NULL
);

INSERT INTO config.pitch_settings (key, value) VALUES
    ('pitch_length', 120),
    ('pitch_width', 80),
    ('attack_direction_x', 120)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

CREATE TABLE IF NOT EXISTS config.pitch_zones (
    zone_id     INTEGER PRIMARY KEY,
    zone_name   TEXT NOT NULL UNIQUE,
    x_min       DOUBLE PRECISION NOT NULL,
    x_max       DOUBLE PRECISION NOT NULL,
    y_min       DOUBLE PRECISION NOT NULL,
    y_max       DOUBLE PRECISION NOT NULL
);

TRUNCATE config.pitch_zones;

INSERT INTO config.pitch_zones (zone_id, zone_name, x_min, x_max, y_min, y_max) VALUES
    (1,  'def_right',      0,  24, 0,           80.0/3),
    (2,  'def_centre',     0,  24, 80.0/3,      160.0/3),
    (3,  'def_left',       0,  24, 160.0/3,     80),
    (4,  'def_mid_right',  24, 48, 0,           80.0/3),
    (5,  'def_mid_centre', 24, 48, 80.0/3,      160.0/3),
    (6,  'def_mid_left',   24, 48, 160.0/3,     80),
    (7,  'mid_right',      48, 72, 0,           80.0/3),
    (8,  'mid_centre',     48, 72, 80.0/3,      160.0/3),
    (9,  'mid_left',       48, 72, 160.0/3,     80),
    (10, 'att_mid_right',  72, 96, 0,           80.0/3),
    (11, 'att_mid_centre', 72, 96, 80.0/3,      160.0/3),
    (12, 'att_mid_left',   72, 96, 160.0/3,     80),
    (13, 'att_right',      96, 120, 0,          80.0/3),
    (14, 'att_centre',     96, 120, 80.0/3,     160.0/3),
    (15, 'att_left',       96, 120, 160.0/3,    80);
