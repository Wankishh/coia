"""Agent avatar files under `{workspace}/_avatars/{agent_id}/`."""

from __future__ import annotations

import shutil
from pathlib import Path

ALLOWED_PRESETS = frozenset(
    {"moss", "signal", "sky", "coral", "violet", "sand"}
)

ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_BASENAME = "avatar"


class AgentAvatarError(ValueError):
    """Invalid avatar upload or path."""


def avatars_root(workspace_root: Path) -> Path:
    return (workspace_root / "_avatars").resolve()


def agent_avatar_dir(workspace_root: Path, agent_id: str) -> Path:
    root = avatars_root(workspace_root)
    path = (root / agent_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AgentAvatarError("Invalid agent id for avatar path") from exc
    return path


def find_avatar_file(workspace_root: Path, agent_id: str) -> Path | None:
    directory = agent_avatar_dir(workspace_root, agent_id)
    if not directory.is_dir():
        return None
    for path in sorted(directory.iterdir()):
        if (
            path.is_file()
            and path.stem == AVATAR_BASENAME
            and path.suffix.lower() in ALLOWED_EXTENSIONS
        ):
            return path
    return None


def relative_avatar_path(workspace_root: Path, file_path: Path) -> str:
    return str(file_path.resolve().relative_to(workspace_root.resolve()))


def clear_avatar_files(workspace_root: Path, agent_id: str) -> None:
    directory = agent_avatar_dir(workspace_root, agent_id)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


def save_avatar_upload(
    workspace_root: Path,
    agent_id: str,
    *,
    filename: str | None,
    data: bytes,
) -> str:
    if not data:
        raise AgentAvatarError("Empty upload")
    if len(data) > MAX_AVATAR_BYTES:
        raise AgentAvatarError(
            f"Avatar too large (max {MAX_AVATAR_BYTES // 1024} KB)"
        )

    suffix = Path(filename or "avatar.png").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AgentAvatarError(
            "Unsupported image type (use png, jpg, webp, or gif)"
        )

    directory = agent_avatar_dir(workspace_root, agent_id)
    clear_avatar_files(workspace_root, agent_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{AVATAR_BASENAME}{suffix}"
    target.write_bytes(data)
    return relative_avatar_path(workspace_root, target)


def normalize_preset(value: str | None) -> str | None:
    if value is None:
        return None
    preset = value.strip().lower()
    if not preset:
        return None
    if preset not in ALLOWED_PRESETS:
        raise AgentAvatarError(f"Unknown avatar preset: {preset}")
    return preset
