"""Sandboxed filesystem tools scoped to an agent workspace (+ library mounts)."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class SandboxPathError(ValueError):
    """Raised when a path escapes the agent workspace / allowed mounts."""


def resolve_sandbox_path(workspace: Path, relative_path: str) -> Path:
    """Resolve a relative path within workspace; reject traversal."""
    workspace = workspace.resolve()
    # Normalize and reject absolute / parent escapes early
    candidate = (workspace / relative_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise SandboxPathError(
            f"Path '{relative_path}' is outside the agent workspace"
        ) from exc
    return candidate


def resolve_sandbox_or_mount(
    workspace: Path,
    relative_path: str,
    mounts: dict[str, Path] | None = None,
) -> Path:
    """
    Resolve a relative path under the workspace, or under a library mount.

    Mounts map a virtual prefix (e.g. ``sources/<id>``) to a real directory
    (library root). Read/list use mounts; write to a mount is allowed so agents
    can annotate shared file sources when attached.
    """
    normalized = (relative_path or ".").replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise SandboxPathError(f"Path '{relative_path}' must be relative")
    parts = Path(normalized).parts
    if ".." in parts:
        raise SandboxPathError(f"Path '{relative_path}' escapes sandbox")

    if mounts:
        # Longest prefix match
        for prefix in sorted(mounts.keys(), key=len, reverse=True):
            prefix_norm = prefix.strip("/")
            if normalized == prefix_norm or normalized.startswith(prefix_norm + "/"):
                rest = normalized[len(prefix_norm) :].lstrip("/")
                root = mounts[prefix].resolve()
                if rest in ("", "."):
                    return root
                candidate = (root / rest).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError as exc:
                    raise SandboxPathError(
                        f"Path '{relative_path}' is outside mounted source"
                    ) from exc
                return candidate

    return resolve_sandbox_path(workspace, normalized)


class ReadFileInput(BaseModel):
    path: str = Field(description="Relative path within the agent workspace")


class WriteFileInput(BaseModel):
    path: str = Field(description="Relative path within the agent workspace")
    content: str = Field(description="File contents to write")


class ListFilesInput(BaseModel):
    path: str = Field(
        default=".",
        description="Relative directory within the agent workspace (default '.')",
    )


def create_sandbox_tools(
    workspace: Path,
    *,
    library_mounts: dict[str, Path] | None = None,
) -> list[StructuredTool]:
    """
    Build sandbox tools.

    ``library_mounts`` maps virtual paths like ``sources/<source_id>`` to
    global library directories under ``_library/<source_id>/``.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    mounts = dict(library_mounts or {})

    # Ensure a ``sources/`` directory listing shows attached mount names.
    sources_dir = workspace / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    for prefix in mounts:
        # prefix is like sources/<id> — create a marker so list_files(".") sees it
        rel = Path(prefix)
        if len(rel.parts) >= 2 and rel.parts[0] == "sources":
            marker = sources_dir / rel.parts[1]
            if not marker.exists():
                marker.mkdir(parents=True, exist_ok=True)

    def read_file(path: str) -> str:
        try:
            target = resolve_sandbox_or_mount(workspace, path, mounts)
        except SandboxPathError as exc:
            return f"Error: {exc}"
        if not target.exists() or not target.is_file():
            return f"Error: file not found: {path}"
        return target.read_text(encoding="utf-8")

    def write_file(path: str, content: str) -> str:
        try:
            target = resolve_sandbox_or_mount(workspace, path, mounts)
        except SandboxPathError as exc:
            return f"Error: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path}"

    def list_files(path: str = ".") -> str:
        try:
            target = resolve_sandbox_or_mount(workspace, path, mounts)
        except SandboxPathError as exc:
            return f"Error: {exc}"
        if not target.exists():
            return f"Error: directory not found: {path}"
        if not target.is_dir():
            return f"Error: not a directory: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        # When listing workspace sources/, also surface mount ids that lack markers
        norm = (path or ".").replace("\\", "/").strip().strip("/")
        if norm in (".", "") or norm == "sources":
            # Already created markers; just return
            pass
        return "\n".join(entries) if entries else "(empty)"

    mount_hint = ""
    if mounts:
        listed = ", ".join(sorted(mounts.keys()))
        mount_hint = f" Attached library file sources are readable under: {listed}."

    return [
        StructuredTool.from_function(
            func=read_file,
            name="read_file",
            description=(
                "Read a text file from the agent workspace. "
                "Path must be relative and stay within the workspace."
                + mount_hint
            ),
            args_schema=ReadFileInput,
        ),
        StructuredTool.from_function(
            func=write_file,
            name="write_file",
            description=(
                "Write a text file into the agent workspace. "
                "Path must be relative and stay within the workspace."
                + mount_hint
            ),
            args_schema=WriteFileInput,
        ),
        StructuredTool.from_function(
            func=list_files,
            name="list_files",
            description=(
                "List files and directories in a workspace-relative path."
                + mount_hint
            ),
            args_schema=ListFilesInput,
        ),
    ]
