from __future__ import annotations

from typing import Any

from mplsoccer import Pitch
from psycopg import Connection


def make_pitch(**kwargs: Any) -> Pitch:
    """Shared StatsBomb pitch (120 x 80, attack toward x=120)."""
    options = {"pitch_type": "statsbomb", "line_zorder": 2}
    options.update(kwargs)
    return Pitch(**options)


def load_zones(conn: Connection) -> list[tuple[str, float, float, float, float]]:
    """Return (zone_name, x_min, x_max, y_min, y_max) from config.pitch_zones."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT zone_name, x_min, x_max, y_min, y_max
            FROM config.pitch_zones
            ORDER BY zone_id
            """
        )
        return [(str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in cur.fetchall()]


def match_minutes(conn: Connection, source_match_id: int) -> float:
    """Approximate match length in minutes from staging events."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(minute), 89) + 1
            FROM staging.statsbomb_events
            WHERE match_id = %s
            """,
            (source_match_id,),
        )
        row = cur.fetchone()
    minutes = float(row[0] if row and row[0] is not None else 90)
    return max(minutes, 1.0)


def per90(count: int | float, minutes: float) -> float:
    return float(count) * 90.0 / minutes
