"""Store chat session file attachments under workspace `_chats/{chat_id}/`."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.models.conversation import ChatAttachment
from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ChatAttachmentError(ValueError):
    """Invalid attachment operation."""


def chats_root(workspace_root: Path) -> Path:
    root = (workspace_root / "_chats").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def chat_dir(workspace_root: Path, chat_id: str) -> Path:
    if not chat_id or ".." in chat_id or "/" in chat_id or "\\" in chat_id:
        raise ChatAttachmentError("Invalid chat id")
    root = chats_root(workspace_root)
    path = (root / chat_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ChatAttachmentError("Invalid chat id") from exc
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "upload.bin"
    return cleaned[:180]


def save_upload(
    workspace_root: Path,
    chat_id: str,
    *,
    filename: str,
    data: bytes,
    content_type: str | None = None,
) -> ChatAttachment:
    if len(data) > 8 * 1024 * 1024:
        raise ChatAttachmentError("Attachment too large (max 8 MB)")
    directory = chat_dir(workspace_root, chat_id)
    name = safe_filename(filename)
    target = directory / name
    # Avoid overwrite collisions
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        n = 2
        while True:
            candidate = directory / f"{stem}_{n}{suffix}"
            if not candidate.exists():
                target = candidate
                name = candidate.name
                break
            n += 1
    target.write_bytes(data)
    return ChatAttachment(
        name=name,
        path=name,
        size=len(data),
        content_type=content_type,
    )


def mirror_into_agent_workspace(
    workspace_root: Path,
    agent_id: str,
    chat_id: str,
    attachment: ChatAttachment,
) -> Path:
    """
    Copy attachment into the agent sandbox so tools can read it at
    `_chat_attachments/{name}`.
    """
    src = chat_dir(workspace_root, chat_id) / attachment.path
    if not src.is_file():
        raise ChatAttachmentError("Attachment file missing on disk")
    agent_root = (workspace_root / agent_id).resolve()
    agent_root.mkdir(parents=True, exist_ok=True)
    dest_dir = agent_root / "_chat_attachments"
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        dest = resolve_sandbox_path(agent_root, f"_chat_attachments/{attachment.name}")
    except SandboxPathError as exc:
        raise ChatAttachmentError(str(exc)) from exc
    shutil.copy2(src, dest)
    return dest
