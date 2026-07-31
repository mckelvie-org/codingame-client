"""The puzzle working directory's three manifest files--see
   `codingame_tools.puzzle_manager.manager`'s module docstring for the full rationale behind
   the three-way split (git-tracked stable identity vs. gitignored cache vs. git-tracked
   user-editable content):

   - `puzzle.json` (`CgPuzzleIdentity`, at the working directory root): stable identity, never
     changes for the life of the directory, safe to commit.
   - `.meta/puzzle-server-data.json` (`CgPuzzleServerData`): cache, gitignored--lost whenever the
     working directory is committed to git and cloned elsewhere (see
     `codingame_tools.puzzle_manager.layout.META_SUBDIR_NAME`), reconstructed by `repair()`.
   - `data/puzzle-data.json` (`CgPuzzleData`): the one piece of user-editable metadata that
     travels with a solution submission (currently just `solution_language`)--safe to commit,
     alongside `data/solution.src` itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..client.common.protocol.schema import CgSolutionLanguage
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "PUZZLE_IDENTITY_FILE_NAME",
    "PUZZLE_SCHEMA_VERSION",
    "CgPuzzleIdentity",
    "CgPuzzleServerData",
    "CgPuzzleData",
]

PUZZLE_IDENTITY_FILE_NAME = "puzzle.json"
"""Name of the puzzle working directory's identity/manifest file, at its root (a sibling of
   `data/`/`.meta/`)--its presence is what identifies a directory as a puzzle working directory
   at all."""

PUZZLE_SCHEMA_VERSION = 1
"""Current on-disk format version for a puzzle working directory, recorded in
   `CgPuzzleIdentity.schema_version` so a future format change can detect and offer to migrate an
   older working directory."""


@dataclass
class CgPuzzleIdentity(JSONWizardX):
    """The `puzzle.json` manifest: this working directory's stable identity, written once by
       `import_()` and never changed afterward. Deliberately the *only* thing this package
       considers safe to treat as permanent, git-trackable truth about which puzzle this is--see
       the module docstring, and `codingame_tools.puzzle_manager.manager`'s, for why
       `test_session_handle`/`title`/`puzzle_pretty_id` are cache (`.meta/`) instead, not
       identity."""

    schema_version: int
    """The on-disk format version this working directory was written in--see
       `PUZZLE_SCHEMA_VERSION`."""

    puzzle_id: int
    """Numeric ID of the puzzle (`CgTestSessionPuzzle.id`)--the actual repair root key: the only
       confirmed API that can regenerate everything else from scratch,
       `Puzzle/findProgressByIds`, takes this, not `puzzle_handle` (no known API accepts the
       opaque handle as a lookup key) or `puzzle_pretty_id` (not trusted as stable--see
       `CgPuzzleServerData.puzzle_pretty_id`)."""

    puzzle_handle: str
    """Opaque handle for the puzzle (`CgTestSessionPuzzle.handle`). Recorded here as part of this
       working directory's permanent identity even though nothing can look a puzzle up *by* it
       today--`puzzle_id` is what `repair()` actually queries with."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgPuzzleServerData(JSONWizardX):
    """The `.meta/puzzle-server-data.json` manifest: cached, gitignored, re-derivable-from-
       `puzzle_id` server state. Rebuilt by `repair()` whenever missing (e.g. after a fresh clone
       into a different repo, or manual deletion/corruption)."""

    test_session_handle: str
    """This codingamer's test session handle for the puzzle (see
       `CgAsyncPuzzleService.generate_session_from_puzzle_pretty_id`). Freely cached and reused
       indefinitely, unlike `puzzle_pretty_id`/`title` below--confirmed (2026-07-30, per repeated
       identical results from `generateSessionFromPuzzlePrettyId`) to be a per-user singleton with
       affinity to the *puzzle*, not to whichever `pretty_id` happened to be used to generate it;
       there is no known scenario where a cached handle here would need re-verification the way a
       cached `puzzle_pretty_id` does."""

    title: str
    """Display title of the puzzle. Purely informational (e.g. for `cg puzzle where` output)."""

    puzzle_pretty_id: str
    """The puzzle's pretty ID/slug at the time this was last (re)written--**informational only,
       never trusted as ground truth.** Unlike `test_session_handle`, a pretty ID is *not*
       confirmed stable (it plausibly changes if the puzzle's title changes, and even a
       structurally-valid pretty ID string could in principle end up reassigned to a different
       puzzle over time)--so this cached copy is never fed back into an API call (e.g.
       `generateSessionFromPuzzlePrettyId`) by this package. Whenever a pretty ID is actually
       needed operationally (only `repair()` ever needs one, and only if `findProgressByIds`
       didn't already hand back a reusable `test_session_handle` directly), it's re-derived fresh
       from `Puzzle/findProgressByIds(puzzle_id)` and cross-checked against `puzzle_id` first--see
       `CgPuzzleManager.repair`."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgPuzzleData(JSONWizardX):
    """The `data/puzzle-data.json` manifest: the one piece of metadata that genuinely travels
       with a solution submission (alongside `data/solution.src` itself), as opposed to read-only
       puzzle content (statement, stub generator--see `.meta/`) or server-assigned identity/cache.
       Safe to commit to git, same as `solution.src`."""

    solution_language: CgSolutionLanguage
    """The language `data/solution.src` is currently written in--submitted alongside the code on
       `push()`/`play()`, and so genuinely part of the user-managed submission state, not read-only
       reference material or server-derived cache."""

    extra_data: CatchAll = field(default_factory=dict)
