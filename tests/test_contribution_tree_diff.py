"""Unit tests for codingame_client.contribution_manager.tree_diff: the generic 2-way/3-way
   directory-tree comparison and diff/diff3 rendering used by `cg contribution diff`/`rebase`.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
Tests that exercise `render_three_way_diff`'s genuine-conflict path (which shells out to the
system `diff3`) are skipped if `diff3` isn't on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codingame_client.contribution_manager.tree_diff import (
    diff_three_trees,
    diff_two_trees,
    looks_like_text,
    render_three_way_diff,
    render_two_way_diff,
)

requires_diff3 = pytest.mark.skipif(shutil.which("diff3") is None, reason="diff3 not on PATH")


# --- looks_like_text -------------------------------------------------------------------------


def test_looks_like_text_for_plain_text() -> None:
    assert looks_like_text(b"hello\nworld\n") is True


def test_looks_like_text_false_for_null_bytes() -> None:
    assert looks_like_text(b"\x89PNG\x00\x01\x02") is False


# --- diff_two_trees --------------------------------------------------------------------------


def test_diff_two_trees_detects_unchanged_added_removed_modified(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "same.txt").write_text("same\n")
    (b_dir / "same.txt").write_text("same\n")
    (a_dir / "removed.txt").write_text("gone\n")
    (b_dir / "added.txt").write_text("new\n")
    (a_dir / "modified.txt").write_text("old\n")
    (b_dir / "modified.txt").write_text("new\n")

    entries = {e.relative_path: e for e in diff_two_trees(a_dir, b_dir)}

    assert not entries["same.txt"].changed
    assert entries["removed.txt"].changed and entries["removed.txt"].b is None
    assert entries["added.txt"].changed and entries["added.txt"].a is None
    assert entries["modified.txt"].changed


def test_diff_two_trees_missing_directory_treated_as_empty(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    a_dir.mkdir()
    (a_dir / "only-in-a.txt").write_text("x\n")
    b_dir = tmp_path / "does-not-exist"

    entries = diff_two_trees(a_dir, b_dir)

    assert len(entries) == 1
    assert entries[0].relative_path == "only-in-a.txt"
    assert entries[0].b is None


def test_diff_two_trees_excludes_last_committed_subdir(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    (a_dir / "last_committed").mkdir(parents=True)
    (a_dir / "last_committed" / "contribution.json").write_text("{}")
    b_dir.mkdir()

    entries = diff_two_trees(a_dir, b_dir)

    assert entries == []


def test_render_two_way_diff_shows_unified_diff_for_text(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "f.txt").write_text("line1\nline2\n")
    (b_dir / "f.txt").write_text("line1\nchanged\n")

    text = render_two_way_diff(diff_two_trees(a_dir, b_dir), a_label="base", b_label="local")

    assert "-line2" in text
    assert "+changed" in text
    assert "base/f.txt" in text
    assert "local/f.txt" in text


def test_render_two_way_diff_reports_binary_files_differ(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "cover.png").write_bytes(b"\x89PNG\x00old")
    (b_dir / "cover.png").write_bytes(b"\x89PNG\x00new")

    text = render_two_way_diff(diff_two_trees(a_dir, b_dir))

    assert "Binary files" in text
    assert "differ" in text


def test_render_two_way_diff_empty_when_nothing_changed(tmp_path: Path) -> None:
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "f.txt").write_text("same\n")
    (b_dir / "f.txt").write_text("same\n")

    assert render_two_way_diff(diff_two_trees(a_dir, b_dir)) == ""


# --- diff_three_trees / ThreeWayEntry.status --------------------------------------------------


def _write(root: Path, name: str, content: str | None) -> None:
    if content is not None:
        (root / name).write_text(content)


def _make_trees(tmp_path: Path, *, base: str | None, local: str | None, remote: str | None) -> tuple[Path, Path, Path]:
    base_dir, local_dir, remote_dir = tmp_path / "base", tmp_path / "local", tmp_path / "remote"
    for d in (base_dir, local_dir, remote_dir):
        d.mkdir()
    _write(base_dir, "f.txt", base)
    _write(local_dir, "f.txt", local)
    _write(remote_dir, "f.txt", remote)
    return base_dir, local_dir, remote_dir


def test_status_unchanged(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="x\n", remote="x\n")
    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "unchanged"


def test_status_local_changed(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="y\n", remote="x\n")
    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "local_changed"


def test_status_remote_changed(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="x\n", remote="y\n")
    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "remote_changed"


def test_status_both_changed_same(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="y\n", remote="y\n")
    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "both_changed_same"


def test_status_conflict(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="y\n", remote="z\n")
    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "conflict"


def test_render_three_way_diff_omits_unchanged(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="x\n", remote="x\n")
    text = render_three_way_diff(diff_three_trees(base_dir, local_dir, remote_dir), base_dir, local_dir, remote_dir)
    assert text == ""


def test_render_three_way_diff_shows_remote_changed_as_two_way(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="x\n", remote="y\n")
    text = render_three_way_diff(diff_three_trees(base_dir, local_dir, remote_dir), base_dir, local_dir, remote_dir)
    assert "f.txt (remote_changed)" in text
    assert "-x" in text
    assert "+y" in text


@requires_diff3
def test_render_three_way_diff_uses_diff3_for_genuine_conflict(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = _make_trees(tmp_path, base="x\n", local="y\n", remote="z\n")
    text = render_three_way_diff(diff_three_trees(base_dir, local_dir, remote_dir), base_dir, local_dir, remote_dir)
    assert "f.txt (conflict)" in text
    assert "<<<<<<<" in text
    assert "=======" in text
    assert ">>>>>>>" in text


@requires_diff3
def test_render_three_way_diff_conflict_binary_falls_back_to_note(tmp_path: Path) -> None:
    base_dir, local_dir, remote_dir = tmp_path / "base", tmp_path / "local", tmp_path / "remote"
    for d in (base_dir, local_dir, remote_dir):
        d.mkdir()
    (base_dir / "cover.png").write_bytes(b"\x89PNG\x00base")
    (local_dir / "cover.png").write_bytes(b"\x89PNG\x00local")
    (remote_dir / "cover.png").write_bytes(b"\x89PNG\x00remote")

    entries = diff_three_trees(base_dir, local_dir, remote_dir)
    assert entries[0].status == "conflict"
    text = render_three_way_diff(entries, base_dir, local_dir, remote_dir)
    assert "cannot auto-render" in text
