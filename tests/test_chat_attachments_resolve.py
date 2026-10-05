"""Chat attachment path resolution and image detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chat_attachments import (
    ChatAttachmentError,
    is_image_attachment,
    resolve_chat_attachment_file,
    save_upload,
)


def test_is_image_attachment() -> None:
    assert is_image_attachment(content_type="image/png") is True
    assert is_image_attachment(name="hero.PNG") is True
    assert is_image_attachment(name="notes.txt") is False
    assert is_image_attachment(content_type="text/plain", name="x.png") is True


def test_resolve_chat_attachment_file(tmp_path: Path) -> None:
    att = save_upload(
        tmp_path,
        "chat-1",
        filename="shot.png",
        data=b"\x89PNG",
        content_type="image/png",
    )
    path = resolve_chat_attachment_file(tmp_path, "chat-1", att.name)
    assert path.is_file()
    assert path.read_bytes() == b"\x89PNG"


def test_resolve_rejects_traversal(tmp_path: Path) -> None:
    save_upload(tmp_path, "chat-1", filename="ok.png", data=b"x")
    with pytest.raises(ChatAttachmentError):
        resolve_chat_attachment_file(tmp_path, "chat-1", "../ok.png")
    with pytest.raises(ChatAttachmentError):
        resolve_chat_attachment_file(tmp_path, "../chat-1", "ok.png")
