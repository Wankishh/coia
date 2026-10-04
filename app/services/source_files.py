"""Filesystem helpers for library file sources."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path


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


def list_source_files(root: Path) -> list[dict[str, object]]:
    root = root.resolve()
    if not root.exists():
        return []
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": rel,
                "size": path.stat().st_size,
                "is_text": _looks_like_text(path),
            }
        )
    return entries


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


def delete_file(root: Path, relative_path: str) -> None:
    target = resolve_source_file(root, relative_path)
    if not target.exists() or not target.is_file():
        raise SourceFilesError(f"File not found: {relative_path}")
    target.unlink()
    # Clean empty parent dirs up to root
    parent = target.parent
    while parent != root and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


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
    return name


def ensure_relative_paths(paths: Iterable[str]) -> None:
    for path in paths:
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise SourceFilesError(f"Invalid path: {path}")
