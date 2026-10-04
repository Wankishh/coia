"""Connection probes for data sources (SQL / NoSQL / files)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.models.source import (
    DataSource,
    DataSourceCreate,
    NosqlSourceConfig,
    SourceConfig,
    SourceType,
    SqlSourceConfig,
    merge_source_secrets,
)
from app.services.db_tunnel import optional_ssh_tunnel
from app.services.source_files import source_root
from app.tools.sql_readonly import _DEFAULT_PORTS, _engine_args_for_url, normalize_sqlalchemy_url

logger = logging.getLogger(__name__)


class SourceTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: Optional[int] = None


class SourceTestRequest(BaseModel):
    """Draft or override source config for connection tests."""

    title: str = "draft"
    description: str = ""
    type: Optional[SourceType] = None
    config: dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None


def _as_source_config(
    payload: Union[DataSource, SourceConfig, DataSourceCreate, SourceTestRequest],
) -> SourceConfig:
    if isinstance(payload, SourceConfig):
        return payload
    source_type = getattr(payload, "type", None)
    if source_type is None:
        raise ValueError("source type is required for connection test")
    return SourceConfig(
        id=getattr(payload, "id", None) or "draft",
        title=getattr(payload, "title", None) or "draft",
        description=getattr(payload, "description", "") or "",
        type=source_type,
        config=dict(getattr(payload, "config", None) or {}),
    )


async def test_source_connection(
    payload: Union[DataSource, SourceConfig, DataSourceCreate, SourceTestRequest],
    settings: Settings,
    *,
    existing: Optional[DataSource] = None,
) -> SourceTestResult:
    """
    Run a trivial connectivity check.

    When ``existing`` is provided, omitted secrets on the payload are filled
    from the stored source (same merge rules as PATCH).
    """
    incoming = _as_source_config(payload)
    if existing is not None:
        incoming = merge_source_secrets(existing.as_source_config(), incoming)

    started = time.perf_counter()
    try:
        if incoming.type == SourceType.files:
            message = await asyncio.to_thread(
                _test_files, settings.workspace_path, incoming.id
            )
        elif incoming.type == SourceType.sql:
            typed = SqlSourceConfig.model_validate(incoming.config)
            message = await asyncio.to_thread(_test_sql, typed, incoming.title)
        elif incoming.type == SourceType.nosql:
            typed = NosqlSourceConfig.model_validate(incoming.config)
            message = await asyncio.to_thread(_test_nosql, typed, incoming.title)
        else:
            return SourceTestResult(ok=False, message=f"Unsupported type: {incoming.type}")
        latency = int((time.perf_counter() - started) * 1000)
        return SourceTestResult(ok=True, message=message, latency_ms=latency)
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - started) * 1000)
        logger.info("Source test failed for %s: %s", incoming.title, exc)
        return SourceTestResult(
            ok=False,
            message=str(exc) or "Connection test failed",
            latency_ms=latency,
        )


def _test_files(workspace_root: Path, source_id: str) -> str:
    root = source_root(workspace_root, source_id)
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Library folder missing: {root}")
    probe = root / ".coia_write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Library folder not writable: {exc}") from exc
    return f"Folder exists and is writable ({root.name})"


def _test_sql(cfg: SqlSourceConfig, title: str) -> str:
    conn = (cfg.connection_string or "").strip()
    if not conn:
        raise RuntimeError(f"SQL source '{title}' has no connection_string")
    url = normalize_sqlalchemy_url(cfg.engine, conn)
    default_port = _DEFAULT_PORTS.get(cfg.engine, 5432)
    with optional_ssh_tunnel(url, cfg.ssh, default_remote_port=default_port) as effective:
        engine = create_engine(effective, **_engine_args_for_url(effective))
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise RuntimeError(f"SQL error: {exc}") from exc
        finally:
            engine.dispose()
    ssh_note = " via SSH" if cfg.ssh and cfg.ssh.enabled else ""
    return f"SELECT 1 succeeded ({cfg.engine}{ssh_note})"


def _test_nosql(cfg: NosqlSourceConfig, title: str) -> str:
    conn = (cfg.connection_string or "").strip()
    if not conn:
        raise RuntimeError(f"NoSQL source '{title}' has no connection_string")
    if cfg.engine != "mongodb":
        raise RuntimeError(f"Unsupported NoSQL engine: {cfg.engine}")

    # Mongo ping; optional SSH rewrite of host/port when enabled.
    default_port = 27017
    with optional_ssh_tunnel(conn, cfg.ssh, default_remote_port=default_port) as effective:
        try:
            from pymongo import MongoClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pymongo is not installed") from exc
        client = MongoClient(effective, serverSelectionTimeoutMS=8000)
        try:
            client.admin.command("ping")
        finally:
            client.close()
    ssh_note = " via SSH" if cfg.ssh and cfg.ssh.enabled else ""
    return f"MongoDB ping succeeded{ssh_note}"
