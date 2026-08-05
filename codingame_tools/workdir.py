"""Kind-agnostic resolution of a working directory from any file inside it.

   `puzzle_manager.resolver.infer_puzzle_dir` and its contribution twin both answer "which working
   directory does this file belong to", but each requires the caller to already know *which kind* it
   is looking at--which is exactly what an editor integration doesn't know. VS Code hands over
   `${file}`, the path of whichever tab was focused, and nothing more.

   So this resolves both at once: the directory, and whether it is a puzzle or a contribution. One
   `tasks.json` entry and one debug configuration per language can then serve every working
   directory in a workspace, instead of a set regenerated per directory.

   Deliberately more permissive than the two `infer_*` helpers, which insist the file resolve to
   `<root>/data/solution.src` exactly. Any file inside a working directory works here--a test case's
   `input.txt`, `statement.cgmd`, the solution symlink--because "run the tests for whatever I'm
   looking at" is a reasonable thing to ask with a test input open.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .contribution_manager.schema import CONTRIBUTION_IDENTITY_FILE_NAME
from .puzzle_manager.schema import PUZZLE_IDENTITY_FILE_NAME

__all__ = [
    "CgWorkingDir",
    "CgWorkingDirError",
    "CgWorkingDirKind",
    "find_working_dir",
    "resolve_working_dir",
    "working_dir_kind",
]

CgWorkingDirKind = Literal["puzzle", "contribution"]
"""Which of the two working directory layouts a root holds. They share a shape (`data/`, `.meta/`,
   a `solution.<ext>` symlink) and are told apart only by which identity file is present."""

_IDENTITY_FILES: tuple[tuple[str, CgWorkingDirKind], ...] = (
    (PUZZLE_IDENTITY_FILE_NAME, "puzzle"),
    (CONTRIBUTION_IDENTITY_FILE_NAME, "contribution"),
)


class CgWorkingDirError(Exception):
    """Raised by `resolve_working_dir` when a path isn't inside any working directory."""


@dataclass(frozen=True)
class CgWorkingDir:
    """A working directory and which kind it is."""

    root: Path
    """The working directory root (resolved absolute)--the directory holding the identity file."""

    kind: CgWorkingDirKind
    """`"puzzle"` or `"contribution"`."""


def working_dir_kind(root: Path) -> CgWorkingDirKind | None:
    """Which kind of working directory `root` is, or None if it isn't one.

       Checks for the identity file itself rather than for `data/`, so a half-built directory (or
       any directory that merely happens to contain a `data/`) isn't mistaken for one."""
    for file_name, kind in _IDENTITY_FILES:
        if (root / file_name).is_file():
            return kind
    return None


def find_working_dir(target: Path | str) -> CgWorkingDir | None:
    """The working directory containing `target`, or None if there isn't one.

       Searches upward from `target` twice: once from its fully-resolved path, and once from the
       literal path as given. Both are needed, and the order matters:

       - Resolving first handles the case the debugger cares about--a `solution.<ext>` symlink,
         possibly living somewhere else entirely in the workspace, whose real target is inside the
         working directory. Walking up from the symlink's own location would find nothing.
       - Falling back to the literal path handles a working directory reached *through* a symlinked
         parent (a symlinked checkout, say), where resolving would land outside the tree the user
         thinks they're in.

       Nearest match wins, so a working directory nested inside another resolves to the inner one.
    """
    literal = Path(target).expanduser().absolute()
    resolved = literal.resolve()
    for candidate in (resolved, literal):
        for directory in (candidate, *candidate.parents):
            kind = working_dir_kind(directory)
            if kind is not None:
                return CgWorkingDir(root=directory, kind=kind)
    return None


def resolve_working_dir(target: Path | str) -> CgWorkingDir:
    """`find_working_dir`, but raising rather than returning None.

    Raises:
        CgWorkingDirError: if `target` isn't inside a puzzle or contribution working directory.
    """
    found = find_working_dir(target)
    if found is None:
        raise CgWorkingDirError(
                f"{target} is not inside a puzzle or contribution working directory (looked for a "
                f"{PUZZLE_IDENTITY_FILE_NAME} or {CONTRIBUTION_IDENTITY_FILE_NAME} in it and every "
                "parent directory). Open a file inside one, or run `cg puzzle import` / "
                "`cg contribution import` first."
            )
    return found
