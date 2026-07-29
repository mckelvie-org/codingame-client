"""Generic 2-way/3-way directory-tree comparison, used to detect and render drift between a
   contribution working directory's local content, its cached base (`last_committed/`), and the
   current server state--all as plain materialized directories on disk (see
   `codingame_client.contribution_manager.manager`'s `materialize_base`/`materialize_remote`), so
   this module itself has no client/network dependency at all.

   Content is compared purely as raw bytes--no test-case-aware or field-aware logic. This is
   deliberate: it's fine (expected, even) for this to report a difference where semantically there
   isn't one (e.g. `import_test_cases`'s ordinal directory naming producing a different-but-
   equivalent layout)--simplicity was explicitly preferred here over precision.
"""

from __future__ import annotations

import contextlib
import difflib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .last_committed import LAST_COMMITTED_SUBDIR_NAME

__all__ = [
    "TwoWayEntry",
    "ThreeWayEntry",
    "diff_two_trees",
    "diff_three_trees",
    "looks_like_text",
    "render_two_way_diff",
    "render_three_way_diff",
]


def _read_file_map(root: Path) -> dict[str, bytes]:
    """relative POSIX path -> content, for every regular file under `root`, excluding
       `last_committed/` itself--working-directory bookkeeping, never meaningful to diff (and
       ephemeral base/remote trees never contain one in the first place)."""
    result: dict[str, bytes] = {}
    if not root.is_dir():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == LAST_COMMITTED_SUBDIR_NAME:
            continue
        result[rel.as_posix()] = path.read_bytes()
    return result


@dataclass(frozen=True)
class TwoWayEntry:
    """One relative path's content in each of two directory trees (`None` if absent)."""

    relative_path: str
    a: bytes | None
    b: bytes | None

    @property
    def changed(self) -> bool:
        return self.a != self.b


def diff_two_trees(a_dir: Path, b_dir: Path) -> list[TwoWayEntry]:
    """Compare every file under `a_dir` and `b_dir` (union of relative paths, sorted), reading
       full file content into memory (contribution working directories are small enough that this
       is simpler and fast enough, rather than hashing first)."""
    a_map = _read_file_map(a_dir)
    b_map = _read_file_map(b_dir)
    paths = sorted(set(a_map) | set(b_map))
    return [TwoWayEntry(p, a_map.get(p), b_map.get(p)) for p in paths]


@dataclass(frozen=True)
class ThreeWayEntry:
    """One relative path's content in each of three directory trees (`None` if absent)."""

    relative_path: str
    base: bytes | None
    local: bytes | None
    remote: bytes | None

    @property
    def status(self) -> str:
        """One of "unchanged", "local_changed" (local differs, remote matches base),
           "remote_changed" (remote differs, local matches base), "both_changed_same" (both
           differ from base, but ended up identical to each other--no real conflict), or
           "conflict" (both differ from base, and from each other)."""
        eq_base_local = self.base == self.local
        eq_base_remote = self.base == self.remote
        if eq_base_local and eq_base_remote:
            return "unchanged"
        if eq_base_local and not eq_base_remote:
            return "remote_changed"
        if not eq_base_local and eq_base_remote:
            return "local_changed"
        if self.local == self.remote:
            return "both_changed_same"
        return "conflict"


def diff_three_trees(base_dir: Path, local_dir: Path, remote_dir: Path) -> list[ThreeWayEntry]:
    """Like `diff_two_trees`, but across three directory trees at once."""
    base_map = _read_file_map(base_dir)
    local_map = _read_file_map(local_dir)
    remote_map = _read_file_map(remote_dir)
    paths = sorted(set(base_map) | set(local_map) | set(remote_map))
    return [ThreeWayEntry(p, base_map.get(p), local_map.get(p), remote_map.get(p)) for p in paths]


def looks_like_text(content: bytes) -> bool:
    """Heuristic (the same one git and most other tools use): binary content almost always
       contains a NUL byte within the first few KB; text content essentially never does."""
    return b"\x00" not in content[:8192]


def _decode(content: bytes) -> list[str]:
    return content.decode("utf-8", errors="replace").splitlines(keepends=True)


def render_two_way_diff(entries: list[TwoWayEntry], *, a_label: str = "base", b_label: str = "local") -> str:
    """Render a unified-diff-style summary of every changed entry. Unchanged entries are omitted
       entirely; added/removed paths get a one-line note; binary changes get a one-line note;
       text changes get a real unified diff via `difflib`."""
    parts: list[str] = []
    for entry in entries:
        if not entry.changed:
            continue
        if entry.a is None:
            parts.append(f"+++ added ({b_label}): {entry.relative_path}\n")
        elif entry.b is None:
            parts.append(f"--- removed ({b_label}): {entry.relative_path}\n")
        elif not (looks_like_text(entry.a) and looks_like_text(entry.b)):
            parts.append(f"Binary files {a_label}/{entry.relative_path} and {b_label}/{entry.relative_path} differ\n")
        else:
            diff = difflib.unified_diff(
                    _decode(entry.a), _decode(entry.b),
                    fromfile=f"{a_label}/{entry.relative_path}", tofile=f"{b_label}/{entry.relative_path}",
                )
            parts.append("".join(diff))
    return "".join(parts)


def _run_diff3(local_path: Path, base_path: Path, remote_path: Path) -> str:
    """Run the system `diff3 -m` (merge mode--conflict-marker output, `<<<<<<<`/`|||||||`/
       `=======`/`>>>>>>>`) on the three given paths, substituting an empty temp file for any that
       don't exist (an add/remove tangled up in a genuine conflict).

       Requires `diff3` on PATH--part of standard diffutils, present by default on macOS and
       Linux; not attempted/verified on other platforms.

    Raises:
        FileNotFoundError: if `diff3` isn't on PATH.
    """
    if shutil.which("diff3") is None:
        raise FileNotFoundError("`diff3` not found on PATH (part of diffutils on Linux, or the BSD base tools on macOS).")
    with contextlib.ExitStack() as stack:
        def resolve(path: Path) -> str:
            if path.is_file():
                return str(path)
            empty = stack.enter_context(tempfile.NamedTemporaryFile(mode="w", suffix=".empty"))
            return empty.name
        args = ["diff3", "-m", resolve(local_path), resolve(base_path), resolve(remote_path)]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        # diff3 exit codes: 0 = no conflicts found, 1 = conflicts found (expected/normal here), 2 = trouble.
        if result.returncode not in (0, 1):
            return f"diff3 failed (exit {result.returncode}): {result.stderr.strip()}\n"
        return result.stdout


def render_three_way_diff(
            entries: list[ThreeWayEntry], base_dir: Path, local_dir: Path, remote_dir: Path,
        ) -> str:
    """Render a per-path summary of every non-unchanged entry: a plain unified diff against base
       for "local_changed"/"remote_changed"/"both_changed_same" entries, and a real diff3-style
       merge (conflict markers) for genuine "conflict" entries--using the system `diff3`, or a
       one-line fallback note if a conflicted entry is binary or `diff3` isn't available.
    """
    parts: list[str] = []
    for entry in entries:
        status = entry.status
        if status == "unchanged":
            continue
        parts.append(f"=== {entry.relative_path} ({status}) ===\n")
        if status == "remote_changed":
            two_way = TwoWayEntry(entry.relative_path, entry.base, entry.remote)
            parts.append(render_two_way_diff([two_way], a_label="base", b_label="remote"))
        elif status in ("local_changed", "both_changed_same"):
            two_way = TwoWayEntry(entry.relative_path, entry.base, entry.local)
            parts.append(render_two_way_diff([two_way], a_label="base", b_label="local"))
        else:  # conflict
            all_text = all(
                    c is None or looks_like_text(c) for c in (entry.base, entry.local, entry.remote)
                )
            if not all_text:
                parts.append("Binary and conflicting on both sides--cannot auto-render; compare the files directly.\n")
                continue
            try:
                parts.append(_run_diff3(
                        local_dir / entry.relative_path, base_dir / entry.relative_path, remote_dir / entry.relative_path))
            except FileNotFoundError as e:
                parts.append(f"{e} Falling back to separate diffs:\n")
                local_entry = TwoWayEntry(entry.relative_path, entry.base, entry.local)
                remote_entry = TwoWayEntry(entry.relative_path, entry.base, entry.remote)
                parts.append(render_two_way_diff([local_entry], a_label="base", b_label="local"))
                parts.append(render_two_way_diff([remote_entry], a_label="base", b_label="remote"))
    return "".join(parts)
