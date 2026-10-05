"""Agent personal workspace file helpers (sandbox + reserved dirs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.source_files import (
    SourceFilesError,
    agent_workspace_root,
    assert_agent_file_path,
    delete_file,
    list_agent_workspace_files,
    list_source_files,
    mkdir_path,
    resolve_upload_relative_path,
    write_upload,
)
from app.tools.sandbox_file import SandboxPathError, resolve_sandbox_path


def test_agent_workspace_root_creates_under_workspace(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    assert root == (tmp_path / "agent-1").resolve()
    assert root.is_dir()


def test_agent_workspace_root_rejects_reserved_and_traversal(tmp_path: Path) -> None:
    for bad in ("_library", "_chats", "_avatars", "../x", "a/b", ""):
        with pytest.raises(SourceFilesError):
            agent_workspace_root(tmp_path, bad)


def test_assert_agent_file_path_blocks_reserved() -> None:
    assert assert_agent_file_path("notes/memory.md") == "notes/memory.md"
    for bad in ("_library/x", "_chats/a.txt", "_avatars/p.png", "../escape", ""):
        with pytest.raises(SourceFilesError):
            assert_agent_file_path(bad)


def test_list_hides_reserved_top_level(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    write_upload(root, "memory.txt", b"hello")
    (root / "_library").mkdir()
    (root / "_library" / "secret.txt").write_text("nope", encoding="utf-8")
    (root / "_chats").mkdir()
    (root / "_chats" / "c.txt").write_text("nope", encoding="utf-8")

    entries = list_agent_workspace_files(root)
    paths = {e["path"] for e in entries}
    assert paths == {"memory.txt"}
    assert all(e["type"] == "file" for e in entries)


def test_list_immediate_children_dirs_first(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    mkdir_path(root, "reports")
    write_upload(root, "a.txt", b"a")
    write_upload(root, "reports/foo.csv", b"x,y\n")

    root_entries = list_agent_workspace_files(root)
    assert [e["path"] for e in root_entries] == ["reports", "a.txt"]
    assert root_entries[0]["type"] == "dir"
    assert root_entries[0]["name"] == "reports"
    assert root_entries[1]["type"] == "file"

    nested = list_agent_workspace_files(root, "reports")
    assert len(nested) == 1
    assert nested[0]["path"] == "reports/foo.csv"
    assert nested[0]["name"] == "foo.csv"
    assert nested[0]["type"] == "file"


def test_mkdir_and_delete_empty_dir(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    mkdir_path(root, "reports/nested")
    assert (root / "reports" / "nested").is_dir()
    delete_file(root, "reports/nested")
    assert not (root / "reports" / "nested").exists()
    delete_file(root, "reports")
    assert not (root / "reports").exists()


def test_delete_dir_recursive(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    mkdir_path(root, "reports")
    write_upload(root, "reports/foo.csv", b"1")
    delete_file(root, "reports")
    assert not (root / "reports").exists()


def test_list_includes_mtime_and_created(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    write_upload(root, "memory.txt", b"hello")
    mkdir_path(root, "notes")
    entries = {e["path"]: e for e in list_source_files(root)}
    assert entries["memory.txt"]["mtime"]
    assert entries["memory.txt"]["created"]
    assert entries["notes"]["mtime"]
    assert entries["notes"]["created"]
    assert entries["notes"]["type"] == "dir"


def test_resolve_upload_relative_path() -> None:
    assert resolve_upload_relative_path(None, "foo.csv") == "foo.csv"
    assert resolve_upload_relative_path("reports/", "foo.csv") == "reports/foo.csv"
    assert resolve_upload_relative_path("reports/foo.csv", "ignored.csv") == "reports/foo.csv"
    with pytest.raises(SourceFilesError):
        resolve_upload_relative_path("../x", "a.txt")


def test_list_source_rejects_traversal(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    with pytest.raises(SourceFilesError):
        list_source_files(root, "../_library")


def test_resolve_sandbox_rejects_escape(tmp_path: Path) -> None:
    root = agent_workspace_root(tmp_path, "agent-1")
    outside = tmp_path / "_library" / "other"
    outside.mkdir(parents=True)
    (outside / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SandboxPathError):
        resolve_sandbox_path(root, "../_library/other/x.txt")
