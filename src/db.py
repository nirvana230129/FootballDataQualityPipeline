from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "football")
    user = os.getenv("POSTGRES_USER", "football")
    password = os.getenv("POSTGRES_PASSWORD", "football")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), connect_timeout=10)


def read_sql(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def execute_sql_file(conn: psycopg.Connection, relative_path: str) -> None:
    sql = read_sql(relative_path)
    with conn.cursor() as cur:
        cur.execute(sql)


DDL_FILES = [
    "sql/ddl/raw.sql",
    "sql/ddl/staging.sql",
    "sql/ddl/core.sql",
    "sql/ddl/config.sql",
    "sql/ddl/monitoring.sql",
    "sql/ddl/marts.sql",
]
