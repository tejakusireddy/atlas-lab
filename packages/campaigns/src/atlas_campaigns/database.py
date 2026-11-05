"""Transactional, checksum-guarded forward SQL migrations."""

import argparse
import hashlib
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

LOCAL_DSN = "postgresql://atlas:atlas-local-only@127.0.0.1:55432/atlas"
Connection = psycopg.Connection[dict[str, Any]]


def connect(dsn: str | None = None) -> Connection:
    return psycopg.connect(
        dsn or os.environ.get("ATLAS_DATABASE_URL", LOCAL_DSN),
        row_factory=dict_row,
        autocommit=True,
        connect_timeout=5,
    )


def migrate(connection: Connection, directory: Path = Path("sql")) -> None:
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise ValueError("No migrations found; run from the repository root")
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(737164920)")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        applied = {
            row["name"]: row["sha256"]
            for row in connection.execute("SELECT name, sha256 FROM schema_migrations")
        }
        if set(applied) - {path.name for path in files}:
            raise ValueError("Applied migration is missing from the checkout")
        for path in files:
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            connection.execute(path.read_text())
            connection.execute(
                "INSERT INTO schema_migrations(name, sha256) VALUES (%s,%s)", (path.name, checksum)
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("sql"))
    args = parser.parse_args()
    with connect() as connection:
        migrate(connection, args.directory)
    print("Database migrations applied and checksums verified.")
