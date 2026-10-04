#!/usr/bin/env python3
"""Apply init_demo_db.sql to the demo Postgres (re-runnable; no volume wipe needed)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

DEFAULT_URL = "postgresql://demo:demo@localhost:5432/demo"
SQL_FILENAME = "init_demo_db.sql"


def normalize_database_url(url: str) -> str:
    """psycopg2 accepts postgresql://; strip SQLAlchemy driver suffixes."""
    cleaned = url.strip()
    for prefix in ("postgresql+psycopg2://", "postgres+psycopg2://"):
        if cleaned.startswith(prefix):
            cleaned = "postgresql://" + cleaned[len(prefix) :]
            break
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql://" + cleaned[len("postgres://") :]
    return cleaned


def resolve_sql_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"SQL file not found: {path}")
        return path

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / SQL_FILENAME,  # repo root when running scripts/load_demo_db.py
        Path.cwd() / SQL_FILENAME,
        Path("/app") / SQL_FILENAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"Could not find {SQL_FILENAME}. Pass --sql PATH or run from the repo root."
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Load / reload the Coia demo Postgres schema (idempotent)."
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Postgres URL (default: DEMO_DATABASE_URL or localhost demo credentials)",
    )
    parser.add_argument(
        "--sql",
        default=None,
        help=f"Path to {SQL_FILENAME}",
    )
    args = parser.parse_args()

    url = normalize_database_url(
        args.url or os.getenv("DEMO_DATABASE_URL") or DEFAULT_URL
    )
    sql_path = resolve_sql_path(args.sql)
    sql = sql_path.read_text(encoding="utf-8")

    print(f"Applying {sql_path} → {url.split('@')[-1] if '@' in url else url}")
    try:
        with psycopg2.connect(url) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "SELECT version, applied_at, notes FROM schema_version ORDER BY version"
                )
                rows = cur.fetchall()
                cur.execute(
                    "SELECT table_name FROM demo_info ORDER BY table_name"
                )
                tables = [r[0] for r in cur.fetchall()]
    except psycopg2.Error as exc:
        print(f"Postgres error: {exc}", file=sys.stderr)
        return 1

    for version, applied_at, notes in rows:
        print(f"schema_version={version} applied_at={applied_at} notes={notes}")
    print(f"demo_info tables ({len(tables)}): {', '.join(tables)}")
    print("Demo DB load complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
