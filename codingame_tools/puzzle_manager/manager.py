"""`CgPuzzleManager`: builds a puzzle working directory from an existing server-side puzzle
   (`import_`), runs the working directory's current solution against a single test case
   (`play`), submits it for credit (`submit`), and reconstructs cached/reference state that was
   deliberately never committed to git (`repair`).

   Deliberately much simpler than `codingame_tools.contribution_manager`: exactly one file is
   ever editable--`data/solution.src`--so there is no git repository backing this working
   directory, no branches, no multi-file merge machinery. "Merge reconciliation" here is just a
   two-way choice between the local file and the server's last-submitted version:

   - `diff()` shows a unified text diff between them.
   - `discard_local()` overwrites the local file with the server's version.
   - `submit()` overwrites the server's version with the local file (a normal `TestSession/submit`).
     Note `play()` *also* durably updates the server's copy of the code as a side effect (see its
     docstring)--unlike a contribution, a puzzle working directory has two independent
     server-side persistence phases (the test session's current answer, and a graded
     submission), not one; `submit()` is named for CodinGame's own vocabulary (matching the
     underlying `TestSession/submit` API method) rather than `push()`'s git vocabulary, precisely
     to avoid implying it's the only thing that persists anything server-side.

   There is no third "merge tool" option in this first cut--flagged as a possible follow-up, not
   built, since a single-file external diff/merge tool is easy to add later if actually wanted.

   Unlike a contribution, nothing here is ever newly *created*: a puzzle already exists on the
   server before you can solve it, so `import_()` is the only way a working directory comes into
   being, and `CgPuzzleIdentity` has no `create()`-then-later-linked state to track.

   **Three-way state split (see `codingame_tools.puzzle_manager.schema`/`.layout` for the exact
   files), and why:** a puzzle working directory is expected to be put under the user's own git
   (unlike a contribution working directory, which has its *own*, separate, internal git repo).
   That means anything not explicitly committed is lost the moment the directory is cloned into a
   different repo/machine--so state here is split by how it behaves under that constraint:

   - `puzzle.json` (`CgPuzzleIdentity`, root): the *only* facts treated as permanent identity,
     safe to commit--`puzzle_id` and `puzzle_handle`. Deliberately minimal: `puzzle_id` is the
     real repair root key (the only confirmed API that can regenerate everything else,
     `Puzzle/findProgressByIds`, takes a numeric ID, not a pretty ID or the opaque handle).
   - `.meta/` (`CgPuzzleServerData` + read-only `statement.html`/`stub_generator.cgstub`/`tests/`):
     gitignored cache, reconstructed by `repair()` whenever missing. `test_session_handle` is
     cached and reused freely (confirmed stable, with affinity to the *puzzle*, not to whichever
     pretty ID happened to generate it). `title`/`puzzle_pretty_id` are cached too, but purely for
     display--never trusted as ground truth or fed back into an API call, since (unlike the
     handle) a pretty ID isn't confirmed stable across e.g. a puzzle title change. See
     `CgPuzzleServerData`'s own docstring. `tests/` (see
     `codingame_tools.puzzle_manager.test_cases_dir`) holds each test case's downloaded
     input/output, one directory per server-assigned test index--reference material for running
     the solution locally (e.g. in a debugger), not something this package interprets itself.
   - `data/puzzle-data.json` (`CgPuzzleData`) + `data/solution.src`: genuinely user-managed,
     git-trackable content--the solution itself, and the one piece of metadata that travels with
     a submission (`solution_language`).
"""

from __future__ import annotations

import dataclasses
import difflib
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..client.client import CgClient
from ..client.common.protocol.last_activities import CgLastActivityPuzzle
from ..client.common.protocol.report import CgSubmissionReport
from ..client.common.protocol.schema import CgSolutionLanguage, cg_solution_language_to_extension
from ..client.common.protocol.test_session import (
    CgMultipleLanguagesTestParams,
    CgPlayRequest,
    CgPlayResult,
    CgSubmitRequest,
)
from ..client.common.raw_client import CgClientHttpError
from ..test_runner import DEFAULT_RUN_TIMEOUT_SECONDS, outputs_match, run_solution_locally
from .layout import (
    DATA_SUBDIR_NAME,
    GITIGNORE_FILE_NAME,
    META_SUBDIR_NAME,
    SOLUTION_FILE_NAME,
    STATEMENT_FILE_NAME,
    STUB_GENERATOR_FILE_NAME,
)
from .schema import (
    PUZZLE_IDENTITY_FILE_NAME,
    PUZZLE_SCHEMA_VERSION,
    CgPuzzleData,
    CgPuzzleIdentity,
    CgPuzzleServerData,
)
from .test_cases_dir import TESTS_SUBDIR_NAME, download_test_cases, list_downloaded_test_cases

__all__ = [
    "DATA_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "SOLUTION_FILE_NAME",
    "STATEMENT_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "TESTS_SUBDIR_NAME",
    "CgPuzzleManagerError",
    "CgPuzzleDiscardResult",
    "CgPuzzleLocalTestResult",
    "CgPuzzleLocalTestFailedError",
    "CgPuzzleRemoteTestResult",
    "CgPuzzleStatus",
    "CgPuzzleManager",
]

_SUPPORTED_CONTRIBUTION_TYPE = "PUZZLE_INOUT"

_PUZZLE_DATA_FILE_NAME = "puzzle-data.json"
_PUZZLE_SERVER_DATA_FILE_NAME = "puzzle-server-data.json"


class CgPuzzleManagerError(Exception):
    """Raised for puzzle-manager-level errors not better represented by a more specific
       exception (e.g. importing an unsupported puzzle type, discarding local edits when nothing
       has ever been submitted to discard to, or a `repair()` whose fresh lookup didn't actually
       match the puzzle it was supposed to repair)."""


@dataclass(frozen=True)
class CgPuzzleDiscardResult:
    """The outcome of `CgPuzzleManager.discard_local()`."""

    code: str
    """The server's last-submitted code, now also written to `data/solution.src`."""

    solution_language: CgSolutionLanguage
    """The language `code` is written in (the server's last submission may be in a different
       language than `data/puzzle-data.json`'s previously-recorded `solution_language`--this is
       the fresh, now-authoritative value; `discard_local()` updates `puzzle-data.json` to
       match)."""


@dataclass(frozen=True)
class CgPuzzleLocalTestResult:
    """The outcome of running `data/solution.src` against one downloaded `.meta/tests/` test
       case--see `CgPuzzleManager.play_local`."""

    index: int
    """The test case's server-assigned index (see `CgPuzzleDownloadedTestCase.index`)."""

    label: str
    """The test case's real label."""

    passed: bool
    """Whether the run completed without crashing/timing out and its stdout matched the test
       case's expected output (see `codingame_tools.test_runner.outputs_match`)."""

    input: str
    """The test case's input, exactly as fed to the solution's stdin."""

    expected_output: str
    """The test case's expected output (`output.txt`)."""

    actual_output: str
    """What the solution actually wrote to stdout."""

    stderr: str
    """What the solution wrote to stderr (not itself a failure condition, but useful context when
       a test does fail)."""

    timed_out: bool
    """Whether the run was killed for exceeding its timeout rather than running to completion."""


@dataclass(frozen=True)
class CgPuzzleRemoteTestResult:
    """The outcome of playing one of a puzzle's test cases against the server
       (`TestSession/play`)--see `CgPuzzleManager.play`."""

    index: int
    """The test case's 1-based index (see `CgTestSessionTestCase.index`)."""

    label: str
    """The test case's real label, from `.meta/tests/<index>/` if it's been downloaded--a
       generic `f"test {index}"` placeholder otherwise (`play()` doesn't require an index to be
       locally downloaded; the server doesn't need that to run it)."""

    result: CgPlayResult
    """The raw `TestSession/play` response for this test case."""


class CgPuzzleLocalTestFailedError(CgPuzzleManagerError):
    """Raised by `CgPuzzleManager.play_local` if any test case failed. Carries every result (not
       just the failing ones) via `.results`, so a caller can report the full picture."""

    def __init__(self, results: list[CgPuzzleLocalTestResult]) -> None:
        self.results = results
        failed = [r for r in results if not r.passed]
        summary = ", ".join(f"#{r.index} ({r.label})" for r in failed)
        super().__init__(f"{len(failed)}/{len(results)} local test case(s) failed: {summary}")


@dataclass(frozen=True)
class CgPuzzleStatus:
    """A point-in-time summary of a puzzle working directory--see `CgPuzzleManager.status()`.
       Much simpler than `codingame_tools.contribution_manager.CgContributionStatus`--no
       versioning, no draft/moderation gate, no sync-state machine--matching this whole package's
       "much simpler than contribution_manager" design (see the module docstring)."""

    puzzle_dir: Path
    """The working directory this status describes."""

    puzzle_id: int
    """Numeric ID of the puzzle (`CgPuzzleIdentity.puzzle_id`)."""

    puzzle_handle: str
    """Opaque handle for the puzzle (`CgPuzzleIdentity.puzzle_handle`)."""

    title: str
    """`.meta/puzzle-server-data.json`'s cached title--informational only, may be stale (see
       `CgPuzzleServerData.title`'s docstring)."""

    puzzle_pretty_id: str
    """`.meta/puzzle-server-data.json`'s cached pretty ID/slug--informational only, may be stale
       (see `CgPuzzleServerData.puzzle_pretty_id`'s docstring--never trusted as ground truth by
       this package itself either)."""

    puzzle_type: str | None
    """`.meta/puzzle-server-data.json`'s cached contribution type (e.g. "PUZZLE_INOUT"), or
       `None` for a cache file written before this field existed (see `CgPuzzleServerData.
       puzzle_type`)--run `cg puzzle repair` (after deleting `.meta/`) to populate it."""

    difficulty: str | None
    """`.meta/puzzle-server-data.json`'s cached difficulty level (e.g. "easy"), or `None` for a
       cache file written before this field existed (see `CgPuzzleServerData.difficulty`)--same
       backfill note as `puzzle_type`."""

    solution_language: CgSolutionLanguage
    """`data/puzzle-data.json`'s `solution_language`--the language `data/solution.src` is
       currently written in."""

    local_dirty: bool | None
    """Whether `data/solution.src` currently differs from the server's last-submitted answer for
       this puzzle (`bool(diff())`)--`None` unless `status(refresh=True)` checked (a live
       `TestSession/startTestSession` call; there is no local cache of the server's answer to
       compare against, unlike `codingame_tools.contribution_manager`)."""

    progress: CgLastActivityPuzzle | None
    """This codingamer's live progress/score summary for the puzzle (`Puzzle/findProgressByIds`--
       `level`/`validator_score`/`solved_count`/`attempt_count`/`xp_points`/`last_activity`), or
       `None` unless `status(refresh=True)` fetched it."""


def _refresh_solution_symlink(puzzle_dir: Path, solution_language: str | None) -> None:
    """Remove any existing `solution.<ext>` convenience symlink at `puzzle_dir`'s root, then
       recreate one pointing at `data/solution.src` if `solution_language` maps to a known
       extension. Never touches `solution.src` itself. Same logic as
       `contribution_manager.manager._refresh_solution_symlink` (kept as an independent copy--see
       this module's docstring for why the two packages aren't cross-coupled)."""
    for path in puzzle_dir.glob("solution.*"):
        if path.is_symlink() and path.name != SOLUTION_FILE_NAME:
            path.unlink()
    extension = cg_solution_language_to_extension(solution_language) if solution_language else None
    if extension is None:
        return
    link_name = f"solution.{extension}"
    if link_name == SOLUTION_FILE_NAME:
        return
    (puzzle_dir / link_name).symlink_to(f"{DATA_SUBDIR_NAME}/{SOLUTION_FILE_NAME}")


def _write_meta_gitignore(puzzle_dir: Path) -> None:
    """Write `puzzle_dir/.gitignore` containing `.meta/`, so `.meta/`'s contents (gitignored
       cache--see the module docstring) can never end up tracked by whatever project comes to
       track the rest of `puzzle_dir`, now or later."""
    (puzzle_dir / GITIGNORE_FILE_NAME).write_text(f"{META_SUBDIR_NAME}/\n")


class CgPuzzleManager:
    """Builds/updates a puzzle working directory (`puzzle_dir`) against the server, via an
       already-authenticated `CgClient`. See the module docstring for the (deliberately much
       simpler than `codingame_tools.contribution_manager`) design this is backed by."""

    puzzle_dir: Path
    client: CgClient

    def __init__(self, puzzle_dir: Path | str, client: CgClient) -> None:
        self.puzzle_dir = Path(puzzle_dir).resolve()
        self.client = client

    # --- paths -------------------------------------------------------------------------------

    @property
    def identity_file(self) -> Path:
        """Path to this working directory's `puzzle.json` (stable identity) manifest."""
        return self.puzzle_dir / PUZZLE_IDENTITY_FILE_NAME

    @property
    def meta_dir(self) -> Path:
        return self.puzzle_dir / META_SUBDIR_NAME

    @property
    def server_data_file(self) -> Path:
        """Path to this working directory's `.meta/puzzle-server-data.json` (gitignored cache)."""
        return self.meta_dir / _PUZZLE_SERVER_DATA_FILE_NAME

    @property
    def tests_dir(self) -> Path:
        """Path to this working directory's `.meta/tests/` (downloaded test case input/output--see
           `codingame_tools.puzzle_manager.test_cases_dir`)."""
        return self.meta_dir / TESTS_SUBDIR_NAME

    @property
    def data_dir(self) -> Path:
        """Path to this working directory's `data/` subdirectory."""
        return self.puzzle_dir / DATA_SUBDIR_NAME

    @property
    def solution_file(self) -> Path:
        return self.data_dir / SOLUTION_FILE_NAME

    @property
    def puzzle_data_file(self) -> Path:
        """Path to this working directory's `data/puzzle-data.json` (user-editable metadata)."""
        return self.data_dir / _PUZZLE_DATA_FILE_NAME

    @property
    def statement_file(self) -> Path:
        """Path to this working directory's `.meta/statement.html` (read-only reference copy of
           the puzzle's rendered problem statement)."""
        return self.meta_dir / STATEMENT_FILE_NAME

    # --- identity / server-data / puzzle-data load ----------------------------------------------

    def load_identity(self) -> CgPuzzleIdentity | None:
        """Load `puzzle.json`, or None if this directory has never been imported."""
        if not self.identity_file.is_file():
            return None
        return CgPuzzleIdentity.load(self.identity_file)

    def load_statement_html(self) -> str | None:
        """Read `.meta/statement.html`, or None if it doesn't exist (never imported, or `.meta/`
           needs `repair()`)."""
        if not self.statement_file.is_file():
            return None
        return self.statement_file.read_text(encoding="utf-8")

    def load_server_data(self) -> CgPuzzleServerData | None:
        """Load `.meta/puzzle-server-data.json`, or None if it's missing (needs `repair()`--e.g.
           a fresh clone that (correctly) didn't bring gitignored `.meta/` along)."""
        if not self.server_data_file.is_file():
            return None
        return CgPuzzleServerData.load(self.server_data_file)

    def load_puzzle_data(self) -> CgPuzzleData | None:
        """Load `data/puzzle-data.json`, or None if this directory has never been imported."""
        if not self.puzzle_data_file.is_file():
            return None
        return CgPuzzleData.load(self.puzzle_data_file)

    def _require_state(self) -> tuple[CgPuzzleIdentity, CgPuzzleServerData, CgPuzzleData]:
        """All three manifests, for operations that need the full picture (`diff`/
           `discard_local`/`submit`/`play`).

        Raises:
            FileNotFoundError: if this working directory has never been imported at all.
            CgPuzzleManagerError: if `.meta/` is missing (needs `repair()`).
        """
        identity = self.load_identity()
        if identity is None:
            raise FileNotFoundError(
                    f"{self.identity_file} does not exist--this working directory has never "
                    "been imported (see `cg puzzle import`)."
                )
        server_data = self.load_server_data()
        if server_data is None:
            raise CgPuzzleManagerError(
                    f"{self.server_data_file} does not exist (likely gitignored and not carried "
                    "along by a fresh clone)--run `cg puzzle repair` first."
                )
        puzzle_data = self.load_puzzle_data()
        if puzzle_data is None:
            raise FileNotFoundError(f"{self.puzzle_data_file} does not exist--this working directory is in an inconsistent state.")
        return identity, server_data, puzzle_data

    def load_solution(self) -> str:
        """Read `data/solution.src`.

        Raises:
            FileNotFoundError: if `solution.src` doesn't exist.
        """
        return self.solution_file.read_text(encoding="utf-8")

    # --- puzzle reference resolution -------------------------------------------------------

    async def _resolve_puzzle_ref(self, puzzle_ref: str) -> str:
        """Resolve a general puzzle reference to a real pretty ID, trying each of four
           strategies in order and returning the first that matches:

           1. A numeric puzzle ID (e.g. "10075")--looked up via `Puzzle/findProgressByIds`. If
              `puzzle_ref` parses as an integer but doesn't match a real puzzle, this raises
              immediately rather than falling through to the remaining strategies--a bare number
              is almost certainly meant as an ID, and searching for a puzzle literally *titled*
              that number would just produce a more confusing error.
           2. Already a valid pretty ID (e.g. "literary-alfabet-soupe")--validated (and,
              incidentally, resolved to the server's own canonical copy) via
              `Puzzle/findProgressByPrettyId`. Confirmed live: an unrecognized pretty ID responds
              200 with a JSON `null` body, which `service_request_to_dict` rejects with a
              `CgClientHttpError` ("expected a JSON dictionary, got NoneType")--that specific
              case (and only that case, identified by `status_code == 200`) is treated as "not a
              valid pretty ID," not a real error, and falls through to the next strategy.
           3. An exact-matching puzzle title (e.g. "Literary Alfabet Soupe")--via `Search/search`
              (`type_filter="PUZZLE"`). Confirmed live: for `type == "PUZZLE"`, `CgSearchResult.
              id` *is* the pretty ID directly (not a numeric ID, despite that field's own
              docstring's general claim for "other types"--puzzles are the documented exception).
           4. A case-insensitive-matching puzzle title, from that same search result set.

        Raises:
            CgPuzzleManagerError: if `puzzle_ref` parses as an integer with no matching puzzle,
                                   or if none of the four strategies resolve to a real puzzle.
        """
        stripped = puzzle_ref.strip()
        if stripped.isdigit():
            puzzle_id = int(stripped)
            progress_results = await self.client.services.puzzle.find_progress_by_ids([puzzle_id])
            match = next((p for p in progress_results if p.id == puzzle_id), None)
            if match is not None:
                return match.pretty_id
            raise CgPuzzleManagerError(f"No puzzle found with numeric ID {puzzle_id}.")

        try:
            progress = await self.client.services.puzzle.find_progress_by_pretty_id(puzzle_ref)
            return progress.pretty_id
        except CgClientHttpError as e:
            if e.status_code != 200:
                raise

        search_results = await self.client.services.search.search(puzzle_ref, type_filter="PUZZLE")
        exact = next((r for r in search_results if r.name == puzzle_ref), None)
        if exact is not None:
            return exact.id
        lowered = puzzle_ref.lower()
        case_insensitive = next((r for r in search_results if r.name.lower() == lowered), None)
        if case_insensitive is not None:
            return case_insensitive.id

        raise CgPuzzleManagerError(
                f"Could not resolve {puzzle_ref!r} to a puzzle (tried: numeric ID, pretty ID, "
                "exact title match, case-insensitive title match)."
            )

    # --- import_ -------------------------------------------------------------------------------

    async def import_(
                self,
                puzzle_ref: str,
                *,
                language: CgSolutionLanguage = "Python3",
            ) -> CgPuzzleData:
        """Build this working directory from an existing puzzle: resolves `puzzle_ref` to a real
           pretty ID (see `_resolve_puzzle_ref`--a numeric ID, a pretty ID, an exact title match,
           or a case-insensitive title match, tried in that order), then resolves this
           codingamer's test session for it (`Puzzle/generateSessionFromPuzzlePrettyId`), then
           `TestSession/startTestSession` to fetch its current state.

           Writes `data/solution.src` from the codingamer's existing saved answer if there is one
           (`CgTestSessionQuestion.answer`--i.e. this puzzle has been attempted/submitted before),
           in whatever language that answer was written in (`language` is ignored in that case).
           Otherwise (never attempted before), writes a minimal placeholder comment in `language`
           instead--this package does not interpret the puzzle's stub-generator DSL to produce a
           real starter solution the way an IDE would; `.meta/stub_generator.cgstub` (see below)
           is written as a read-only reference instead, for the solver to consult by hand.

           Also writes `.meta/statement.html`, `.meta/stub_generator.cgstub`, and `.meta/tests/`
           (each test case's downloaded input/output--see
           `codingame_tools.puzzle_manager.test_cases_dir`)--all read-only reference copies,
           regenerated here, never read back or diffed--and refreshes the `solution.<ext>`
           convenience symlink at the working directory root--see the module docstring for why
           these live under `.meta/` rather than `data/`.

        Args:
            puzzle_ref: A general puzzle reference--numeric ID, pretty ID, exact title, or
                        case-insensitive title (see `_resolve_puzzle_ref`).
            language:   Language for the placeholder starter `solution.src`, if this puzzle has
                        no existing answer to import instead. Defaults to "Python3". Ignored if
                        an existing answer is found.

        Raises:
            CgPuzzleManagerError: if this directory already tracks a puzzle, if `puzzle_ref`
                                   couldn't be resolved to a real puzzle, or if the puzzle isn't a
                                   supported type (currently, only classic "PUZZLE_INOUT"
                                   puzzles).
        """
        if self.load_identity() is not None:
            raise CgPuzzleManagerError(
                    f"{self.identity_file} already exists--this working directory has already "
                    "been imported."
                )

        puzzle_pretty_id = await self._resolve_puzzle_ref(puzzle_ref)
        test_session_handle = await self.client.services.puzzle.generate_session_from_puzzle_pretty_id(
                puzzle_pretty_id)
        session = await self.client.services.test_session.start_test_session(test_session_handle)
        question = session.current_question.question
        contribution_type = question.contribution.contribution_type
        if contribution_type != _SUPPORTED_CONTRIBUTION_TYPE:
            raise CgPuzzleManagerError(
                    f"Puzzle {puzzle_pretty_id!r} is a {contribution_type!r} puzzle--only "
                    f"{_SUPPORTED_CONTRIBUTION_TYPE!r} puzzles are supported so far."
                )

        answer = session.current_question.answer
        # `answer` itself can be non-None (an empty placeholder object) even with no solution
        # ever submitted--`code`/`programming_language_id` are the actual "has a real answer"
        # signal; see CgTestSessionAnswer's docstring.
        if answer is not None and answer.code is not None and answer.programming_language_id is not None:
            solution_language = answer.programming_language_id
            solution_code = answer.code
        else:
            solution_language = language
            solution_code = f"# TODO: solve {question.title!r} ({puzzle_pretty_id})\n"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.solution_file.write_text(solution_code, encoding="utf-8")
        (self.meta_dir / STATEMENT_FILE_NAME).write_text(question.statement, encoding="utf-8")
        (self.meta_dir / STUB_GENERATOR_FILE_NAME).write_text(f"{question.stub_generator}\n", encoding="utf-8")
        await download_test_cases(self.client, question.test_cases, self.tests_dir)
        _write_meta_gitignore(self.puzzle_dir)

        CgPuzzleIdentity(
                schema_version=PUZZLE_SCHEMA_VERSION, puzzle_id=session.puzzle.id,
                puzzle_handle=session.puzzle.handle,
            ).save(self.identity_file)
        CgPuzzleServerData(
                test_session_handle=test_session_handle, title=question.title,
                puzzle_pretty_id=puzzle_pretty_id, puzzle_type=contribution_type,
                difficulty=session.puzzle.level,
            ).save(self.server_data_file)
        puzzle_data = CgPuzzleData(solution_language=solution_language)
        puzzle_data.save(self.puzzle_data_file)

        _refresh_solution_symlink(self.puzzle_dir, solution_language)
        return puzzle_data

    # --- repair ----------------------------------------------------------------------------------

    async def repair(self) -> CgPuzzleServerData:
        """Reconstruct `.meta/` (the test session handle, plus the read-only `statement.html`/
           `stub_generator.cgstub`/`tests/` reference copies) from `puzzle.json`'s stable
           `puzzle_id`--for recovering from `.meta/` being missing, e.g. after a fresh clone into
           a different repo (it's gitignored on purpose--see the module docstring) or manual
           deletion/corruption. `data/` (`solution.src`, `puzzle-data.json`) is never touched--
           there's nothing to preserve *from*, since it's exactly the git-tracked content a clone
           would have brought along.

           Looks up `Puzzle/findProgressByIds([puzzle_id])` for a fresh `pretty_id`/`title`, and
           (if already available there) a reusable `test_session_handle` directly--otherwise
           falls back to `Puzzle/generateSessionFromPuzzlePrettyId` using that fresh `pretty_id`.
           Either way, cross-checks the resulting session's own reported puzzle ID against
           `puzzle_id` before trusting anything else about it (see `CgPuzzleServerData`'s
           docstring for why a looked-up `pretty_id` specifically is never trusted un-verified).

        Raises:
            FileNotFoundError: if this working directory has never been imported (no
                                `puzzle.json`), or `data/solution.src` itself is missing (nothing
                                on disk to refresh the solution symlink for/repair alongside).
            CgPuzzleManagerError: if `.meta/` already exists (nothing to repair), or if a fresh
                                   lookup's own reported puzzle ID doesn't match `puzzle_id`
                                   (refuses rather than risk repairing with mismatched data).
        """
        identity = self.load_identity()
        if identity is None:
            raise FileNotFoundError(
                    f"{self.identity_file} does not exist--this working directory has never "
                    "been imported (nothing to repair)."
                )
        if self.server_data_file.is_file():
            raise CgPuzzleManagerError(f"{self.server_data_file} already exists--nothing to repair.")
        if not self.solution_file.is_file():
            raise FileNotFoundError(f"{self.solution_file} does not exist--nothing on disk to repair alongside.")

        progress_results = await self.client.services.puzzle.find_progress_by_ids([identity.puzzle_id])
        if not progress_results or progress_results[0].id != identity.puzzle_id:
            raise CgPuzzleManagerError(
                    f"Puzzle/findProgressByIds([{identity.puzzle_id}]) did not return a matching "
                    "result--refusing to repair with mismatched data."
                )
        progress = progress_results[0]

        test_session_handle = progress.test_session_handle
        if test_session_handle is None:
            test_session_handle = await self.client.services.puzzle.generate_session_from_puzzle_pretty_id(
                    progress.pretty_id)

        session = await self.client.services.test_session.start_test_session(test_session_handle)
        if session.puzzle.id != identity.puzzle_id:
            raise CgPuzzleManagerError(
                    f"TestSession/startTestSession({test_session_handle!r}) returned puzzle "
                    f"{session.puzzle.id}, expected {identity.puzzle_id}--refusing to repair "
                    "with mismatched data."
                )
        question = session.current_question.question

        self.meta_dir.mkdir(parents=True, exist_ok=True)
        (self.meta_dir / STATEMENT_FILE_NAME).write_text(question.statement, encoding="utf-8")
        (self.meta_dir / STUB_GENERATOR_FILE_NAME).write_text(f"{question.stub_generator}\n", encoding="utf-8")
        await download_test_cases(self.client, question.test_cases, self.tests_dir)
        _write_meta_gitignore(self.puzzle_dir)

        server_data = CgPuzzleServerData(
                test_session_handle=test_session_handle, title=progress.title,
                puzzle_pretty_id=progress.pretty_id,
                puzzle_type=question.contribution.contribution_type,
                difficulty=session.puzzle.level,
            )
        server_data.save(self.server_data_file)

        puzzle_data = self.load_puzzle_data()
        if puzzle_data is not None:
            _refresh_solution_symlink(self.puzzle_dir, puzzle_data.solution_language)
        return server_data

    # --- diff / discard_local / submit ----------------------------------------------------------

    async def _fetch_current_answer_code(self) -> tuple[str, CgSolutionLanguage] | None:
        """A fresh `TestSession/startTestSession` call (using the cached `test_session_handle`),
           returning the codingamer's current server-side saved answer (code, language), or None
           if this puzzle has never been submitted at all."""
        _, server_data, _ = self._require_state()
        session = await self.client.services.test_session.start_test_session(server_data.test_session_handle)
        answer = session.current_question.answer
        # see the note in import_()--`answer` itself can be non-None with no real answer inside.
        if answer is None or answer.code is None or answer.programming_language_id is None:
            return None
        return answer.code, answer.programming_language_id

    async def diff(self) -> str:
        """A unified text diff between the local `data/solution.src` and the server's current
           last-submitted answer for this puzzle--empty if they're identical, or if there's no
           local file/no server answer at all yet (nothing meaningful to diff in that case).

        Raises:
            FileNotFoundError: if this working directory has never been imported.
            CgPuzzleManagerError: if `.meta/` is missing (run `repair()` first).
        """
        self._require_state()
        local_lines = self.solution_file.read_text(encoding="utf-8").splitlines(keepends=True) \
            if self.solution_file.is_file() else []
        current = await self._fetch_current_answer_code()
        server_lines = current[0].splitlines(keepends=True) if current is not None else []
        return "".join(difflib.unified_diff(server_lines, local_lines, fromfile="server", tofile="local"))

    async def discard_local(self) -> CgPuzzleDiscardResult:
        """Discard local edits: overwrite `data/solution.src` with the server's current
           last-submitted answer for this puzzle (and update `data/puzzle-data.json`'s
           `solution_language` to match, in case the last submission was in a different language
           than previously recorded), then refresh the `solution.<ext>` symlink. Purely a local
           overwrite--no submission or other server-side side effect.

        Raises:
            FileNotFoundError: if this working directory has never been imported.
            CgPuzzleManagerError: if `.meta/` is missing (run `repair()` first), or if this
                                   puzzle has never been submitted at all (nothing server-side to
                                   discard to).
        """
        identity, server_data, puzzle_data = self._require_state()
        current = await self._fetch_current_answer_code()
        if current is None:
            raise CgPuzzleManagerError(
                    f"Puzzle {identity.puzzle_id} has no server-side answer yet (never "
                    "submitted)--nothing to discard local edits to."
                )
        code, solution_language = current
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.solution_file.write_text(code, encoding="utf-8")
        if solution_language != puzzle_data.solution_language:
            dataclasses.replace(puzzle_data, solution_language=solution_language).save(self.puzzle_data_file)
        _refresh_solution_symlink(self.puzzle_dir, solution_language)
        return CgPuzzleDiscardResult(code=code, solution_language=solution_language)

    async def submit(self) -> CgSubmissionReport:
        """Submit the current local `data/solution.src` to the server for credit
           (`TestSession/submit`), in `data/puzzle-data.json`'s recorded `solution_language`,
           then fetch and return the resulting results report
           (`Report/findReportBySubmission`)--score, achievement completion, and per-validator
           pass/fail.

           Named `submit()`, not `push()` (unlike `codingame_tools.contribution_manager`'s
           git-vocabulary naming)--a puzzle working directory has two distinct server-side
           persistence phases, not one: the test session's current answer (see `play()`'s
           docstring--confirmed live to be silently updated by *any* `TestSession/play` call, not
           just this method) and this method's actual graded submission. "Push" would suggest
           the former; this method is unambiguously the latter.

           CAUTION: unlike `codingame_tools.contribution_manager`'s `push()`, this always
           creates a new graded submission--there's no draft/private-staging concept for puzzle
           solutions. See `CgTestSessionService.submit`'s docstring for the (currently
           unhandled) heavy-validation Cloudflare/524 timeout risk shared with contribution
           submission.

           The report is fetched via `CgReportServiceHelper.find_report_by_submission_when_ready`
           rather than the plain `find_report_by_submission`, since calling the latter immediately
           after submitting can race server-side grading--see `CgSubmissionReport`'s class
           docstring.

        Returns:
            The new submission's `CgSubmissionReport` (its `.submission_id` is the same numeric
            ID `TestSession/submit` itself returns).

        Raises:
            FileNotFoundError: if this working directory has never been imported.
            CgPuzzleManagerError: if `.meta/` is missing (run `repair()` first).
            TimeoutError: if grading hasn't finished within
                          `find_report_by_submission_when_ready`'s default timeout.
        """
        _, server_data, puzzle_data = self._require_state()
        code = self.solution_file.read_text(encoding="utf-8")
        request = CgSubmitRequest(code=code, programming_language_id=puzzle_data.solution_language)
        submission_id = await self.client.services.test_session.submit(server_data.test_session_handle, request)
        return await self.client.services.report.helper.find_report_by_submission_when_ready(submission_id)

    # --- play ------------------------------------------------------------------------------------

    async def play(self, test_indices: list[int] | None = None) -> list[CgPuzzleRemoteTestResult]:
        """Run the current local `data/solution.src` against one or more of the puzzle's test
           cases via the server (`TestSession/play`--the IDE's "Test"/"Run" button, as opposed
           to `submit()`'s full "Submit"). Each index is a separate live API call--there is no
           batch form of `TestSession/play`--run sequentially, in the order given.

           CONFIRMED LIVE (2026-08-01): this call has a side effect beyond just running the given
           test case(s)--the server durably persists whatever `code` was sent as the test
           session's current answer (the same "current answer" returned by
           `TestSession/startTestSession`, and visible in the web IDE from any browser), whether
           or not the test case actually passes. This is NOT a grading/submission event (no
           `Report`/score is produced), and there's no separate "just save, don't run" call--the
           web IDE itself has no autosave either (confirmed: editing code there without running a
           test, then navigating away, prompts "All changes will be lost")--so running at least
           one test case is, in effect, the only way to persist a change short of a real
           submission. `submit()` also persists the code this way (again regardless of whether
           the submission scores well), as a side effect of grading it.

        Args:
            test_indices: 1-based indices to run against (see `CgTestSessionTestCase.index`).
                          Need not be locally downloaded--the server runs by index alone.
                          If not given, runs every downloaded test case (`.meta/tests/`, i.e.
                          every test case this working directory actually knows about--NOT
                          necessarily every test case the puzzle has).

        Returns:
            One `CgPuzzleRemoteTestResult` per index, in the order run.

        Raises:
            FileNotFoundError: if this working directory has never been imported, or (only when
                                `test_indices` is not given) has no downloaded test cases at all.
            CgPuzzleManagerError: if `.meta/` is missing (run `repair()` first).
        """
        _, server_data, puzzle_data = self._require_state()
        downloaded = list_downloaded_test_cases(self.tests_dir)
        labels_by_index = {tc.index: tc.label for tc in downloaded}
        if test_indices is None:
            if not downloaded:
                raise FileNotFoundError(f"{self.tests_dir} has no downloaded test cases--run `cg puzzle repair` first.")
            indices = [tc.index for tc in downloaded]
        else:
            indices = test_indices

        code = self.solution_file.read_text(encoding="utf-8")
        results: list[CgPuzzleRemoteTestResult] = []
        for index in indices:
            request = CgPlayRequest(
                    code=code,
                    programming_language_id=puzzle_data.solution_language,
                    multiple_languages=CgMultipleLanguagesTestParams(test_index=index),
                )
            play_result = await self.client.services.test_session.play(server_data.test_session_handle, request)
            results.append(CgPuzzleRemoteTestResult(
                    index=index, label=labels_by_index.get(index, f"test {index}"), result=play_result,
                ))
        return results

    # --- play_local --------------------------------------------------------------------------

    def play_local(
                self,
                test_index: int | None = None,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> list[CgPuzzleLocalTestResult]:
        """Run the current local `data/solution.src` against the downloaded `.meta/tests/` test
           cases entirely locally--no network access at all, unlike `play()`--by shelling out to
           the appropriate interpreter/compiler as a subprocess (see
           `codingame_tools.test_runner.run_solution_locally`) and comparing captured stdout to
           each test case's expected `output.txt`.

           This is the general-purpose, batch runner. For stepping through `solution.src` in a
           debugger against a specific test case's input instead, see
           `codingame_tools.test_runner.debug_stdin` (launched directly, not through this
           method--a subprocess like this one spawns can't be stepped into).

        Args:
            test_index: If given, only run the test case with this index (the same numbering
                        `.meta/tests/`'s directory names and `play()`'s own `test_index` use).
                        Defaults to running every downloaded test case.
            timeout:    Per-test-case wall-clock timeout in seconds--see
                        `codingame_tools.test_runner.DEFAULT_RUN_TIMEOUT_SECONDS`.

        Returns:
            One `CgPuzzleLocalTestResult` per test case run, in index order.

        Raises:
            FileNotFoundError: if this working directory has never been imported, or has no
                                downloaded test cases at all (run `cg puzzle repair` first).
            CgPuzzleManagerError: if `test_index` doesn't match any downloaded test case.
            CgLocalRunUnsupportedLanguageError: if `data/puzzle-data.json`'s `solution_language`
                                                 isn't yet supported by `codingame_tools.
                                                 test_runner.run_solution_locally`.
            CgPuzzleLocalTestFailedError: if any test case's output didn't match (or the solution
                                           crashed/timed out)--carries every result via `.results`.
        """
        identity = self.load_identity()
        if identity is None:
            raise FileNotFoundError(
                    f"{self.identity_file} does not exist--this working directory has never "
                    "been imported (see `cg puzzle import`)."
                )
        puzzle_data = self.load_puzzle_data()
        if puzzle_data is None:
            raise FileNotFoundError(f"{self.puzzle_data_file} does not exist--this working directory is in an inconsistent state.")
        downloaded = list_downloaded_test_cases(self.tests_dir)
        if not downloaded:
            raise FileNotFoundError(f"{self.tests_dir} has no downloaded test cases--run `cg puzzle repair` first.")
        if test_index is not None:
            downloaded = [tc for tc in downloaded if tc.index == test_index]
            if not downloaded:
                raise CgPuzzleManagerError(f"No downloaded test case with index {test_index}.")

        results: list[CgPuzzleLocalTestResult] = []
        for test_case in downloaded:
            run_result = run_solution_locally(
                    self.solution_file, puzzle_data.solution_language, test_case.input_text, timeout=timeout)
            passed = not run_result.timed_out and run_result.returncode == 0 \
                and outputs_match(run_result.output, test_case.output_text)
            results.append(CgPuzzleLocalTestResult(
                    index=test_case.index, label=test_case.label, passed=passed,
                    input=test_case.input_text, expected_output=test_case.output_text,
                    actual_output=run_result.output, stderr=run_result.stderr,
                    timed_out=run_result.timed_out,
                ))
        if any(not r.passed for r in results):
            raise CgPuzzleLocalTestFailedError(results)
        return results

    # --- status ----------------------------------------------------------------------------

    async def status(self, *, refresh: bool = False) -> CgPuzzleStatus:
        """A point-in-time summary of this working directory--see `CgPuzzleStatus`.

           By default, entirely local/cheap: no network access at all--just the three on-disk
           manifests. Pass `refresh=True` to also check `local_dirty` (a live
           `TestSession/startTestSession` call, same as `diff()`) and fetch `progress` (a live
           `Puzzle/findProgressByIds` call)--both stay `None` otherwise. Unlike
           `codingame_tools.contribution_manager`'s `status()`, there is no cache file this writes
           to for next time--puzzle working directories have no such cache at all (see the module
           docstring); every `refresh=True` call is genuinely live, every time.

        Args:
            refresh: If True, also check for local edits against the server's last-submitted
                     answer and fetch live progress/score info. Defaults to False.

        Raises:
            FileNotFoundError: if this working directory has never been imported.
            CgPuzzleManagerError: if `.meta/` is missing (run `repair()` first).
        """
        identity, server_data, puzzle_data = self._require_state()
        local_dirty: bool | None = None
        progress: CgLastActivityPuzzle | None = None
        if refresh:
            local_dirty = bool(await self.diff())
            progress_results = await self.client.services.puzzle.find_progress_by_ids([identity.puzzle_id])
            if progress_results and progress_results[0].id == identity.puzzle_id:
                progress = progress_results[0]
        return CgPuzzleStatus(
                puzzle_dir=self.puzzle_dir,
                puzzle_id=identity.puzzle_id,
                puzzle_handle=identity.puzzle_handle,
                title=server_data.title,
                puzzle_pretty_id=server_data.puzzle_pretty_id,
                puzzle_type=server_data.puzzle_type,
                difficulty=server_data.difficulty,
                solution_language=puzzle_data.solution_language,
                local_dirty=local_dirty,
                progress=progress,
            )

    # --- delete --------------------------------------------------------------------------------

    def delete(self) -> None:
        """Remove this working directory entirely (`puzzle.json`, `.meta/`, `data/`, and the
           `solution.<ext>` convenience symlink)--purely local. Unlike `codingame_tools.
           contribution_manager.CgContributionManager.delete()`, there is no server-side
           counterpart at all here--a puzzle already exists on the server before you can solve
           it (see the module docstring), so there is nothing to delete *there*; this only ever
           removes your own local working directory.

           No confirmation prompt here--that's the CLI's job (`cg puzzle delete`), same as every
           other method in this class.

        Raises:
            FileNotFoundError: if this working directory has never been imported.
        """
        if self.load_identity() is None:
            raise FileNotFoundError(
                    f"{self.identity_file} does not exist--this working directory has never "
                    "been imported (nothing to delete)."
                )
        shutil.rmtree(self.puzzle_dir)
