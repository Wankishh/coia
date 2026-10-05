"""Filesystem helpers for library file sources and agent workspace files."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path

# Global workspace dirs — never exposed via agent personal-files API.
RESERVED_WORKSPACE_DIRS = frozenset({"_library", "_chats", "_avatars"})


class SourceFilesError(ValueError):
    """Raised for invalid file-source operations."""


def library_source_root(workspace_root: Path, source_id: str) -> Path:
    """Global library files root: `{workspace}/_library/{source_id}/`."""
    sid = (source_id or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        raise SourceFilesError("Invalid source id for library path")
    library = (workspace_root / "_library").resolve()
    library.mkdir(parents=True, exist_ok=True)
    root = (library / sid).resolve()
    try:
        root.relative_to(library)
    except ValueError as exc:
        raise SourceFilesError("Invalid source id for library path") from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_root(workspace_root: Path, source_id: str) -> Path:
    """Alias for library_source_root (preferred API)."""
    return library_source_root(workspace_root, source_id)


def agent_workspace_root(workspace_root: Path, agent_id: str) -> Path:
    """Personal agent workspace: `{workspace}/{agent_id}/` only."""
    aid = (agent_id or "").strip()
    if (
        not aid
        or ".." in aid
        or "/" in aid
        or "\\" in aid
        or aid in RESERVED_WORKSPACE_DIRS
    ):
        raise SourceFilesError("Invalid agent id for workspace path")
    base = workspace_root.resolve()
    root = (base / aid).resolve()
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise SourceFilesError("Invalid agent id for workspace path") from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def assert_agent_file_path(relative_path: str) -> str:
    """Normalize and reject reserved / empty relative paths under agent workspace."""
    rel = (relative_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel in (".", ".."):
        raise SourceFilesError("path is empty")
    parts = Path(rel).parts
    if ".." in parts or parts[0] in RESERVED_WORKSPACE_DIRS:
        raise SourceFilesError(f"Path not allowed: {relative_path}")
    return Path(*parts).as_posix()


def normalize_dir_path(relative_path: str | None) -> str:
    """Normalize a directory relative path. Empty / '.' → '' (root)."""
    rel = (relative_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel == ".":
        return ""
    parts = Path(rel).parts
    if ".." in parts:
        raise SourceFilesError(f"Invalid path: {relative_path}")
    return Path(*parts).as_posix()


def assert_agent_dir_path(relative_path: str | None) -> str:
    """Normalize agent directory path; empty means workspace root."""
    rel = normalize_dir_path(relative_path)
    if not rel:
        return ""
    return assert_agent_file_path(rel)


def list_agent_workspace_files(
    root: Path, path: str | None = None
) -> list[dict[str, object]]:
    """List immediate children under agent workspace, hiding reserved top-level dirs."""
    rel_dir = assert_agent_dir_path(path)
    entries = list_source_files(root, rel_dir or None)
    if not rel_dir:
        filtered: list[dict[str, object]] = []
        for entry in entries:
            entry_path = str(entry.get("path") or "")
            parts = Path(entry_path).parts
            if parts and parts[0] in RESERVED_WORKSPACE_DIRS:
                continue
            filtered.append(entry)
        return filtered
    return entries


def agent_source_root(workspace_root: Path, agent_id: str, source_id: str) -> Path:
    """Legacy per-agent path (kept for migration / read fallback)."""
    root = (workspace_root / agent_id / "sources" / source_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def delete_library_source_dir(workspace_root: Path, source_id: str) -> None:
    root = (workspace_root / "_library" / source_id).resolve()
    library = (workspace_root / "_library").resolve()
    try:
        root.relative_to(library)
    except ValueError:
        return
    if root.exists() and root.is_dir():
        shutil.rmtree(root)


def resolve_source_file(root: Path, relative_path: str) -> Path:
    """Resolve a path under the source root; reject traversal."""
    try:
        return resolve_sandbox_path(root, relative_path)
    except SandboxPathError as exc:
        raise SourceFilesError(str(exc)) from exc


def _iso_from_timestamp(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _entry_times(path: Path) -> dict[str, str | None]:
    """Return ``mtime`` / ``created`` ISO timestamps from ``stat`` when available."""
    try:
        st = path.stat()
    except OSError:
        return {"mtime": None, "created": None}
    birth = getattr(st, "st_birthtime", None)
    created_ts = birth if birth is not None else st.st_ctime
    return {
        "mtime": _iso_from_timestamp(st.st_mtime),
        "created": _iso_from_timestamp(created_ts),
    }


def list_source_files(
    root: Path, path: str | None = None
) -> list[dict[str, object]]:
    """List immediate children of a relative directory under ``root``."""
    root = root.resolve()
    rel_dir = normalize_dir_path(path)
    target = root if not rel_dir else resolve_source_file(root, rel_dir)
    if not target.exists():
        if not rel_dir:
            return []
        raise SourceFilesError(f"Directory not found: {rel_dir}")
    if not target.is_dir():
        raise SourceFilesError(f"Not a directory: {rel_dir or '.'}")

    children = sorted(
        target.iterdir(),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    entries: list[dict[str, object]] = []
    for child in children:
        child_rel = child.relative_to(root).as_posix()
        times = _entry_times(child)
        if child.is_dir():
            entries.append(
                {
                    "name": child.name,
                    "path": child_rel,
                    "type": "dir",
                    "mtime": times["mtime"],
                    "created": times["created"],
                }
            )
        elif child.is_file():
            entries.append(
                {
                    "name": child.name,
                    "path": child_rel,
                    "type": "file",
                    "size": child.stat().st_size,
                    "is_text": _looks_like_text(child),
                    "mtime": times["mtime"],
                    "created": times["created"],
                }
            )
    return entries


def mkdir_path(root: Path, relative_path: str) -> Path:
    """Create a directory (and parents) under ``root``."""
    rel = normalize_dir_path(relative_path)
    if not rel:
        raise SourceFilesError("path is empty")
    target = resolve_source_file(root, rel)
    if target.exists() and not target.is_dir():
        raise SourceFilesError(f"Path exists and is not a directory: {rel}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_text_file(root: Path, relative_path: str) -> str:
    target = resolve_source_file(root, relative_path)
    if not target.exists() or not target.is_file():
        raise SourceFilesError(f"File not found: {relative_path}")
    return target.read_text(encoding="utf-8")


def write_text_file(root: Path, relative_path: str, content: str) -> Path:
    target = resolve_source_file(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_upload(
    root: Path,
    relative_path: str,
    data: bytes,
) -> Path:
    target = resolve_source_file(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def resolve_existing_file(root: Path, relative_path: str) -> Path:
    """Resolve an existing file under root for binary download."""
    target = resolve_source_file(root, relative_path)
    if not target.exists() or not target.is_file():
        raise SourceFilesError(f"File not found: {relative_path}")
    return target


def file_entry(root: Path, relative_path: str) -> dict[str, object]:
    """Build a file listing entry for an existing path."""
    target = resolve_existing_file(root, relative_path)
    times = _entry_times(target)
    return {
        "name": target.name,
        "path": relative_path.replace("\\", "/").strip().lstrip("/"),
        "type": "file",
        "size": target.stat().st_size,
        "is_text": _looks_like_text(target),
        "mtime": times["mtime"],
        "created": times["created"],
    }


def dir_entry(root: Path, relative_path: str) -> dict[str, object]:
    """Build a directory listing entry for an existing path."""
    rel = normalize_dir_path(relative_path)
    if not rel:
        raise SourceFilesError("path is empty")
    target = resolve_source_file(root, rel)
    if not target.exists() or not target.is_dir():
        raise SourceFilesError(f"Directory not found: {rel}")
    times = _entry_times(target)
    return {
        "name": target.name,
        "path": rel,
        "type": "dir",
        "mtime": times["mtime"],
        "created": times["created"],
    }


def delete_file(root: Path, relative_path: str) -> None:
    """Delete a file or directory (directories are removed recursively)."""
    target = resolve_source_file(root, relative_path)
    if not target.exists():
        raise SourceFilesError(f"File not found: {relative_path}")
    if target.is_file():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)
        return
    raise SourceFilesError(f"File not found: {relative_path}")


def _looks_like_text(path: Path, sample_size: int = 2048) -> bool:
    try:
        chunk = path.read_bytes()[:sample_size]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalize_upload_name(filename: str | None, fallback: str = "upload.bin") -> str:
    name = (filename or fallback).replace("\\", "/").strip()
    name = name.lstrip("/")
    if not name or name in (".", "..") or ".." in name.split("/"):
        raise SourceFilesError("Invalid upload filename")
    # Keep only the basename for safety when browsers send paths.
    return Path(name).name or fallback


def resolve_upload_relative_path(
    path: str | None, filename: str | None
) -> str:
    """
    Build the destination relative path for an upload.

    - ``path`` unset → upload filename (basename)
    - ``path`` ending with ``/`` → directory prefix + filename
    - otherwise ``path`` is the full relative destination
    """
    name = normalize_upload_name(filename)
    if not path:
        return name
    rel = path.replace("\\", "/").strip().lstrip("/")
    if not rel or rel == ".":
        return name
    if ".." in Path(rel).parts:
        raise SourceFilesError(f"Invalid path: {path}")
    if rel.endswith("/"):
        return f"{rel.rstrip('/')}/{name}"
    return Path(*Path(rel).parts).as_posix()


def ensure_relative_paths(paths: Iterable[str]) -> None:
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise SourceFilesError(f"Invalid path: {path}")
