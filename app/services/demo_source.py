"""Idempotent registration of the persistent Demo SQL data source."""

from __future__ import annotations

import logging
import socket
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from pymongo.errors import DuplicateKeyError

from app.config import Settings
from app.models.source import DataSource, DataSourceCreate, DataSourceUpdate, SourceType
from app.services.repos import SourceRepository

logger = logging.getLogger(__name__)

DEMO_SOURCE_ID = "demo-sales-db"
DEMO_SOURCE_TITLE = "Demo sales DB"

DEMO_SOURCE_DESCRIPTION = (
    "Read-only Postgres demo schema. If tables look missing or empty, "
    "reload with `python scripts/load_demo_db.py` or "
    "`docker compose up demo-db-seed` (no need for `down -v`).\n\n"
    "Start discovery with: SELECT * FROM demo_info;\n\n"
    "Tables:\n"
    "- demo_info (table_name, description, example_questions, row_count_hint) "
    "— catalog of this dataset\n"
    "- schema_version (version, applied_at, notes) — seed marker\n"
    "- sales_transactions (transaction_date, region, product, channel, "
    "quantity, unit_price, revenue, customer_segment, salesperson)\n"
    "- customers (id, name, email, country, segment, created_at)\n"
    "- products (id, name, category, unit_price, active)\n"
    "- employees (id, name, department, region, title, hire_date, email)\n"
    "- orders (id, customer_id, employee_id, order_date, status, channel, region)\n"
    "- order_items (id, order_id, product_id, quantity, unit_price, line_total)\n\n"
    "Agents attached to this source can run SELECT/WITH/SHOW/EXPLAIN "
    "via `run_sql_query`."
)


def resolve_demo_database_url(url: str) -> str:
    """
    Prefer the configured URL, but rewrite ``demo-db`` → ``localhost`` when the
    Docker hostname does not resolve (typical host-run harness + compose DB).
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    if (parsed.hostname or "").lower() != "demo-db":
        return raw
    try:
        socket.getaddrinfo("demo-db", None)
        return raw
    except OSError:
        netloc = parsed.netloc.replace("demo-db", "localhost", 1)
        rewritten = urlunparse(parsed._replace(netloc=netloc))
        logger.info(
            "demo-db hostname unresolved; using localhost for demo SQL URL"
        )
        return rewritten


def build_demo_source_payload(connection_string: str) -> dict[str, Any]:
    """Payload shape for API create / repository create."""
    return {
        "id": DEMO_SOURCE_ID,
        "title": DEMO_SOURCE_TITLE,
        "description": DEMO_SOURCE_DESCRIPTION,
        "type": "sql",
        "config": {
            "engine": "postgresql",
            "connection_string": resolve_demo_database_url(connection_string),
            "ssh": {"enabled": False},
        },
    }


def _matches_demo(source: DataSource) -> bool:
    if source.id == DEMO_SOURCE_ID:
        return True
    return source.title == DEMO_SOURCE_TITLE and source.type == SourceType.sql


async def _sync_demo_connection(
    source_repo: SourceRepository,
    source: DataSource,
    connection_string: str,
) -> DataSource:
    """Keep the demo source connection string aligned with settings."""
    current = (source.config or {}).get("connection_string") or ""
    if current.strip() == connection_string.strip():
        return source
    updated = await source_repo.update(
        source.id,
        DataSourceUpdate(
            config={
                **(source.config or {}),
                "connection_string": connection_string,
                "engine": (source.config or {}).get("engine") or "postgresql",
            }
        ),
    )
    if updated is not None:
        logger.info(
            "Updated demo data source connection string id=%s",
            source.id,
        )
        return updated
    return source


async def ensure_demo_source(
    source_repo: SourceRepository,
    settings: Settings,
) -> Optional[DataSource]:
    """
    Ensure the Demo sales DB library source exists (idempotent).

    Looks up by fixed id ``demo-sales-db`` or title ``Demo sales DB``.
    Creates from ``settings.demo_database_url`` when missing.
    """
    desired_url = resolve_demo_database_url(settings.demo_database_url)

    existing = await source_repo.get(DEMO_SOURCE_ID)
    if existing is not None:
        return await _sync_demo_connection(source_repo, existing, desired_url)

    for src in await source_repo.list_all():
        if _matches_demo(src):
            return await _sync_demo_connection(source_repo, src, desired_url)

    payload = DataSourceCreate.model_validate(
        build_demo_source_payload(desired_url)
    )
    try:
        source = await source_repo.create(payload)
    except DuplicateKeyError:
        raced = await source_repo.get(DEMO_SOURCE_ID)
        if raced is not None:
            return await _sync_demo_connection(source_repo, raced, desired_url)
        for src in await source_repo.list_all():
            if _matches_demo(src):
                return await _sync_demo_connection(source_repo, src, desired_url)
        raise

    logger.info(
        "Registered demo data source id=%s title=%r",
        source.id,
        source.title,
    )
    return source
