"""`CgContributionManager`: builds a contribution working directory from an existing server-side
   contribution (`import_`), pushes a working directory's content back to the server (`commit`),
   and reconciles local/server drift (`rebase`, `merge_discard_local`, `merge_discard_server`).

   See `codingame_client.contribution_manager.schema` for the local (`contribution.json`) manifest
   format, `codingame_client.contribution_manager.last_committed` for the cached base
   (`last_committed/`) state, and `codingame_client.contribution_manager.tree_diff` for how the
   two (plus the current server state) are compared.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import tempfile
from enum import Enum
from pathlib import Path

from ..client.async_.client import CgAsyncClient
from ..client.common.protocol.contribution import CgContribution, CgContributionData, CgContributionId, CgPuzzleType
from ..client.common.protocol.schema import cg_extension_to_solution_language, cg_solution_language_to_extension
from ..client.common.raw_client import compute_content_hash
from .last_committed import LAST_COMMITTED_CONTRIBUTION_FILE_NAME as _LC_CONTRIBUTION_FILE_NAME
from .last_committed import LAST_COMMITTED_COVER_FILE_NAME as _LC_COVER_FILE_NAME
from .last_committed import (
    LAST_COMMITTED_SUBDIR_NAME,
    CgLastCommittedContribution,
)
from .schema import CONTRIBUTION_FILE_NAME, CgContributionWorkingDir
from .test_cases_dir import TESTS_SUBDIR_NAME, commit_test_cases, import_test_cases
from .tree_diff import diff_two_trees

__all__ = [
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
    "CgContributionManagerError",
    "CgRebaseStatus",
    "CgContributionManager",
]

logger = logging.getLogger(__name__)

STATEMENT_FILE_NAME = "statement.cgmd"
INPUT_DESCRIPTION_FILE_NAME = "input_description.cgmd"
OUTPUT_DESCRIPTION_FILE_NAME = "output_description.cgmd"
CONSTRAINTS_FILE_NAME = "constraints.cgmd"
STUB_GENERATOR_FILE_NAME = "stub_generator.cgstub"
COVER_IMAGE_FILE_NAME = "cover.png"

_ACTIVE_VERSION_POLL_INTERVAL_SECONDS = 2.0
_ACTIVE_VERSION_POLL_MAX_ATTEMPTS = 10
"""See `CgContributionManager._refresh_active_version`--calibrated for the brief eventual-
   consistency lag confirmed live (caught up within a few seconds), not the much longer 524-
   timeout scenario `CgAsyncContributionServiceHelper` polls for (30s interval, unbounded by
   default)."""


class CgContributionManagerError(Exception):
    """Raised for contribution-manager-level errors not better represented by a more specific
       exception (e.g. attempting to `commit()` without a `puzzle_type` set, or a corrupted
       `last_committed/` cover-image cache)."""


class CgRebaseStatus(str, Enum):
    """The outcome of `CgContributionManager.rebase()`."""

    UP_TO_DATE = "up_to_date"
    """The server hasn't changed since `last_committed/`--nothing to do, regardless of whether the
       local working directory has uncommitted edits."""

    FAST_FORWARDED = "fast_forwarded"
    """The server changed, but the local working directory had no uncommitted edits (matched
       `last_committed/` exactly)--the working directory and `last_committed/` were both refreshed
       to the new server state (equivalent to `merge_discard_local`)."""

    CONFLICT = "conflict"
    """Both the server and the local working directory have diverged from `last_committed/`--
       nothing was changed. Use `cg contribution diff` to inspect, and `merge_discard_local`/
       `merge_discard_server`/an external merge tool to resolve."""


def _ensure_trailing_newline(text: str) -> str:
    """See `test_cases_dir._ensure_trailing_newline`--same rationale, used here for the other
       sidecar text files (statement.cgmd, the solution file, etc.)."""
    return text if text.endswith("\n") else text + "\n"


def _write_sidecar(path: Path, content: str | None) -> None:
    """Write `content` to `path` (creating parent directories, appending a trailing newline if
       missing), or remove `path` if `content` is None."""
    if content is None:
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ensure_trailing_newline(content), encoding="utf-8")


def _read_sidecar(path: Path) -> str | None:
    """Read `path`'s content, or None if it doesn't exist."""
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _clear_statement_html(contribution: CgContribution) -> CgContribution:
    """Return a copy of `contribution` with `last_version.statement_html` nulled out--it's
       entirely derivative of `data`'s text fields and never needed to reconstruct or resubmit a
       version, so there's no reason to carry it around in cached state."""
    cleaned_version = dataclasses.replace(contribution.last_version, statement_html=None)
    return dataclasses.replace(contribution, last_version=cleaned_version)


def _default_solution_file_name(solution_language: str | None) -> str:
    """A best-guess solution filename for `solution_language`, e.g. "solution.py" for "Python3"--
       "solution.txt" if the language is unknown/unmapped."""
    extension = cg_solution_language_to_extension(solution_language) if solution_language else None
    return f"solution.{extension}" if extension else "solution.txt"


def _solution_language_changed(solution_file: str, solution_language: str | None) -> bool:
    """Whether `solution_file`'s extension no longer matches `solution_language`--only True when
       both sides are confidently known and actually differ; an unrecognized extension or unknown
       language is treated as "can't tell, don't force a change" rather than a mismatch."""
    prior_extension = Path(solution_file).suffix.lstrip(".")
    prior_language = cg_extension_to_solution_language(prior_extension) if prior_extension else None
    return prior_language is not None and solution_language is not None and prior_language != solution_language


def _materialize_content_tree(
            target_dir: Path,
            *,
            puzzle_type: CgPuzzleType,
            draft: bool,
            ready_for_moderation: bool,
            data: CgContributionData,
            cover_bytes: bytes | None,
            prior_solution_file: str | None,
        ) -> CgContributionWorkingDir:
    """Write a full working-dir-shaped content tree into `target_dir`: sidecar text files,
       `cover.png`, `tests/`, a solution file, and `contribution.json` itself--everything except
       `last_committed/`, which is a separate concern of the real working directory, not of a
       content snapshot as such.

       Used both for the real working directory (`import_`, passing its own pre-existing
       `solution_file` as `prior_solution_file` so re-imports don't reset an intentionally-placed
       solution filename) and for ephemeral base/remote trees materialized purely for diffing
       (`materialize_base`/`materialize_remote`, always `prior_solution_file=None`--a fresh guess
       every time, since these trees aren't meant to be edited or reused).

    Returns:
        The `CgContributionWorkingDir` that was written to `target_dir/contribution.json`.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    _write_sidecar(target_dir / STATEMENT_FILE_NAME, data.statement)
    _write_sidecar(target_dir / INPUT_DESCRIPTION_FILE_NAME, data.input_description)
    _write_sidecar(target_dir / OUTPUT_DESCRIPTION_FILE_NAME, data.output_description)
    _write_sidecar(target_dir / CONSTRAINTS_FILE_NAME, data.constraints)
    _write_sidecar(target_dir / STUB_GENERATOR_FILE_NAME, data.stub_generator)

    cover_path = target_dir / COVER_IMAGE_FILE_NAME
    if cover_bytes is not None:
        cover_path.write_bytes(cover_bytes)
    elif cover_path.is_file():
        cover_path.unlink()

    solution_file = prior_solution_file
    if data.solution is not None:
        if solution_file is not None and _solution_language_changed(solution_file, data.solution_language):
            # The language changed since solution_file was chosen (e.g. the reference solution was
            # rewritten in a different language)--reusing the old path/extension would write the
            # new language's content under a misleading name. Regenerate a fresh default name and
            # delete the old file--solution_file is always inside target_dir (see the class
            # docstring on `solution_file`; a symlink there to somewhere else is fine--unlink()
            # only removes the link itself, never whatever it points to).
            old_path = target_dir / solution_file
            if old_path.is_file():
                old_path.unlink()
            solution_file = None
        if solution_file is None:
            solution_file = _default_solution_file_name(data.solution_language)
        solution_path = target_dir / solution_file
        solution_path.parent.mkdir(parents=True, exist_ok=True)
        solution_path.write_text(_ensure_trailing_newline(data.solution), encoding="utf-8")

    import_test_cases(data.test_cases, target_dir / TESTS_SUBDIR_NAME)

    working_data = CgContributionData(
            title=data.title,
            difficulty=data.difficulty,
            topics=data.topics,
            solution_language=data.solution_language,
        )
    working = CgContributionWorkingDir(
            puzzle_type=puzzle_type,
            draft=draft,
            ready_for_moderation=ready_for_moderation,
            solution_file=solution_file,
            data=working_data,
        )
    working.save(target_dir / CONTRIBUTION_FILE_NAME)
    return working


class CgContributionManager:
    """Builds/updates a contribution working directory (`contribution_dir`) against the server,
       via an already-authenticated `CgAsyncClient`."""

    contribution_dir: Path
    client: CgAsyncClient

    def __init__(self, contribution_dir: Path | str, client: CgAsyncClient) -> None:
        self.contribution_dir = Path(contribution_dir)
        self.client = client

    @property
    def contribution_file(self) -> Path:
        """Path to this working directory's `contribution.json` manifest."""
        return self.contribution_dir / CONTRIBUTION_FILE_NAME

    @property
    def tests_dir(self) -> Path:
        """Path to this working directory's `tests/` subdirectory."""
        return self.contribution_dir / TESTS_SUBDIR_NAME

    @property
    def last_committed_dir(self) -> Path:
        """Path to this working directory's `last_committed/` subdirectory."""
        return self.contribution_dir / LAST_COMMITTED_SUBDIR_NAME

    @property
    def last_committed_contribution_file(self) -> Path:
        """Path to `last_committed/contribution.json`."""
        return self.last_committed_dir / _LC_CONTRIBUTION_FILE_NAME

    @property
    def last_committed_cover_file(self) -> Path:
        """Path to `last_committed/cover.png` (the cached base cover image, if any)."""
        return self.last_committed_dir / _LC_COVER_FILE_NAME

    def load(self) -> CgContributionWorkingDir:
        """Load `contribution.json`.

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
        """
        return CgContributionWorkingDir.load(self.contribution_file)

    def save(self, working: CgContributionWorkingDir) -> None:
        """Write `working` back to `contribution.json`, creating `contribution_dir` if needed."""
        self.contribution_dir.mkdir(parents=True, exist_ok=True)
        working.save(self.contribution_file)

    def load_last_committed(self) -> CgLastCommittedContribution | None:
        """Load `last_committed/contribution.json`, or None if this working directory has never
           been imported/committed."""
        if not self.last_committed_contribution_file.is_file():
            return None
        return CgLastCommittedContribution.load(self.last_committed_contribution_file)

    def save_last_committed(self, last_committed: CgLastCommittedContribution, *, cover_bytes: bytes | None) -> None:
        """Write `last_committed/contribution.json`, and `last_committed/cover.png` (or remove it
           if `cover_bytes` is None)--the two are always written together here, since the caller
           always knows the definitive new state of both (unlike `merge_discard_server`, which
           may leave the cover cache untouched if the binary ID didn't actually change--see there)."""
        self.last_committed_dir.mkdir(parents=True, exist_ok=True)
        last_committed.save(self.last_committed_contribution_file)
        if cover_bytes is not None:
            self.last_committed_cover_file.write_bytes(cover_bytes)
        elif self.last_committed_cover_file.is_file():
            self.last_committed_cover_file.unlink()

    def _load_verified_last_committed_cover(self, last_committed: CgLastCommittedContribution) -> bytes | None:
        """Load `last_committed/cover.png`, verifying its content hash still matches
           `last_committed.cover_binary_hash` (the source of truth--see the `last_committed`
           module docstring). Returns None if there's no cover recorded at all.

        Raises:
            CgContributionManagerError: if a cover is recorded but the cache file is missing or
                                         its hash doesn't match--a corrupted/tampered cache, not a
                                         normal state to silently work around.
        """
        if last_committed.cover_binary_hash is None:
            return None
        if not self.last_committed_cover_file.is_file():
            raise CgContributionManagerError(
                    f"{self.last_committed_contribution_file} records a cover image (hash "
                    f"{last_committed.cover_binary_hash!r}) but {self.last_committed_cover_file} is "
                    "missing. Run `cg contribution merge --discard-server` (or re-import) to rebuild it."
                )
        content = self.last_committed_cover_file.read_bytes()
        actual_hash = compute_content_hash(content)
        if actual_hash != last_committed.cover_binary_hash:
            raise CgContributionManagerError(
                    f"{self.last_committed_cover_file}'s content hash ({actual_hash!r}) does not "
                    f"match the recorded hash ({last_committed.cover_binary_hash!r}) in "
                    f"{self.last_committed_contribution_file}--the cache is corrupted. Run "
                    "`cg contribution merge --discard-server` (or re-import) to rebuild it."
                )
        return content

    async def import_(
                self,
                contribution_id: CgContributionId,
                *,
                contribution: CgContribution | None = None,
            ) -> CgContributionWorkingDir:
        """Build (or refresh) this working directory from an existing server-side contribution:
           `findContribution` (unless `contribution` is already given, e.g. by `rebase()`, to
           avoid a redundant call), followed by downloading the cover image if one is set. Also
           refreshes `last_committed/` to match.

           A pre-existing `solution_file` pointer (from a prior `import_`/manual edit) is
           preserved across re-imports rather than reset to a freshly-guessed name--e.g. if it's a
           symlink to somewhere else (see `CgContributionWorkingDir.solution_file`). The `tests/`
           subdirectory is entirely replaced (see `import_test_cases`).
        """
        prior = self.load() if self.contribution_file.is_file() else None
        if contribution is None:
            contribution = await self.client.services.contribution.find_contribution(contribution_id)
        version = contribution.last_version
        data = version.data

        cover_bytes: bytes | None = None
        cover_hash: str | None = None
        if data.cover_binary_id is not None:
            download = await self.client.servlets.file_servlet(data.cover_binary_id)
            cover_bytes = download.content
            cover_hash = download.hash

        working = _materialize_content_tree(
                self.contribution_dir,
                puzzle_type=contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=data,
                cover_bytes=cover_bytes,
                prior_solution_file=prior.solution_file if prior is not None else None,
            )
        self.save_last_committed(
                CgLastCommittedContribution(contribution=_clear_statement_html(contribution), cover_binary_hash=cover_hash),
                cover_bytes=cover_bytes,
            )
        return working

    async def commit(self) -> CgContribution:
        """Push this working directory's content to the server via `updateContribution`, updating
           `last_committed/` to reflect the result on success.

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
            CgContributionManagerError: if `puzzle_type` isn't set.
            NotImplementedError: if this working directory has never been associated with a
                                  server-side contribution (submitting a brand-new contribution
                                  isn't supported yet--the protocol for it hasn't been reverse
                                  engineered).
        """
        working = self.load()
        if working.puzzle_type is None:
            raise CgContributionManagerError("Cannot commit: puzzle_type is not set in contribution.json.")
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise NotImplementedError(
                    "Submitting a brand-new contribution (one with no last_committed/) is not yet supported."
                )
        contribution_id = last_committed.contribution_id
        prev_version = last_committed.prev_version

        cover_path = self.contribution_dir / COVER_IMAGE_FILE_NAME
        cover_binary_id: int | None
        cover_content_hash: str | None
        cover_bytes: bytes | None
        if cover_path.is_file():
            cover_bytes = cover_path.read_bytes()
            cover_content_hash = compute_content_hash(cover_bytes)
            prior_binary_id = last_committed.contribution.last_version.data.cover_binary_id
            if cover_content_hash == last_committed.cover_binary_hash and prior_binary_id is not None:
                cover_binary_id = prior_binary_id
            else:
                upload = await self.client.servlets.file_upload(
                        cover_bytes, filename=COVER_IMAGE_FILE_NAME, content_type="image/png")
                cover_binary_id = upload.id
        else:
            cover_binary_id = None
            cover_content_hash = None
            cover_bytes = None

        solution = None
        if working.solution_file is not None:
            solution = (self.contribution_dir / working.solution_file).read_text(encoding="utf-8")

        data = dataclasses.replace(
                working.data,
                statement=_read_sidecar(self.contribution_dir / STATEMENT_FILE_NAME),
                input_description=_read_sidecar(self.contribution_dir / INPUT_DESCRIPTION_FILE_NAME),
                output_description=_read_sidecar(self.contribution_dir / OUTPUT_DESCRIPTION_FILE_NAME),
                constraints=_read_sidecar(self.contribution_dir / CONSTRAINTS_FILE_NAME),
                stub_generator=_read_sidecar(self.contribution_dir / STUB_GENERATOR_FILE_NAME),
                solution=solution,
                test_cases=commit_test_cases(self.tests_dir),
                cover_binary_id=cover_binary_id,
            )

        result = await self.client.services.contribution.helper.update_contribution(
                contribution_id,
                working.puzzle_type,
                data,
                working.draft,
                working.ready_for_moderation,
                prev_version,
            )
        result = await self._refresh_active_version(result, contribution_id)

        self.save_last_committed(
                CgLastCommittedContribution(contribution=_clear_statement_html(result), cover_binary_hash=cover_content_hash),
                cover_bytes=cover_bytes,
            )
        return result

    async def _refresh_active_version(self, result: CgContribution, contribution_id: CgContributionId) -> CgContribution:
        """`updateContribution`'s response has been confirmed live to report a stale
           `active_version` (lagging one version behind `last_version.version` in that same
           response), apparently because the server finishes activating the new version slightly
           asynchronously--see `CgContribution.active_version`'s docstring. Since
           `last_committed/` is cached and its `active_version` needs to be accurate for callers,
           this re-fetches via `findContribution`, polling briefly (a few seconds, best-effort)
           until `active_version` catches up to the version just submitted.

           Gives up and returns the latest `findContribution` result even if `active_version`
           still hasn't caught up, rather than blocking indefinitely on unconfirmed eventual-
           consistency timing--logs a warning in that case.
        """
        target_version = result.last_version.version
        if result.active_version == target_version:
            return result  # already fresh (e.g. helper's own 524-recovery already re-fetched it)
        refreshed = result
        for attempt in range(_ACTIVE_VERSION_POLL_MAX_ATTEMPTS):
            refreshed = await self.client.services.contribution.find_contribution(contribution_id)
            if refreshed.active_version == target_version:
                return refreshed
            if attempt + 1 < _ACTIVE_VERSION_POLL_MAX_ATTEMPTS:
                await asyncio.sleep(_ACTIVE_VERSION_POLL_INTERVAL_SECONDS)
        logger.warning(
                "commit(): active_version for contribution %r is still %s (expected %s) after "
                "%d findContribution attempts; using it anyway.",
                contribution_id, refreshed.active_version, target_version, _ACTIVE_VERSION_POLL_MAX_ATTEMPTS,
            )
        return refreshed

    def materialize_base(self, target_dir: Path, *, prior_solution_file: str | None = None) -> CgLastCommittedContribution:
        """Materialize the "base" (last-synced) content tree into `target_dir`, from
           `last_committed/`--no network access at all.

           `prior_solution_file` is normally left `None` (a fresh best-guess name, for the usual
           case of `target_dir` being an ephemeral temp tree used only for diffing)--`revert()`
           passes its own pre-existing `solution_file` pointer instead, since it materializes
           directly into the real `contribution_dir` and wants to preserve that pointer exactly
           like `import_()` does.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: see `_load_verified_last_committed_cover`.
        """
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise FileNotFoundError(
                    f"{self.last_committed_contribution_file} does not exist--nothing to diff/rebase/revert against.")
        cover_bytes = self._load_verified_last_committed_cover(last_committed)
        version = last_committed.contribution.last_version
        _materialize_content_tree(
                target_dir,
                puzzle_type=last_committed.contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=version.data,
                cover_bytes=cover_bytes,
                prior_solution_file=prior_solution_file,
            )
        return last_committed

    def revert(self) -> CgContributionWorkingDir:
        """Revert this working directory's content to match `last_committed/` (the cached base
           state) exactly--purely local, no network access at all (unlike `merge_discard_local`,
           which re-fetches the current server state first). A pre-existing `solution_file`
           pointer is preserved, same as `import_()`.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: see `_load_verified_last_committed_cover`.
        """
        prior = self.load() if self.contribution_file.is_file() else None
        self.materialize_base(self.contribution_dir, prior_solution_file=prior.solution_file if prior is not None else None)
        return self.load()

    async def materialize_remote(
                self, target_dir: Path, contribution: CgContribution | None = None,
            ) -> CgContribution:
        """Materialize the "remote" (current server) content tree into `target_dir`: a fresh
           `findContribution` (unless `contribution` is already given), downloading the cover
           image unless its binary ID is unchanged from the cached base--in which case the cached
           `last_committed/cover.png` bytes are reused instead (binary IDs are as good as a hash
           for content identity once both sides already have one--see the `last_committed` module
           docstring), avoiding a redundant download.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: see `_load_verified_last_committed_cover`.
        """
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise FileNotFoundError(
                    f"{self.last_committed_contribution_file} does not exist--nothing to diff/rebase against.")
        if contribution is None:
            contribution = await self.client.services.contribution.find_contribution(last_committed.contribution_id)
        version = contribution.last_version
        data = version.data

        base_binary_id = last_committed.contribution.last_version.data.cover_binary_id
        cover_bytes: bytes | None
        if data.cover_binary_id is None:
            cover_bytes = None
        elif data.cover_binary_id == base_binary_id:
            cover_bytes = self._load_verified_last_committed_cover(last_committed)
        else:
            download = await self.client.servlets.file_servlet(data.cover_binary_id)
            cover_bytes = download.content

        _materialize_content_tree(
                target_dir,
                puzzle_type=contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=data,
                cover_bytes=cover_bytes,
                prior_solution_file=None,
            )
        return contribution

    async def rebase(self) -> CgRebaseStatus:
        """Detect drift between the server, `last_committed/`, and this working directory's local
           content, and automatically resolve it when that's unambiguous:

           - Server unchanged since `last_committed/`: nothing to do, regardless of local edits
             (`CgRebaseStatus.UP_TO_DATE`).
           - Server changed, local unchanged (matches `last_committed/` exactly): fast-forward--
             refresh the working directory and `last_committed/` to the new server state, exactly
             like `import_`/`merge_discard_local` (`CgRebaseStatus.FAST_FORWARDED`).
           - Both changed: a real conflict, left entirely alone
             (`CgRebaseStatus.CONFLICT`)--use `cg contribution diff` to inspect, and
             `merge_discard_local`/`merge_discard_server`/an external merge tool to resolve.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
        """
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise FileNotFoundError(
                    f"{self.last_committed_contribution_file} does not exist--nothing to rebase against.")
        with tempfile.TemporaryDirectory(prefix="cg-contribution-rebase-") as tmp:
            base_dir = Path(tmp) / "base"
            remote_dir = Path(tmp) / "remote"
            self.materialize_base(base_dir)
            contribution = await self.materialize_remote(remote_dir)

            server_changed = any(entry.changed for entry in diff_two_trees(base_dir, remote_dir))
            if not server_changed:
                return CgRebaseStatus.UP_TO_DATE

            local_changed = any(entry.changed for entry in diff_two_trees(base_dir, self.contribution_dir))
            if not local_changed:
                await self.import_(last_committed.contribution_id, contribution=contribution)
                return CgRebaseStatus.FAST_FORWARDED

            return CgRebaseStatus.CONFLICT

    async def merge_discard_local(self) -> CgContributionWorkingDir:
        """Discard all local edits: unconditionally replace the working directory (and
           `last_committed/`) with the current server state. Unlike `rebase()`, doesn't check
           whether local actually diverged first--always overwrites.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
        """
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise FileNotFoundError(
                    f"{self.last_committed_contribution_file} does not exist--nothing to merge against.")
        return await self.import_(last_committed.contribution_id)

    async def merge_discard_server(self) -> CgLastCommittedContribution:
        """Update `last_committed/` to reflect the current server state, without touching any
           working-directory content files (the opposite of `merge_discard_local`: keep local,
           discard the server's changes as far as tracking is concerned--they'll simply be
           overwritten by the next `commit()`).

           The cached cover image/hash are left completely untouched if the server's
           `cover_binary_id` hasn't actually changed; a fresh download only happens if it changed
           to a new non-null ID (changing to null just clears the cache, no download needed).

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
        """
        last_committed = self.load_last_committed()
        if last_committed is None:
            raise FileNotFoundError(
                    f"{self.last_committed_contribution_file} does not exist--nothing to merge against.")
        contribution = await self.client.services.contribution.find_contribution(last_committed.contribution_id)
        new_binary_id = contribution.last_version.data.cover_binary_id
        old_binary_id = last_committed.contribution.last_version.data.cover_binary_id

        cover_changed = new_binary_id != old_binary_id
        if not cover_changed:
            cover_hash = last_committed.cover_binary_hash
            new_cover_bytes: bytes | None = None
        elif new_binary_id is None:
            cover_hash = None
            new_cover_bytes = None
        else:
            download = await self.client.servlets.file_servlet(new_binary_id)
            cover_hash = download.hash
            new_cover_bytes = download.content

        new_last_committed = CgLastCommittedContribution(
                contribution=_clear_statement_html(contribution), cover_binary_hash=cover_hash)
        self.last_committed_dir.mkdir(parents=True, exist_ok=True)
        new_last_committed.save(self.last_committed_contribution_file)
        if cover_changed:
            if new_cover_bytes is None:
                if self.last_committed_cover_file.is_file():
                    self.last_committed_cover_file.unlink()
            else:
                self.last_committed_cover_file.write_bytes(new_cover_bytes)
        return new_last_committed
