from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from src.utils.hashing import payload_hash


def insert_raw_payload(
    conn: psycopg.Connection,
    *,
    table: str,
    source_id: str,
    payload: Any,
    batch_id: uuid.UUID,
    provider: str = "statsbomb",
    entity_type: str,
) -> str:
    """Insert a raw version. Returns loaded|skipped_same_hash."""
    record_hash = payload_hash(payload)
    sql = f"""
        INSERT INTO {table} (
            provider, entity_type, source_id, payload, record_hash, batch_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (provider, entity_type, source_id, record_hash) DO NOTHING
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (provider, entity_type, source_id, Jsonb(payload), record_hash, batch_id),
        )
        row = cur.fetchone()
    return "loaded" if row else "skipped_same_hash"


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
