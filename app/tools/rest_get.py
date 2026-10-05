"""Read-only HTTP GET tool for REST API data sources (SSRF-hardened)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.models.source import RestAuthType, RestSourceConfig

logger = logging.getLogger(__name__)

_MAX_RESPONSE_CHARS = 50_000
_DEFAULT_TIMEOUT = 15.0
_MAX_TIMEOUT = 60.0


class HttpGetInput(BaseModel):
    path: str = Field(
        description=(
            "Relative path under the source base_url "
            "(e.g. '/v1/orders' or 'v1/orders'). Query string in path is ignored; "
            "use query_params."
        )
    )
    query_params_json: str = Field(
        default="{}",
        description='Optional query parameters as a JSON object, e.g. \'{"page":"1"}\'',
    )


def normalize_allowed_prefixes(prefixes: list[str]) -> list[str]:
    out: list[str] = []
    for p in prefixes or []:
        text = (p or "").strip()
        if not text:
            continue
        if not text.startswith("/"):
            text = "/" + text
        # Keep trailing slash semantics loose — store without forcing slash.
        out.append(text.rstrip("/") or "/")
    return out


def path_allowed(path: str, allowed_prefixes: list[str]) -> bool:
    """True when path is under at least one allowlisted prefix."""
    normalized = _normalize_rel_path(path)
    if normalized is None:
        return False
    prefixes = normalize_allowed_prefixes(allowed_prefixes)
    if not prefixes:
        # Empty allowlist → deny all (safe default).
        return False
    for prefix in prefixes:
        if prefix == "/":
            return True
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def _normalize_rel_path(path: str) -> Optional[str]:
    raw = (path or "").strip()
    if not raw:
        return None
    # Reject absolute URLs / scheme-relative.
    if "://" in raw or raw.startswith("//"):
        return None
    if "\\" in raw:
        return None
    # Drop query/fragment if the model stuffed them into path.
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    if not raw.startswith("/"):
        raw = "/" + raw
    # Normalize .. and .
    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(segment)
    return "/" + "/".join(parts) if parts else "/"


def build_request_url(
    base_url: str,
    path: str,
    query_params: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Join base_url + relative path; enforce same host (no open redirect / SSRF).

    Returns (url, error).
    """
    base = (base_url or "").strip()
    if not base:
        return None, "base_url is empty"
    parsed_base = urlparse(base)
    if parsed_base.scheme not in ("http", "https"):
        return None, "base_url must be http or https"
    if not parsed_base.netloc:
        return None, "base_url is missing a host"
    rel = _normalize_rel_path(path)
    if rel is None:
        return None, "path is invalid or escapes the base"

    # Force path from our normalized rel under base host.
    base_path = parsed_base.path.rstrip("/")
    full_path = (base_path + rel) if rel != "/" else (base_path or "/")
    if not full_path.startswith("/"):
        full_path = "/" + full_path

    query = ""
    if query_params:
        # Flatten to str values; reject nested structures.
        pairs: list[tuple[str, str]] = []
        for key, value in query_params.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                return None, "query_params values must be scalars"
            pairs.append((str(key), str(value)))
        query = urlencode(pairs)

    candidate = urlunparse(
        (
            parsed_base.scheme,
            parsed_base.netloc,
            full_path,
            "",
            query,
            "",
        )
    )
    parsed = urlparse(candidate)
    if parsed.scheme != parsed_base.scheme:
        return None, "URL scheme mismatch"
    if parsed.hostname != parsed_base.hostname:
        return None, "URL host escapes base_url (SSRF guard)"
    if parsed.port != parsed_base.port:
        # Allow implicit default ports to match explicit.
        base_port = parsed_base.port or (443 if parsed_base.scheme == "https" else 80)
        cand_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if base_port != cand_port:
            return None, "URL port escapes base_url (SSRF guard)"
    return candidate, None


def auth_headers(cfg: RestSourceConfig) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json, text/plain, */*"}
    if cfg.auth == RestAuthType.none:
        return headers
    if cfg.auth == RestAuthType.bearer:
        token = (cfg.bearer_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
    if cfg.auth == RestAuthType.header:
        name = (cfg.header_name or "").strip()
        value = (cfg.header_value or "").strip()
        if name and value:
            headers[name] = value
    return headers


def create_http_get_tool(
    rest_config: RestSourceConfig,
    *,
    title: str,
    description: str = "",
    name: str = "http_get",
) -> StructuredTool:
    base_url = (rest_config.base_url or "").strip()
    if not base_url:
        raise ValueError(f"REST source '{title}' has no base_url")
    prefixes = normalize_allowed_prefixes(rest_config.allowed_path_prefixes)
    timeout = float(rest_config.timeout_seconds or _DEFAULT_TIMEOUT)
    timeout = max(1.0, min(timeout, _MAX_TIMEOUT))

    desc_parts = [
        f"HTTP GET against REST source '{title}' (base_url={base_url}).",
        "GET only — no POST/PUT/PATCH/DELETE.",
    ]
    if description.strip():
        desc_parts.append(description.strip())
    if prefixes:
        desc_parts.append(
            "Allowed path prefixes: " + ", ".join(prefixes) + "."
        )
    else:
        desc_parts.append("No path prefixes configured — all GETs will be rejected.")

    def _run_sync(path: str, query_params_json: str = "{}") -> str:
        if not path_allowed(path, prefixes):
            return "Rejected: path is not under an allowed_path_prefixes entry"
        params: dict[str, Any] = {}
        raw = (query_params_json or "").strip()
        if raw:
            import json

            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError as exc:
                return f"Rejected: query_params_json is not valid JSON: {exc}"
            if not isinstance(loaded, dict):
                return "Rejected: query_params_json must be a JSON object"
            params = loaded

        url, err = build_request_url(base_url, path, params)
        if err:
            return f"Rejected: {err}"
        assert url is not None

        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                headers=auth_headers(rest_config),
            ) as client:
                # Manual redirect follow staying on same host (max 3).
                current = url
                response = None
                for _ in range(4):
                    response = client.get(current)
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            break
                        next_url = urljoin(current, location)
                        next_parsed = urlparse(next_url)
                        base_parsed = urlparse(base_url)
                        if next_parsed.hostname != base_parsed.hostname:
                            return "Rejected: redirect escapes base_url host"
                        if next_parsed.scheme not in ("http", "https"):
                            return "Rejected: redirect uses unsupported scheme"
                        # Re-check path allowlist against redirect path relative to base.
                        base_path = (base_parsed.path or "").rstrip("/")
                        redirect_path = next_parsed.path or "/"
                        if base_path and redirect_path.startswith(base_path):
                            rel = redirect_path[len(base_path) :] or "/"
                        else:
                            rel = redirect_path
                        if not path_allowed(rel, prefixes):
                            return "Rejected: redirect path not allowlisted"
                        current = next_url
                        continue
                    break
                assert response is not None
                text = response.text
                if len(text) > _MAX_RESPONSE_CHARS:
                    text = text[: _MAX_RESPONSE_CHARS - 1].rstrip() + "…"
                return f"HTTP {response.status_code}\n{text}"
        except httpx.TimeoutException:
            return f"Error: request timed out after {timeout}s"
        except Exception as exc:  # noqa: BLE001
            logger.warning("http_get failed: %s", exc)
            return f"Error: {exc}"

    async def http_get(path: str, query_params_json: str = "{}") -> str:
        return await asyncio.to_thread(_run_sync, path, query_params_json)

    return StructuredTool.from_function(
        coroutine=http_get,
        name=name,
        description=" ".join(desc_parts),
        args_schema=HttpGetInput,
    )


async def test_rest_connection(cfg: RestSourceConfig, title: str) -> str:
    """Probe with GET against base_url (or first allowlisted prefix)."""
    base = (cfg.base_url or "").strip()
    if not base:
        raise RuntimeError(f"REST source '{title}' has no base_url")
    prefixes = normalize_allowed_prefixes(cfg.allowed_path_prefixes)
    probe_path = prefixes[0] if prefixes else "/"
    url, err = build_request_url(base, probe_path, None)
    if err:
        raise RuntimeError(err)
    timeout = max(1.0, min(float(cfg.timeout_seconds or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=auth_headers(cfg),
    ) as client:
        response = await client.get(url)
    return f"GET {probe_path} → HTTP {response.status_code}"
