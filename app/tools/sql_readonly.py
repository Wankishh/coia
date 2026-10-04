"""Read-only SQL tool against a configured database (agent source or demo)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from langchain_community.utilities import SQLDatabase
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from app.models.source import SshConfig, SqlSourceConfig
from app.services.db_tunnel import optional_ssh_tunnel

logger = logging.getLogger(__name__)

# Only allow read-oriented statement prefixes (after stripping comments/whitespace).
_ALLOWED_PREFIX = re.compile(
    r"^\s*(WITH|SELECT|SHOW|EXPLAIN)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|"
    r"COPY|EXECUTE|CALL|MERGE|REPLACE|ATTACH|DETACH|"
    r"INTO|SETVAL|NEXTVAL|"
    r"PG_READ_FILE|PG_READ_BINARY_FILE|PG_LS_DIR|PG_STAT_FILE|"
    r"LO_IMPORT|LO_EXPORT|DBLINK|DBLINK_EXEC|DBLINK_CONNECT|"
    r"FILE_FDW|POSTGRES_FDW)\b",
    re.IGNORECASE,
)
_MULTI_STATEMENT = re.compile(r";\s*\S")

# Postgres session guards (ms for statement_timeout).
_PG_CONNECT_OPTIONS = (
    "-c default_transaction_read_only=on "
    "-c statement_timeout=15000"
)

_DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "sqlite": 0,
}


class SqlQueryInput(BaseModel):
    query: str = Field(description="Read-only SQL query (SELECT/WITH/SHOW/EXPLAIN only)")


def validate_readonly_sql(query: str) -> Optional[str]:
    """Return an error message if the query is not allowed; else None."""
    cleaned = query.strip()
    if not cleaned:
        return "Query is empty"

    # Strip block and line comments for validation
    no_block = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    no_comments = re.sub(r"--.*?$", " ", no_block, flags=re.MULTILINE).strip()

    if _MULTI_STATEMENT.search(no_comments.rstrip(";")):
        return "Multiple SQL statements are not allowed"

    if not _ALLOWED_PREFIX.match(no_comments):
        return "Only SELECT, WITH, SHOW, and EXPLAIN queries are allowed"

    if _FORBIDDEN.search(no_comments):
        return "Query contains forbidden write/DDL keywords"

    return None


def normalize_sqlalchemy_url(engine: str, connection_string: str) -> str:
    """Ensure the URL has a SQLAlchemy-compatible driver prefix."""
    raw = connection_string.strip()
    if not raw:
        raise ValueError("connection_string is empty")

    if engine == "sqlite":
        if raw.startswith("sqlite:"):
            return raw
        # Treat bare path as sqlite file
        return f"sqlite:///{raw.lstrip('/')}" if not raw.startswith("/") else f"sqlite:///{raw}"

    if "://" not in raw:
        raise ValueError("connection_string must be a URL (e.g. postgresql://user:pass@host/db)")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()

    if engine == "postgresql":
        if scheme in ("postgresql", "postgres", "postgresql+psycopg2"):
            if scheme in ("postgresql", "postgres"):
                return raw.replace(f"{parsed.scheme}://", "postgresql+psycopg2://", 1)
            return raw
        raise ValueError(f"Unexpected scheme for postgresql: {scheme}")

    if engine == "mysql":
        if scheme in ("mysql", "mysql+pymysql"):
            if scheme == "mysql":
                return raw.replace("mysql://", "mysql+pymysql://", 1)
            return raw
        raise ValueError(f"Unexpected scheme for mysql: {scheme}")

    return raw


def _engine_args_for_url(url: str) -> dict:
    if url.startswith("postgresql"):
        return {
            "connect_args": {"options": _PG_CONNECT_OPTIONS},
            "pool_pre_ping": True,
        }
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


def create_sql_tool(
    database_url: str,
    *,
    name: str = "run_sql_query",
    description: Optional[str] = None,
    engine: str = "postgresql",
    ssh: Optional[SshConfig] = None,
) -> StructuredTool:
    """
    Build a read-only SQL tool.

    When ssh.enabled, each query opens a short-lived tunnel (MVP-safe; not pooled).
    """
    tool_description = description or (
        "Execute a read-only SQL query against the configured database. "
        "Allowed: SELECT, WITH, SHOW, EXPLAIN."
    )

    def _run_sync(query: str) -> str:
        error = validate_readonly_sql(query)
        if error:
            return f"Rejected: {error}"
        try:
            url = normalize_sqlalchemy_url(engine, database_url)
        except ValueError as exc:
            return f"Config error: {exc}"

        default_port = _DEFAULT_PORTS.get(engine, 5432)
        try:
            with optional_ssh_tunnel(url, ssh, default_remote_port=default_port) as effective_url:
                if ssh and ssh.enabled:
                    # Note for operators / model: tunnel is active for this query.
                    pass
                db = SQLDatabase.from_uri(
                    effective_url,
                    engine_args=_engine_args_for_url(effective_url),
                )
                return db.run(query)
        except SQLAlchemyError as exc:
            logger.warning("SQL query failed: %s", exc)
            return f"SQL error: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected SQL tool error")
            return f"Error: {exc}"

    async def run_sql_query(query: str) -> str:
        return await asyncio.to_thread(_run_sync, query)

    return StructuredTool.from_function(
        coroutine=run_sql_query,
        name=name,
        description=tool_description,
        args_schema=SqlQueryInput,
    )


def create_sql_tool_from_source(
    sql_config: SqlSourceConfig,
    *,
    title: str,
    description: str = "",
    name: str = "run_sql_query",
    fallback_url: Optional[str] = None,
) -> StructuredTool:
    conn = (sql_config.connection_string or "").strip() or (fallback_url or "")
    if not conn:
        raise ValueError(f"SQL source '{title}' has no connection_string")

    desc_parts = [
        f"Execute a read-only SQL query against data source '{title}'.",
    ]
    if description.strip():
        desc_parts.append(description.strip())
    desc_parts.append(
        f"Engine: {sql_config.engine}. Allowed: SELECT, WITH, SHOW, EXPLAIN."
    )
    if sql_config.ssh and sql_config.ssh.enabled:
        desc_parts.append("SSH tunneling will be used at runtime for this source.")

    return create_sql_tool(
        conn,
        name=name,
        description=" ".join(desc_parts),
        engine=sql_config.engine,
        ssh=sql_config.ssh,
    )
