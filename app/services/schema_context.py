"""Build a capped schema summary for agent system prompts."""

from __future__ import annotations

import logging
from typing import Optional

from app.models.source import (
    NosqlSourceConfig,
    RestSourceConfig,
    SourceConfig,
    SourceType,
    SqlSourceConfig,
)
from app.services.source_files import library_source_root
from app.services.source_schema import fetch_mongo_schema, fetch_source_schema
from app.tools.file_sql import describe_file_tables_for_prompt
from app.tools.rest_get import normalize_allowed_prefixes

logger = logging.getLogger(__name__)

_SCHEMA_CAP_CHARS = 3500


async def build_attached_sources_schema_block(
    sources: list[SourceConfig],
    *,
    workspace_root=None,
    max_chars: int = _SCHEMA_CAP_CHARS,
) -> str:
    """
    Fetch schema summaries for attached sources and format a prompt section.

    Never raises — returns "" on failure / no relevant sources.
    """
    sections: list[str] = []

    sql_sources = [s for s in sources if s.type == SourceType.sql]
    for source in sql_sources:
        try:
            cfg = SqlSourceConfig.model_validate(source.config)
        except Exception:  # noqa: BLE001
            continue
        try:
            schema = await fetch_source_schema(source.id, cfg)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Schema context fetch failed for source %s: %s", source.id, exc
            )
            sections.append(
                f"### {source.title} (`{source.id}`)\n"
                f"(schema unavailable: {exc})\n"
            )
            continue

        lines = [
            f"### {source.title} (`{source.id}`, engine={schema.engine})",
        ]
        if source.description:
            lines.append(source.description.strip()[:400])

        demo_notes = await _try_demo_info(cfg)
        if demo_notes:
            lines.append("Table notes (demo_info):")
            lines.extend(f"- {n}" for n in demo_notes)

        if schema.tables:
            lines.append("Tables:")
            for table in schema.tables:
                col_names = ", ".join(c.name for c in table.columns[:24])
                extra = f" (~{table.row_count} rows)" if table.row_count is not None else ""
                more = "…" if len(table.columns) > 24 else ""
                lines.append(f"- `{table.name}`{extra}: {col_names}{more}")
        else:
            lines.append("(no tables found)")

        sections.append("\n".join(lines))

    mongo_sources = [
        s
        for s in sources
        if s.type == SourceType.nosql
        and (s.config or {}).get("engine", "mongodb") == "mongodb"
    ]
    for source in mongo_sources:
        try:
            cfg = NosqlSourceConfig.model_validate(source.config)
            schema = await fetch_mongo_schema(source.id, cfg)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Mongo schema context failed for source %s: %s", source.id, exc
            )
            sections.append(
                f"### {source.title} (`{source.id}`, mongodb)\n"
                f"(collections unavailable: {exc})\n"
            )
            continue
        lines = [
            f"### {source.title} (`{source.id}`, mongodb)",
            "Tools: `mongo_list_collections`, `mongo_find`, `mongo_aggregate` (read-only).",
        ]
        if source.description:
            lines.append(source.description.strip()[:400])
        if schema.tables:
            lines.append("Collections:")
            for table in schema.tables[:60]:
                lines.append(f"- `{table.name}`")
            if len(schema.tables) > 60:
                lines.append("…")
        else:
            lines.append("(no collections found)")
        sections.append("\n".join(lines))

    files_sources = [s for s in sources if s.type == SourceType.files]
    if files_sources and workspace_root is not None:
        mounts = {}
        titles = {}
        for source in files_sources:
            try:
                mounts[f"sources/{source.id}"] = library_source_root(
                    workspace_root, source.id
                )
                titles[source.id] = source.title
            except Exception as exc:  # noqa: BLE001
                logger.info("File mount for schema failed %s: %s", source.id, exc)
        if mounts:
            try:
                import asyncio

                blurb = await asyncio.to_thread(
                    describe_file_tables_for_prompt,
                    mounts,
                    source_titles=titles,
                    max_chars=1800,
                )
                if blurb:
                    sections.append(blurb)
            except Exception as exc:  # noqa: BLE001
                logger.info("File SQL schema blurb failed: %s", exc)

    for source in sources:
        if source.type != SourceType.rest:
            continue
        try:
            cfg = RestSourceConfig.model_validate(source.config)
        except Exception:  # noqa: BLE001
            continue
        prefixes = normalize_allowed_prefixes(cfg.allowed_path_prefixes)
        lines = [
            f"### {source.title} (`{source.id}`, rest)",
            f"base_url: {cfg.base_url}",
            "Tool: `http_get` (GET only).",
        ]
        if source.description:
            lines.append(source.description.strip()[:400])
        if prefixes:
            lines.append("Allowed path prefixes: " + ", ".join(prefixes))
        else:
            lines.append("Allowed path prefixes: (none configured — GETs rejected)")
        # Never include bearer_token / header_value.
        sections.append("\n".join(lines))

    if not sections:
        return ""

    body = "\n\n".join(sections)
    header = "Attached data sources / schema\n"
    text = header + body
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


async def _try_demo_info(cfg: SqlSourceConfig) -> list[str]:
    """Best-effort short descriptions from demo_info when the table exists."""
    if cfg.engine != "postgresql":
        return []
    try:
        from sqlalchemy import create_engine, text

        from app.services.db_tunnel import optional_ssh_tunnel
        from app.tools.sql_readonly import (
            _DEFAULT_PORTS,
            _engine_args_for_url,
            normalize_sqlalchemy_url,
        )

        url = normalize_sqlalchemy_url(cfg.engine, cfg.connection_string or "")
        default_port = _DEFAULT_PORTS.get(cfg.engine, 5432)

        def _run() -> list[str]:
            with optional_ssh_tunnel(url, cfg.ssh, default_remote_port=default_port) as effective:
                engine = create_engine(effective, **_engine_args_for_url(effective))
                try:
                    with engine.connect() as conn:
                        exists = conn.execute(
                            text(
                                """
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'public' AND table_name = 'demo_info'
                                """
                            )
                        ).fetchone()
                        if not exists:
                            return []
                        rows = conn.execute(
                            text(
                                """
                                SELECT table_name, description
                                FROM demo_info
                                ORDER BY table_name
                                LIMIT 40
                                """
                            )
                        ).fetchall()
                        out: list[str] = []
                        for name, desc in rows:
                            d = (desc or "").strip().replace("\n", " ")
                            if len(d) > 120:
                                d = d[:119] + "…"
                            out.append(f"`{name}` — {d}" if d else f"`{name}`")
                        return out
                finally:
                    engine.dispose()

        import asyncio

        return await asyncio.to_thread(_run)
    except Exception:  # noqa: BLE001
        return []


def append_schema_to_system_prompt(
    system_prompt: str, schema_block: Optional[str]
) -> str:
    block = (schema_block or "").strip()
    if not block:
        return system_prompt
    base = (system_prompt or "").rstrip()
    return f"{base}\n\n{block}\n"
