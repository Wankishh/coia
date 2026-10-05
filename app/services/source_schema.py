"""SQL / Mongo schema introspection for library data sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Connection

from app.models.source import NosqlSourceConfig, SqlSourceConfig
from app.services.db_tunnel import optional_ssh_tunnel
from app.tools.mongo_readonly import list_mongo_collection_names
from app.tools.sql_readonly import _DEFAULT_PORTS, _engine_args_for_url, normalize_sqlalchemy_url

logger = logging.getLogger(__name__)


class SchemaColumn(BaseModel):
    name: str
    data_type: str
    nullable: bool = True


class SchemaTable(BaseModel):
    name: str
    columns: list[SchemaColumn] = Field(default_factory=list)
    row_count: Optional[int] = Field(
        default=None,
        description="Approximate or exact row count when cheap to obtain",
    )


class SourceSchema(BaseModel):
    source_id: str
    engine: str
    tables: list[SchemaTable] = Field(default_factory=list)


async def fetch_source_schema(source_id: str, cfg: SqlSourceConfig) -> SourceSchema:
    """Inspect tables/columns (and cheap row counts) via the source connection."""
    tables = await asyncio.to_thread(_inspect_sql_schema, cfg)
    return SourceSchema(source_id=source_id, engine=cfg.engine, tables=tables)


async def fetch_mongo_schema(source_id: str, cfg: NosqlSourceConfig) -> SourceSchema:
    """List MongoDB collection names (columns unknown without sampling)."""
    conn = (cfg.connection_string or "").strip()
    if not conn:
        raise RuntimeError("MongoDB source has no connection_string")
    if cfg.engine != "mongodb":
        raise RuntimeError(f"Unsupported NoSQL engine: {cfg.engine}")

    names = await asyncio.to_thread(
        list_mongo_collection_names, conn, cfg.ssh
    )
    tables = [SchemaTable(name=n, columns=[]) for n in names]
    return SourceSchema(source_id=source_id, engine="mongodb", tables=tables)


def _inspect_sql_schema(cfg: SqlSourceConfig) -> list[SchemaTable]:
    conn = (cfg.connection_string or "").strip()
    if not conn:
        raise RuntimeError("SQL source has no connection_string")
    url = normalize_sqlalchemy_url(cfg.engine, conn)
    default_port = _DEFAULT_PORTS.get(cfg.engine, 5432)
    with optional_ssh_tunnel(url, cfg.ssh, default_remote_port=default_port) as effective:
        engine = create_engine(effective, **_engine_args_for_url(effective))
        try:
            with engine.connect() as connection:
                if cfg.engine == "postgresql":
                    return _schema_postgresql(connection)
                if cfg.engine == "mysql":
                    return _schema_mysql(connection)
                if cfg.engine == "sqlite":
                    return _schema_sqlite(connection)
                raise RuntimeError(f"Unsupported SQL engine: {cfg.engine}")
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Schema introspection failed: {exc}") from exc
        finally:
            engine.dispose()


def _schema_postgresql(connection: Connection) -> list[SchemaTable]:
    table_rows = connection.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
    ).fetchall()
    table_names = [str(r[0]) for r in table_rows]

    cols_by_table: dict[str, list[SchemaColumn]] = {name: [] for name in table_names}
    if table_names:
        col_rows = connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
                """
            )
        ).fetchall()
        for table_name, column_name, data_type, is_nullable in col_rows:
            if table_name not in cols_by_table:
                continue
            cols_by_table[str(table_name)].append(
                SchemaColumn(
                    name=str(column_name),
                    data_type=str(data_type),
                    nullable=str(is_nullable).upper() == "YES",
                )
            )

    # Exact counts — fine for admin browse / typical demo-sized schemas.
    counts: dict[str, Optional[int]] = {}
    for name in table_names:
        count_row = connection.execute(
            text(f'SELECT COUNT(*) FROM "{name}"')
        ).fetchone()
        counts[name] = int(count_row[0]) if count_row is not None else None

    return [
        SchemaTable(
            name=name,
            columns=cols_by_table.get(name, []),
            row_count=counts.get(name),
        )
        for name in table_names
    ]


def _schema_mysql(connection: Connection) -> list[SchemaTable]:
    table_rows = connection.execute(
        text(
            """
            SELECT table_name, table_rows
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
    ).fetchall()
    counts = {
        str(name): (int(rows) if rows is not None else None) for name, rows in table_rows
    }
    table_names = list(counts.keys())

    cols_by_table: dict[str, list[SchemaColumn]] = {name: [] for name in table_names}
    if table_names:
        col_rows = connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                ORDER BY table_name, ordinal_position
                """
            )
        ).fetchall()
        for table_name, column_name, data_type, is_nullable in col_rows:
            if table_name not in cols_by_table:
                continue
            cols_by_table[str(table_name)].append(
                SchemaColumn(
                    name=str(column_name),
                    data_type=str(data_type),
                    nullable=str(is_nullable).upper() == "YES",
                )
            )

    return [
        SchemaTable(
            name=name,
            columns=cols_by_table.get(name, []),
            row_count=counts.get(name),
        )
        for name in table_names
    ]


def _schema_sqlite(connection: Connection) -> list[SchemaTable]:
    table_rows = connection.execute(
        text(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ).fetchall()
    tables: list[SchemaTable] = []
    for (name,) in table_rows:
        table_name = str(name)
        col_rows = connection.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        columns = [
            SchemaColumn(
                name=str(row[1]),
                data_type=str(row[2] or "ANY"),
                nullable=not bool(row[3]),
            )
            for row in col_rows
        ]
        count_row = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).fetchone()
        row_count = int(count_row[0]) if count_row is not None else None
        tables.append(
            SchemaTable(name=table_name, columns=columns, row_count=row_count)
        )
    return tables
