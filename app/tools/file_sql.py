"""DuckDB SQL over attached library file mounts (CSV / TSV / Excel)."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.tools.sql_readonly import validate_readonly_sql

logger = logging.getLogger(__name__)

_MAX_ROWS = 200
_MAX_RESULT_CHARS = 50_000
_SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}

# Extra DuckDB / remote surface beyond the shared SQL readonly validator.
_DUCKDB_FORBIDDEN = re.compile(
    r"\b(INSTALL|LOAD|ATTACH|DETACH|EXPORT|COPY|PRAGMA|CALL|SET|RESET|"
    r"CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|MERGE|REPLACE|"
    r"VACUUM|CHECKPOINT|FORCE|httpfs|postgres|mysql|sqlite)\b",
    re.IGNORECASE,
)
_REMOTE_HINT = re.compile(
    r"(?:https?://|s3://|hf://|azure://|gcs://|ftp://)",
    re.IGNORECASE,
)


class FileSqlInput(BaseModel):
    query: str = Field(
        description=(
            "Read-only SQL against registered file tables "
            "(SELECT/WITH/SHOW/EXPLAIN only). Use the prefixed table names "
            "from the schema context."
        )
    )


def validate_file_sql(query: str) -> Optional[str]:
    """Readonly SQL plus DuckDB-specific blocks (INSTALL/LOAD/remote ATTACH)."""
    base = validate_readonly_sql(query)
    if base:
        return base
    cleaned = query.strip()
    no_block = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    no_comments = re.sub(r"--.*?$", " ", no_block, flags=re.MULTILINE)
    if _DUCKDB_FORBIDDEN.search(no_comments):
        return "Query contains forbidden DuckDB keywords (INSTALL/LOAD/ATTACH/DDL/…)"
    if _REMOTE_HINT.search(no_comments):
        return "Remote URLs are not allowed in file SQL"
    return None


def table_name_for_file(source_slug: str, relative_path: str) -> str:
    """
    Build a collision-safe DuckDB table identifier.

    Example: source ``sales``, file ``reports/q1.csv`` → ``sales_reports_q1``
    """
    slug = _slug_ident(source_slug)
    rel = relative_path.replace("\\", "/").lstrip("/")
    stem = Path(rel).with_suffix("").as_posix()
    body = _slug_ident(stem)
    name = f"{slug}_{body}" if body else slug
    if not name or not re.match(r"^[A-Za-z_]", name):
        name = f"t_{name}"
    return name[:63]


def _slug_ident(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return slug[:40] or "file"


def discover_file_tables(
    mounts: dict[str, Path],
    *,
    source_titles: Optional[dict[str, str]] = None,
) -> list[dict[str, str]]:
    """
    Scan mounts for queryable files.

    ``mounts`` maps virtual prefix (``sources/<id>``) → library root.
    Returns dicts with keys: table, path, source_id, format.
    """
    titles = source_titles or {}
    tables: list[dict[str, str]] = []
    seen: set[str] = set()
    for prefix, root in sorted(mounts.items(), key=lambda kv: kv[0]):
        root = root.resolve()
        if not root.is_dir():
            continue
        parts = Path(prefix.strip("/")).parts
        source_id = parts[1] if len(parts) >= 2 and parts[0] == "sources" else parts[-1]
        slug_base = _slug_ident(titles.get(source_id) or source_id)
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in _SUPPORTED_SUFFIXES:
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            name = table_name_for_file(slug_base, rel)
            # Disambiguate collisions within the same agent toolset.
            final = name
            n = 2
            while final in seen:
                final = f"{name}_{n}"[:63]
                n += 1
            seen.add(final)
            tables.append(
                {
                    "table": final,
                    "path": str(path),
                    "rel_path": rel,
                    "source_id": source_id,
                    "format": suffix.lstrip("."),
                }
            )
    return tables


def _register_tables(con, tables: list[dict[str, str]]) -> None:
    for entry in tables:
        table = entry["table"]
        path = entry["path"]
        fmt = entry["format"]
        # Quote path for DuckDB string literal.
        lit = path.replace("'", "''")
        if fmt == "csv":
            con.execute(
                f'CREATE OR REPLACE VIEW "{table}" AS '
                f"SELECT * FROM read_csv_auto('{lit}', header=true)"
            )
        elif fmt == "tsv":
            con.execute(
                f'CREATE OR REPLACE VIEW "{table}" AS '
                f"SELECT * FROM read_csv_auto('{lit}', header=true, sep='\\t')"
            )
        elif fmt in ("xlsx", "xls"):
            # Avoid DuckDB INSTALL/LOAD excel — register via openpyxl/pandas.
            try:
                import pandas as pd
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("pandas is required for Excel file SQL") from exc
            engine = "openpyxl" if fmt == "xlsx" else None
            df = pd.read_excel(path, engine=engine)
            con.register(table, df)


def _format_result(columns: list[str], rows: list[tuple]) -> str:
    if not columns:
        return "(no columns)"
    lines = [" | ".join(columns)]
    lines.append(" | ".join("---" for _ in columns))
    for row in rows:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    text = "\n".join(lines)
    if len(text) > _MAX_RESULT_CHARS:
        return text[: _MAX_RESULT_CHARS - 1].rstrip() + "…"
    return text


def create_file_sql_tool(
    mounts: dict[str, Path],
    *,
    source_titles: Optional[dict[str, str]] = None,
    name: str = "run_file_sql",
) -> Optional[StructuredTool]:
    """
    Build a DuckDB SQL tool over CSV/TSV/XLSX files in library mounts.

    Returns None when no queryable files are present.
    """
    tables = discover_file_tables(mounts, source_titles=source_titles)
    if not tables:
        return None

    table_list = ", ".join(f'`{t["table"]}` ({t["format"]}: {t["rel_path"]})' for t in tables[:40])
    more = "…" if len(tables) > 40 else ""
    description = (
        "Execute read-only SQL against attached file sources via DuckDB. "
        f"Allowed: SELECT, WITH, SHOW, EXPLAIN. Tables: {table_list}{more}. "
        "Do not use INSTALL/LOAD/ATTACH or remote URLs."
    )

    def _run_sync(query: str) -> str:
        error = validate_file_sql(query)
        if error:
            return f"Rejected: {error}"
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover
            return f"Error: duckdb is not installed ({exc})"

        try:
            con = duckdb.connect(database=":memory:")
            try:
                _register_tables(con, tables)
                # Cap rows for SELECT-like queries by wrapping when no LIMIT present.
                limited = query.rstrip().rstrip(";")
                result = con.execute(limited)
                columns = [d[0] for d in result.description] if result.description else []
                rows = result.fetchmany(_MAX_ROWS)
                body = _format_result(columns, rows)
                if len(rows) >= _MAX_ROWS:
                    body += f"\n… (truncated at {_MAX_ROWS} rows)"
                return body
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("file SQL failed: %s", exc)
            return f"SQL error: {exc}"

    async def run_file_sql(query: str) -> str:
        return await asyncio.to_thread(_run_sync, query)

    return StructuredTool.from_function(
        coroutine=run_file_sql,
        name=name,
        description=description,
        args_schema=FileSqlInput,
    )


def describe_file_tables_for_prompt(
    mounts: dict[str, Path],
    *,
    source_titles: Optional[dict[str, str]] = None,
    max_chars: int = 2000,
) -> str:
    """Schema blurb: table → columns (best-effort sample)."""
    tables = discover_file_tables(mounts, source_titles=source_titles)
    if not tables:
        return ""

    lines: list[str] = ["File SQL tables (DuckDB via `run_file_sql`):"]
    try:
        import duckdb
    except ImportError:
        for t in tables:
            lines.append(f"- `{t['table']}` ← {t['rel_path']} ({t['format']})")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    con = duckdb.connect(database=":memory:")
    try:
        _register_tables(con, tables)
        for t in tables:
            try:
                info = con.execute(f'DESCRIBE "{t["table"]}"').fetchall()
                cols = ", ".join(str(r[0]) for r in info[:24])
                more = "…" if len(info) > 24 else ""
                lines.append(
                    f"- `{t['table']}` ← {t['rel_path']} ({t['format']}): {cols}{more}"
                )
            except Exception:  # noqa: BLE001
                lines.append(
                    f"- `{t['table']}` ← {t['rel_path']} ({t['format']})"
                )
    finally:
        con.close()

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text
