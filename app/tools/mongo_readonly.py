"""Read-only MongoDB tools (list_collections / find / aggregate)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from bson import ObjectId
from bson.json_util import dumps as bson_dumps
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.source import NosqlSourceConfig, SshConfig
from app.services.db_tunnel import optional_ssh_tunnel

logger = logging.getLogger(__name__)

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20
_MAX_TIME_MS = 15_000
_MAX_RESULT_CHARS = 50_000

# Aggregation stages / operators that write or are dangerous in a shared agent.
_BLOCKED_STAGE_OR_OP = re.compile(
    r"\$(?:out|merge|function|accumulator|currentOp|listLocalSessions|"
    r"planCacheStats|collStats|indexStats|queryStats|searchMeta)\b",
    re.IGNORECASE,
)
_BLOCKED_FILTER_OPS = re.compile(
    r"\$(?:where|function|accumulator)\b",
    re.IGNORECASE,
)
_WRITE_COLLECTION_HINT = re.compile(
    r"\b(?:insert(?:_one|_many)?|update(?:_one|_many)?|replace_one|"
    r"delete(?:_one|_many)?|drop(?:_database|_collection)?|"
    r"create_index|create_collection|bulk_write|rename_collection|"
    r"find_one_and_(?:update|replace|delete)|map_reduce)\b",
    re.IGNORECASE,
)


class MongoListInput(BaseModel):
    """No arguments — lists collection names in the configured database."""


class MongoFindInput(BaseModel):
    collection: str = Field(description="Collection name")
    filter_json: str = Field(
        default="{}",
        description='MongoDB filter as JSON object string, e.g. \'{"status":"active"}\'',
    )
    projection_json: str = Field(
        default="",
        description="Optional projection as JSON object string (empty = all fields)",
    )
    limit: int = Field(
        default=_DEFAULT_LIMIT,
        description=f"Max documents to return (1–{_MAX_LIMIT})",
        ge=1,
        le=_MAX_LIMIT,
    )


class MongoAggregateInput(BaseModel):
    collection: str = Field(description="Collection name")
    pipeline_json: str = Field(
        description="Aggregation pipeline as a JSON array string (read-only stages only)"
    )
    limit: int = Field(
        default=_DEFAULT_LIMIT,
        description=f"Cap on returned documents after the pipeline (1–{_MAX_LIMIT})",
        ge=1,
        le=_MAX_LIMIT,
    )


def validate_mongo_filter(filter_obj: Any) -> Optional[str]:
    """Return an error if the find filter uses blocked operators."""
    try:
        raw = json.dumps(filter_obj, default=str)
    except (TypeError, ValueError):
        return "Filter is not JSON-serializable"
    if _BLOCKED_FILTER_OPS.search(raw):
        return "Filter contains forbidden operator ($where / $function)"
    if _WRITE_COLLECTION_HINT.search(raw):
        return "Filter contains forbidden write-oriented tokens"
    return None


def validate_mongo_pipeline(pipeline: Any) -> Optional[str]:
    """Return an error if the aggregation pipeline is not allowed."""
    if not isinstance(pipeline, list):
        return "Pipeline must be a JSON array"
    if len(pipeline) > 40:
        return "Pipeline is too long (max 40 stages)"
    try:
        raw = json.dumps(pipeline, default=str)
    except (TypeError, ValueError):
        return "Pipeline is not JSON-serializable"
    if _BLOCKED_STAGE_OR_OP.search(raw):
        return (
            "Pipeline contains forbidden stage/operator "
            "($out, $merge, $function, …)"
        )
    if _WRITE_COLLECTION_HINT.search(raw):
        return "Pipeline contains forbidden write-oriented tokens"
    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            return "Each pipeline stage must be a single-key object"
        key = next(iter(stage))
        if not str(key).startswith("$"):
            return f"Invalid stage key: {key}"
        if str(key).lower() in ("$out", "$merge"):
            return f"Forbidden aggregation stage: {key}"
    return None


def _parse_json_object(raw: str, *, label: str) -> tuple[Optional[dict], Optional[str]]:
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{label} is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"{label} must be a JSON object"
    return value, None


def _parse_json_array(raw: str, *, label: str) -> tuple[Optional[list], Optional[str]]:
    text = (raw or "").strip()
    if not text:
        return None, f"{label} is empty"
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{label} is not valid JSON: {exc}"
    if not isinstance(value, list):
        return None, f"{label} must be a JSON array"
    return value, None


def _cap_result(text: str) -> str:
    if len(text) <= _MAX_RESULT_CHARS:
        return text
    return text[: _MAX_RESULT_CHARS - 1].rstrip() + "…"


def _serialize_docs(docs: list[Any]) -> str:
    # Prefer extended JSON for ObjectId/dates; fall back to str.
    try:
        return _cap_result(bson_dumps(docs, indent=2))
    except Exception:  # noqa: BLE001
        def _default(obj: Any) -> Any:
            if isinstance(obj, ObjectId):
                return str(obj)
            return str(obj)

        return _cap_result(json.dumps(docs, indent=2, default=_default))


def _db_name_from_uri(uri: str) -> Optional[str]:
    # mongodb://host/dbname?... or mongodb+srv://...
    try:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        path = (parsed.path or "").lstrip("/")
        if path:
            return path.split("/")[0] or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _client_kwargs() -> dict[str, Any]:
    return {
        "serverSelectionTimeoutMS": 8000,
        "connectTimeoutMS": 8000,
        "socketTimeoutMS": _MAX_TIME_MS + 2000,
    }


def create_mongo_tools_from_source(
    nosql_config: NosqlSourceConfig,
    *,
    title: str,
    description: str = "",
    name_prefix: str = "mongo",
) -> list[StructuredTool]:
    """
    Build list_collections / find / aggregate tools for one Mongo source.

    ``name_prefix`` is ``mongo`` for the first attached source, or
    ``mongo_{slug}`` for additional sources (mirrors SQL multi-source naming).
    """
    conn = (nosql_config.connection_string or "").strip()
    if not conn:
        raise ValueError(f"NoSQL source '{title}' has no connection_string")
    if nosql_config.engine != "mongodb":
        raise ValueError(f"Unsupported NoSQL engine: {nosql_config.engine}")

    ssh = nosql_config.ssh
    desc_bits = [f"MongoDB source '{title}'."]
    if description.strip():
        desc_bits.append(description.strip())
    if ssh and ssh.enabled:
        desc_bits.append("SSH tunneling is used at runtime.")
    base_desc = " ".join(desc_bits)

    def _with_client(fn):
        def _run(*args, **kwargs):
            with optional_ssh_tunnel(conn, ssh, default_remote_port=27017) as effective:
                from pymongo import MongoClient

                client = MongoClient(effective, **_client_kwargs())
                try:
                    db_name = _db_name_from_uri(effective)
                    db = client.get_default_database() if not db_name else client[db_name]
                    if db is None:
                        # URI without path — require explicit default; use first non-system.
                        names = [
                            n
                            for n in client.list_database_names()
                            if n not in ("admin", "local", "config")
                        ]
                        if not names:
                            return "Error: connection URI has no database name"
                        db = client[names[0]]
                    return fn(db, *args, **kwargs)
                finally:
                    client.close()

        return _run

    def _list_sync() -> str:
        try:
            def work(db, *_a, **_k) -> str:
                names = sorted(db.list_collection_names())
                return _cap_result(json.dumps(names, indent=2))

            return _with_client(work)()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo list_collections failed: %s", exc)
            return f"Error: {exc}"

    def _find_sync(
        collection: str,
        filter_json: str = "{}",
        projection_json: str = "",
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        coll = (collection or "").strip()
        if not coll:
            return "Rejected: collection is required"
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", coll):
            return "Rejected: invalid collection name"
        filt, err = _parse_json_object(filter_json, label="filter_json")
        if err:
            return f"Rejected: {err}"
        assert filt is not None
        ferr = validate_mongo_filter(filt)
        if ferr:
            return f"Rejected: {ferr}"
        projection = None
        if (projection_json or "").strip():
            projection, perr = _parse_json_object(projection_json, label="projection_json")
            if perr:
                return f"Rejected: {perr}"
        lim = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
        try:
            def work(db, *_a, **_k) -> str:
                cursor = (
                    db[coll]
                    .find(filt, projection, max_time_ms=_MAX_TIME_MS)
                    .limit(lim)
                )
                docs = list(cursor)
                return _serialize_docs(docs)

            return _with_client(work)()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo find failed: %s", exc)
            return f"Error: {exc}"

    def _aggregate_sync(
        collection: str,
        pipeline_json: str,
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        coll = (collection or "").strip()
        if not coll:
            return "Rejected: collection is required"
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", coll):
            return "Rejected: invalid collection name"
        pipeline, err = _parse_json_array(pipeline_json, label="pipeline_json")
        if err:
            return f"Rejected: {err}"
        assert pipeline is not None
        perr = validate_mongo_pipeline(pipeline)
        if perr:
            return f"Rejected: {perr}"
        lim = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
        # Enforce a trailing $limit so results stay capped even if the model omits one.
        capped = list(pipeline) + [{"$limit": lim}]
        try:
            def work(db, *_a, **_k) -> str:
                cursor = db[coll].aggregate(capped, maxTimeMS=_MAX_TIME_MS)
                docs = list(cursor)
                return _serialize_docs(docs)

            return _with_client(work)()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mongo aggregate failed: %s", exc)
            return f"Error: {exc}"

    async def list_collections() -> str:
        return await asyncio.to_thread(_list_sync)

    async def find(
        collection: str,
        filter_json: str = "{}",
        projection_json: str = "",
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        return await asyncio.to_thread(
            _find_sync, collection, filter_json, projection_json, limit
        )

    async def aggregate(
        collection: str,
        pipeline_json: str,
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        return await asyncio.to_thread(
            _aggregate_sync, collection, pipeline_json, limit
        )

    prefix = name_prefix.strip("_") or "mongo"
    return [
        StructuredTool.from_function(
            coroutine=list_collections,
            name=f"{prefix}_list_collections",
            description=(
                f"{base_desc} List collection names (read-only)."
            ),
            args_schema=MongoListInput,
        ),
        StructuredTool.from_function(
            coroutine=find,
            name=f"{prefix}_find",
            description=(
                f"{base_desc} Find documents (read-only). "
                f"limit ≤ {_MAX_LIMIT}; forbidden: write ops / $where."
            ),
            args_schema=MongoFindInput,
        ),
        StructuredTool.from_function(
            coroutine=aggregate,
            name=f"{prefix}_aggregate",
            description=(
                f"{base_desc} Run a read-only aggregation pipeline. "
                f"Forbidden stages: $out, $merge, $function. "
                f"Results capped to ≤ {_MAX_LIMIT} docs."
            ),
            args_schema=MongoAggregateInput,
        ),
    ]


def list_mongo_collection_names(
    connection_string: str,
    ssh: Optional[SshConfig] = None,
) -> list[str]:
    """Synchronous helper for schema introspection."""
    conn = (connection_string or "").strip()
    if not conn:
        raise RuntimeError("MongoDB source has no connection_string")
    with optional_ssh_tunnel(conn, ssh, default_remote_port=27017) as effective:
        from pymongo import MongoClient

        client = MongoClient(effective, **_client_kwargs())
        try:
            db_name = _db_name_from_uri(effective)
            if db_name:
                db = client[db_name]
            else:
                db = client.get_default_database()
                if db is None:
                    names = [
                        n
                        for n in client.list_database_names()
                        if n not in ("admin", "local", "config")
                    ]
                    if not names:
                        return []
                    db = client[names[0]]
            return sorted(db.list_collection_names())
        finally:
            client.close()
