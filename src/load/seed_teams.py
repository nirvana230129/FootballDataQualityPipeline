from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import psycopg

from src.db import ROOT


def seed_teams_from_csv(
    conn: psycopg.Connection,
    csv_path: Path | None = None,
) -> dict[str, int]:
    path = csv_path or (ROOT / "seeds" / "team_source_mapping.csv")
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_key[row["canonical_team_key"]].append(row)

    created_teams = 0
    upserted_mappings = 0

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS core.team_keys (
                canonical_team_key  TEXT PRIMARY KEY,
                canonical_team_id   BIGINT NOT NULL UNIQUE
                    REFERENCES core.teams (canonical_team_id)
            )
            """
        )

        for team_key, entries in by_key.items():
            display_name = next(
                (e["source_name"] for e in entries if e["provider"] == "statsbomb"),
                entries[0]["source_name"],
            )

            cur.execute(
                "SELECT canonical_team_id FROM core.team_keys WHERE canonical_team_key = %s",
                (team_key,),
            )
            existing = cur.fetchone()
            if existing:
                canonical_team_id = int(existing[0])
            else:
                # Prefer already-mapped StatsBomb team if present.
                sb = next((e for e in entries if e["provider"] == "statsbomb"), None)
                canonical_team_id = None
                if sb:
                    cur.execute(
                        """
                        SELECT canonical_team_id
                        FROM core.team_source_mapping
                        WHERE provider = 'statsbomb' AND source_team_id = %s
                        """,
                        (sb["source_team_id"],),
                    )
                    mapped = cur.fetchone()
                    if mapped:
                        canonical_team_id = int(mapped[0])

                if canonical_team_id is None:
                    cur.execute(
                        """
                        INSERT INTO core.teams (team_name)
                        VALUES (%s)
                        RETURNING canonical_team_id
                        """,
                        (display_name,),
                    )
                    canonical_team_id = int(cur.fetchone()[0])
                    created_teams += 1

                cur.execute(
                    """
                    INSERT INTO core.team_keys (canonical_team_key, canonical_team_id)
                    VALUES (%s, %s)
                    ON CONFLICT (canonical_team_key) DO UPDATE
                    SET canonical_team_id = EXCLUDED.canonical_team_id
                    """,
                    (team_key, canonical_team_id),
                )

            for entry in entries:
                cur.execute(
                    """
                    INSERT INTO core.team_source_mapping (
                        canonical_team_id, provider, source_team_id, source_name,
                        mapping_method, mapping_status
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider, source_team_id) DO UPDATE
                    SET canonical_team_id = EXCLUDED.canonical_team_id,
                        source_name = EXCLUDED.source_name,
                        mapping_method = EXCLUDED.mapping_method,
                        mapping_status = EXCLUDED.mapping_status
                    """,
                    (
                        canonical_team_id,
                        entry["provider"],
                        entry["source_team_id"],
                        entry["source_name"],
                        entry["mapping_method"],
                        entry["mapping_status"],
                    ),
                )
                upserted_mappings += 1

    return {"teams_created": created_teams, "mappings_upserted": upserted_mappings}
