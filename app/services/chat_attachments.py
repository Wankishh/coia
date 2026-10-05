"""Store chat session file attachments under workspace `_chats/{chat_id}/`."""

from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path

from app.models.conversation import ChatAttachment
from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})


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


def is_image_attachment(
    *,
    name: str | None = None,
    content_type: str | None = None,
) -> bool:
    """True when content_type or filename looks like a previewable image."""
    ct = (content_type or "").lower().strip()
    if ct.startswith("image/"):
        return True
    suffix = Path(name or "").suffix.lower()
    return suffix in _IMAGE_SUFFIXES


def resolve_chat_attachment_file(
    workspace_root: Path,
    chat_id: str,
    filename: str,
) -> Path:
    """
    Resolve a single attachment file under `_chats/{chat_id}/`.

    Rejects path traversal; does not create the chat directory.
    """
    if not chat_id or ".." in chat_id or "/" in chat_id or "\\" in chat_id:
        raise ChatAttachmentError("Invalid chat id")
    raw = filename or ""
    if not raw or raw in (".", "..") or "/" in raw or "\\" in raw or ".." in raw:
        raise ChatAttachmentError("Invalid attachment filename")
    name = safe_filename(raw)
    if not name:
        raise ChatAttachmentError("Invalid attachment filename")
    root = chats_root(workspace_root)
    directory = (root / chat_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ChatAttachmentError("Invalid chat id") from exc
    if not directory.is_dir():
        raise ChatAttachmentError("Chat attachments not found")
    target = (directory / name).resolve()
    try:
        target.relative_to(directory)
    except ValueError as exc:
        raise ChatAttachmentError("Invalid attachment filename") from exc
    if not target.is_file():
        raise ChatAttachmentError("Attachment file not found")
    return target


def guess_content_type(path: Path, content_type: str | None = None) -> str:
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


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
