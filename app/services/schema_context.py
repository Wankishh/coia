"""Build a capped schema summary for agent system prompts."""

from __future__ import annotations

import logging
from typing import Optional

from app.models.source import SourceConfig, SourceType, SqlSourceConfig
from app.services.source_schema import fetch_source_schema

logger = logging.getLogger(__name__)

_SCHEMA_CAP_CHARS = 3500


async def build_attached_sources_schema_block(
    sources: list[SourceConfig],
    *,
    max_chars: int = _SCHEMA_CAP_CHARS,
) -> str:
    """
    Fetch SQL schema summaries (table names + demo_info descriptions when present)
    and format a prompt section. Never raises — returns "" on failure / no SQL sources.
    """
    sql_sources = [s for s in sources if s.type == SourceType.sql]
    if not sql_sources:
        return ""

    sections: list[str] = []
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
