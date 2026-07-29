"""`CgContributionManager`: builds a contribution working directory from an existing server-side
   contribution (`import_`), pushes a working directory's content back to the server (`commit`),
   and reconciles local/server drift (`rebase`, and the `merge_start`/`merge_continue`/
   `merge_abort` state machine).

   See `codingame_client.contribution_manager.schema` for the working directory's own manifest
   files, `codingame_client.contribution_manager.contribution_commit_data` for the version-tracking
   file present in server-originated views, and `codingame_client.contribution_manager.tree_diff`
   for how views are compared.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import shutil
from enum import Enum
from pathlib import Path

from ..client.async_.client import CgAsyncClient
from ..client.common.protocol.contribution import CgContribution, CgContributionData, CgContributionId, CgPuzzleType
from ..client.common.protocol.schema import cg_solution_language_to_extension
from ..client.common.raw_client import compute_content_hash
from .contribution_commit_data import CONTRIBUTION_COMMIT_DATA_FILE_NAME, CgContributionCommitData, redact_commit_contribution
from .layout import (
    CONSTRAINTS_FILE_NAME,
    COVER_IMAGE_FILE_NAME,
    DATA_SUBDIR_NAME,
    INPUT_DESCRIPTION_FILE_NAME,
    LAST_COMMITTED_SUBDIR_NAME,
    MERGE_LOCAL_SUBDIR_NAME,
    MERGE_SUBDIR_NAME,
    META_SUBDIR_NAME,
    OUTPUT_DESCRIPTION_FILE_NAME,
    REMOTE_SUBDIR_NAME,
    SOLUTION_FILE_NAME,
    STATEMENT_FILE_NAME,
    STUB_GENERATOR_FILE_NAME,
)
from .schema import (
    CONTRIBUTION_DATA_FILE_NAME,
    CONTRIBUTION_IDENTITY_FILE_NAME,
    CONTRIBUTION_SCHEMA_VERSION,
    CgContributionIdentity,
    CgContributionView,
)
from .test_cases_dir import TESTS_SUBDIR_NAME, commit_test_cases, import_test_cases
from .tree_diff import compute_diff3_merge, diff_three_trees, diff_two_trees, looks_like_text, read_view_files

__all__ = [
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "SOLUTION_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
    "META_SUBDIR_NAME",
    "MERGE_SUBDIR_NAME",
    "LAST_COMMITTED_SUBDIR_NAME",
    "REMOTE_SUBDIR_NAME",
    "CgContributionManagerError",
    "CgRebaseStatus",
    "CgMergeStartStatus",
    "CgMergeStartResult",
    "CgContributionManager",
]

logger = logging.getLogger(__name__)

_ACTIVE_VERSION_POLL_INTERVAL_SECONDS = 2.0
_ACTIVE_VERSION_POLL_MAX_ATTEMPTS = 10
"""See `CgContributionManager._refresh_active_version`--calibrated for the brief eventual-
   consistency lag confirmed live (caught up within a few seconds), not the much longer 524-
   timeout scenario `CgAsyncContributionServiceHelper` polls for (30s interval, unbounded by
   default)."""

_MERGE_MARKER_PREFIX = "<<<<<<<"
"""What `_scan_unresolved_markers` looks for. `diff3 -m` always starts a conflict with a line
   beginning exactly this way (optionally followed by a `-L` label)--sufficient on its own to
   detect an unresolved conflict, so there's no need to also separately check for `|||||||`/
   `=======`/`>>>>>>>`. See `CgContributionManager.merge_continue`'s docstring for why this
   content-based check (rather than something like git's index-stage tracking) is the best we can
   do, and why that's fine in practice."""


class CgContributionManagerError(Exception):
    """Raised for contribution-manager-level errors not better represented by a more specific
       exception (e.g. attempting to `commit()` without a `puzzle_type` set, a corrupted
       `last_committed/` cover-image cache, or unresolved merge conflicts at `merge_continue`)."""


class CgRebaseStatus(str, Enum):
    """The outcome of `CgContributionManager.rebase()`."""

    UP_TO_DATE = "up_to_date"
    """The server hasn't changed since `last_committed/`--nothing to do, regardless of whether the
       local working directory has uncommitted edits."""

    FAST_FORWARDED = "fast_forwarded"
    """The server changed, but the local working directory had no uncommitted edits (matched
       `last_committed/` exactly)--the working directory and `last_committed/` were both refreshed
       to the new server state."""

    CONFLICT = "conflict"
    """Both the server and the local working directory have diverged from `last_committed/`--
       nothing was changed. Use `cg contribution diff` to inspect, and `cg contribution merge` to
       resolve."""


class CgMergeStartStatus(str, Enum):
    """The outcome of `CgContributionManager.merge_start()`."""

    STARTED = "started"
    ALREADY_IN_PROGRESS = "already_in_progress"
    """`merge_start()` is idempotent--if a merge is already in progress, it leaves the existing
       `.meta/merge/` state completely untouched rather than erroring or restarting it."""

    UP_TO_DATE = "up_to_date"
    """The server's version number already matches `last_committed/`'s--nothing to merge, so
       `.meta/merge/` was never created (any local edits are unambiguously safe to commit
       directly, no different from before `merge_start()` was called). Consistent with
       `CgRebaseStatus.UP_TO_DATE`."""


@dataclasses.dataclass(frozen=True)
class CgMergeStartResult:
    """The outcome of `CgContributionManager.merge_start()`."""

    status: CgMergeStartStatus

    text_conflicts: tuple[str, ...] = ()
    """Relative paths where both sides changed differently and `diff3` conflict markers were
       written into the working-directory file for manual resolution."""

    binary_conflicts: tuple[str, ...] = ()
    """Relative paths where both sides changed differently but the content isn't text (in
       practice, always `cover.png`)--the working directory's local version was kept as-is; pull
       `.meta/remote/<path>` in by hand if you want the server's version instead."""


def _ensure_trailing_newline(text: str) -> str:
    """See `test_cases_dir._ensure_trailing_newline`--same rationale, used here for the other
       sidecar text files (statement.cgmd, solution.src, etc.)."""
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


def _refresh_solution_symlink(target_dir: Path, solution_language: str | None) -> None:
    """Remove any existing `solution.<ext>` convenience symlink at `target_dir`'s root, then
       recreate one pointing at `data/solution.src` if that file actually exists and
       `solution_language` maps to a known extension. Never touches `solution.src` itself--only
       ever called for the real working directory, never for `last_committed/` or a
       `.meta/merge/` snapshot."""
    for path in target_dir.glob("solution.*"):
        if path.is_symlink() and path.name != SOLUTION_FILE_NAME:
            path.unlink()
    if not (target_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME).is_file():
        return
    extension = cg_solution_language_to_extension(solution_language) if solution_language else None
    if extension is None:
        return
    link_name = f"solution.{extension}"
    if link_name == SOLUTION_FILE_NAME:
        return
    (target_dir / link_name).symlink_to(f"{DATA_SUBDIR_NAME}/{SOLUTION_FILE_NAME}")


def _cover_hash_matches(view_dir: Path, commit_data: CgContributionCommitData) -> bool:
    """Whether `view_dir/data/cover.png` still matches `commit_data.cover_binary_hash`--never
       raises (unlike `CgContributionManager._verify_last_committed_cover`): used only to decide
       whether an *opportunistic* cache (a materialized view's own previous content, not the
       sacred `last_committed/` base) can be reused, so a mismatch or missing file just means
       "don't reuse it, fetch fresh instead" rather than a hard error."""
    if commit_data.cover_binary_hash is None:
        return False
    cover_path = view_dir / DATA_SUBDIR_NAME / COVER_IMAGE_FILE_NAME
    if not cover_path.is_file():
        return False
    return compute_content_hash(cover_path.read_bytes()) == commit_data.cover_binary_hash


def _materialize_view(
            target_dir: Path,
            *,
            puzzle_type: CgPuzzleType,
            draft: bool,
            ready_for_moderation: bool,
            data: CgContributionData,
            cover_bytes: bytes | None,
            snapshot_contribution: CgContribution | None,
            create_solution_symlink: bool,
        ) -> CgContributionView:
    """Write one materialized view: `target_dir/data/` gets `contribution-data.json`, sidecar text
       files, `solution.src`, `cover.png`, `tests/`--nothing but diffable content, by construction
       (see `codingame_client.contribution_manager.layout.DATA_SUBDIR_NAME`). `target_dir` itself
       (never `target_dir/data/`) optionally gets `contribution-version-data.json` (if
       `snapshot_contribution` is given) and/or the `solution.<ext>` convenience symlink (if
       `create_solution_symlink`). Never writes `contribution.json` (identity)--that's a separate,
       working-directory-root-only concern (see `CgContributionManager.import_`).

    Returns:
        The `CgContributionView` that was written to `target_dir/data/contribution-data.json`.
    """
    data_dir = target_dir / DATA_SUBDIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)

    _write_sidecar(data_dir / STATEMENT_FILE_NAME, data.statement)
    _write_sidecar(data_dir / INPUT_DESCRIPTION_FILE_NAME, data.input_description)
    _write_sidecar(data_dir / OUTPUT_DESCRIPTION_FILE_NAME, data.output_description)
    _write_sidecar(data_dir / CONSTRAINTS_FILE_NAME, data.constraints)
    _write_sidecar(data_dir / STUB_GENERATOR_FILE_NAME, data.stub_generator)
    _write_sidecar(data_dir / SOLUTION_FILE_NAME, data.solution)

    cover_path = data_dir / COVER_IMAGE_FILE_NAME
    if cover_bytes is not None:
        cover_path.write_bytes(cover_bytes)
    elif cover_path.is_file():
        cover_path.unlink()

    if create_solution_symlink:
        _refresh_solution_symlink(target_dir, data.solution_language)

    import_test_cases(data.test_cases, data_dir / TESTS_SUBDIR_NAME)

    working_data = CgContributionData(
            title=data.title,
            difficulty=data.difficulty,
            topics=data.topics,
            solution_language=data.solution_language,
        )
    view = CgContributionView(
            puzzle_type=puzzle_type,
            draft=draft,
            ready_for_moderation=ready_for_moderation,
            data=working_data,
        )
    view.save(data_dir / CONTRIBUTION_DATA_FILE_NAME)

    if snapshot_contribution is not None:
        commit_data = CgContributionCommitData(
                contribution=redact_commit_contribution(snapshot_contribution),
                cover_binary_id=snapshot_contribution.last_version.data.cover_binary_id,
                cover_binary_hash=compute_content_hash(cover_bytes) if cover_bytes is not None else None,
            )
        commit_data.save(target_dir / CONTRIBUTION_COMMIT_DATA_FILE_NAME)

    return view


def _read_local_data(contribution_dir: Path, working_data: CgContributionData) -> tuple[CgContributionData, bytes | None]:
    """Read the real content files (sidecar text files, `solution.src`, `tests/`, `cover.png`)
       currently in `contribution_dir/data/` into a full `CgContributionData`--merging in
       `working_data`'s non-file-backed fields (`title`/`difficulty`/`topics`/`solution_language`)
       --and the current `cover.png` bytes, if any. `cover_binary_id` is left `None`; resolving it
       (network/hash-reuse) is `commit()`'s job, not this function's."""
    data_dir = contribution_dir / DATA_SUBDIR_NAME
    solution = _read_sidecar(data_dir / SOLUTION_FILE_NAME)
    cover_path = data_dir / COVER_IMAGE_FILE_NAME
    cover_bytes = cover_path.read_bytes() if cover_path.is_file() else None
    data = dataclasses.replace(
            working_data,
            statement=_read_sidecar(data_dir / STATEMENT_FILE_NAME),
            input_description=_read_sidecar(data_dir / INPUT_DESCRIPTION_FILE_NAME),
            output_description=_read_sidecar(data_dir / OUTPUT_DESCRIPTION_FILE_NAME),
            constraints=_read_sidecar(data_dir / CONSTRAINTS_FILE_NAME),
            stub_generator=_read_sidecar(data_dir / STUB_GENERATOR_FILE_NAME),
            solution=solution,
            test_cases=commit_test_cases(data_dir / TESTS_SUBDIR_NAME),
            cover_binary_id=None,
        )
    return data, cover_bytes


class CgContributionManager:
    """Builds/updates a contribution working directory (`contribution_dir`) against the server,
       via an already-authenticated `CgAsyncClient`."""

    contribution_dir: Path
    client: CgAsyncClient

    def __init__(self, contribution_dir: Path | str, client: CgAsyncClient) -> None:
        self.contribution_dir = Path(contribution_dir)
        self.client = client

    # --- paths -------------------------------------------------------------------------------

    @property
    def identity_file(self) -> Path:
        """Path to this working directory's `contribution.json` (global identity) manifest."""
        return self.contribution_dir / CONTRIBUTION_IDENTITY_FILE_NAME

    @property
    def data_dir(self) -> Path:
        """Path to this working directory's `data/` subdirectory--the actual diffable content
           (see `codingame_client.contribution_manager.layout.DATA_SUBDIR_NAME`)."""
        return self.contribution_dir / DATA_SUBDIR_NAME

    @property
    def contribution_data_file(self) -> Path:
        """Path to this working directory's own `data/contribution-data.json`."""
        return self.data_dir / CONTRIBUTION_DATA_FILE_NAME

    @property
    def tests_dir(self) -> Path:
        """Path to this working directory's `data/tests/` subdirectory."""
        return self.data_dir / TESTS_SUBDIR_NAME

    @property
    def meta_dir(self) -> Path:
        return self.contribution_dir / META_SUBDIR_NAME

    @property
    def last_committed_dir(self) -> Path:
        """Path to this working directory's cached-base view, `.meta/last_committed/`. Nested
           under `.meta/` (rather than a top-level sibling of the working directory's own content)
           since it's internal bookkeeping, not something a user edits directly--consistent with
           `.meta/merge/`."""
        return self.meta_dir / LAST_COMMITTED_SUBDIR_NAME

    @property
    def remote_dir(self) -> Path:
        """Path to this working directory's cached current-server-state view, `.meta/remote/`--
           refreshed by `materialize_remote()` (via `fetch`/`rebase`/`merge_start`/`diff --remote`
           without `--cached`). Persistent, like `last_committed_dir`--frozen for the duration of
           any merge (see `materialize_remote`'s `merge_in_progress` guard)."""
        return self.meta_dir / REMOTE_SUBDIR_NAME

    @property
    def merge_dir(self) -> Path:
        return self.meta_dir / MERGE_SUBDIR_NAME

    @property
    def merge_local_dir(self) -> Path:
        return self.merge_dir / MERGE_LOCAL_SUBDIR_NAME

    @property
    def merge_in_progress(self) -> bool:
        return self.merge_dir.is_dir()

    # --- identity / view load-save -------------------------------------------------------------

    def load_identity(self) -> CgContributionIdentity | None:
        """Load `contribution.json`, or None if this directory has never been imported."""
        if not self.identity_file.is_file():
            return None
        return CgContributionIdentity.load(self.identity_file)

    def load(self) -> CgContributionView:
        """Load `contribution-data.json`.

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
        """
        return CgContributionView.load(self.contribution_data_file)

    def save(self, view: CgContributionView) -> None:
        """Write `view` back to `data/contribution-data.json`, creating `data/` if needed."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        view.save(self.contribution_data_file)

    def load_last_committed(self) -> tuple[CgContributionView, CgContributionCommitData] | None:
        """Load `last_committed/`'s `contribution-data.json`+`contribution-version-data.json`, or
           None if this working directory has never been imported/committed."""
        return _load_view_and_snapshot(self.last_committed_dir)

    def load_remote(self) -> tuple[CgContributionView, CgContributionCommitData] | None:
        """Load `.meta/remote/`'s `contribution-data.json`+`contribution-version-data.json`, or
           None if it hasn't been populated yet (see `materialize_remote`)."""
        return _load_view_and_snapshot(self.remote_dir)

    def _save_last_committed(self, contribution: CgContribution, cover_bytes: bytes | None) -> None:
        version = contribution.last_version
        _materialize_view(
                self.last_committed_dir,
                puzzle_type=contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=version.data,
                cover_bytes=cover_bytes,
                snapshot_contribution=contribution,
                create_solution_symlink=False,
            )

    def _verify_last_committed_cover(self, commit_data: CgContributionCommitData) -> None:
        """Verify `last_committed/data/cover.png`'s content hash still matches
           `commit_data.cover_binary_hash`--the source of truth (see `CgContributionCommitData`'s
           docstring).

        Raises:
            CgContributionManagerError: if a cover is recorded but the cache file is missing or
                                         its hash doesn't match--a corrupted/tampered cache, not a
                                         normal state to silently work around.
        """
        if commit_data.cover_binary_hash is None:
            return
        cover_path = self.last_committed_dir / DATA_SUBDIR_NAME / COVER_IMAGE_FILE_NAME
        if not cover_path.is_file():
            raise CgContributionManagerError(
                    f"{self.last_committed_dir} records a cover image (hash "
                    f"{commit_data.cover_binary_hash!r}) but {cover_path} is missing. Run "
                    "`cg contribution merge discard-server` (or re-import) to rebuild it."
                )
        actual_hash = compute_content_hash(cover_path.read_bytes())
        if actual_hash != commit_data.cover_binary_hash:
            raise CgContributionManagerError(
                    f"{cover_path}'s content hash ({actual_hash!r}) does not match the recorded "
                    f"hash ({commit_data.cover_binary_hash!r}) in {self.last_committed_dir}--the "
                    "cache is corrupted. Run `cg contribution merge discard-server` (or "
                    "re-import) to rebuild it."
                )

    # --- import_ / commit ----------------------------------------------------------------------

    async def import_(
                self,
                contribution_id: CgContributionId,
                *,
                contribution: CgContribution | None = None,
            ) -> CgContributionView:
        """Build (or refresh) this working directory from an existing server-side contribution:
           `findContribution` (unless `contribution` is already given, e.g. by `rebase()`, to
           avoid a redundant call), followed by downloading the cover image if one is set. Also
           refreshes `last_committed/` to match, and writes `contribution.json` (identity) if this
           is a fresh working directory.

           The `tests/` subdirectory is entirely replaced (see `import_test_cases`).

        Raises:
            CgContributionManagerError: if this directory already tracks a *different*
                                         contribution (refuses to silently retarget it), or a
                                         merge is in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before importing."
                )
        identity = self.load_identity()
        if identity is not None and identity.contribution_handle != contribution_id:
            raise CgContributionManagerError(
                    f"{self.identity_file} already tracks contribution "
                    f"{identity.contribution_handle!r}; refusing to import {contribution_id!r} "
                    "into the same directory."
                )
        if contribution is None:
            contribution = await self.client.services.contribution.find_contribution(contribution_id)
        version = contribution.last_version
        data = version.data

        cover_bytes: bytes | None = None
        if data.cover_binary_id is not None:
            download = await self.client.servlets.file_servlet(data.cover_binary_id)
            cover_bytes = download.content

        view = _materialize_view(
                self.contribution_dir,
                puzzle_type=contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=data,
                cover_bytes=cover_bytes,
                snapshot_contribution=None,
                create_solution_symlink=True,
            )
        self.save_identity_if_absent(contribution_id)
        self._save_last_committed(contribution, cover_bytes)
        return view

    def save_identity_if_absent(self, contribution_id: CgContributionId) -> None:
        """Write `contribution.json` if it doesn't already exist (never overwrites--identity is
           constant for a working directory's lifetime)."""
        if self.identity_file.is_file():
            return
        self.contribution_dir.mkdir(parents=True, exist_ok=True)
        CgContributionIdentity(
                schema_version=CONTRIBUTION_SCHEMA_VERSION, contribution_handle=contribution_id,
            ).save(self.identity_file)

    async def commit(self) -> CgContribution:
        """Push this working directory's content to the server via `updateContribution`, updating
           `last_committed/` to reflect the result on success.

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
            CgContributionManagerError: if `puzzle_type` isn't set, or a merge is in progress.
            NotImplementedError: if this working directory has never been associated with a
                                  server-side contribution (submitting a brand-new contribution
                                  isn't supported yet--the protocol for it hasn't been reverse
                                  engineered).
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before committing."
                )
        view = self.load()
        if view.puzzle_type is None:
            raise CgContributionManagerError("Cannot commit: puzzle_type is not set in contribution-data.json.")
        loaded = self.load_last_committed()
        if loaded is None:
            raise NotImplementedError(
                    "Submitting a brand-new contribution (one with no last_committed/) is not yet supported."
                )
        _, commit_data = loaded
        contribution_id = commit_data.contribution_id
        prev_version = commit_data.prev_version

        cover_path = self.data_dir / COVER_IMAGE_FILE_NAME
        cover_binary_id: int | None
        cover_content_hash: str | None
        cover_bytes: bytes | None
        if cover_path.is_file():
            cover_bytes = cover_path.read_bytes()
            cover_content_hash = compute_content_hash(cover_bytes)
            prior_binary_id = commit_data.cover_binary_id
            if cover_content_hash == commit_data.cover_binary_hash and prior_binary_id is not None:
                cover_binary_id = prior_binary_id
            else:
                upload = await self.client.servlets.file_upload(
                        cover_bytes, filename=COVER_IMAGE_FILE_NAME, content_type="image/png")
                cover_binary_id = upload.id
        else:
            cover_binary_id = None
            cover_content_hash = None
            cover_bytes = None

        view_for_commit = self.load()
        local_data, _ = _read_local_data(self.contribution_dir, view_for_commit.data)
        data = dataclasses.replace(local_data, cover_binary_id=cover_binary_id)

        result = await self.client.services.contribution.helper.update_contribution(
                contribution_id,
                view.puzzle_type,
                data,
                view.draft,
                view.ready_for_moderation,
                prev_version,
            )
        result = await self._refresh_active_version(result, contribution_id)

        self._save_last_committed(result, cover_bytes)
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

    # --- materialize remote ------------------------------------------------------------------------

    async def materialize_remote(
                self, target_dir: Path, contribution: CgContribution | None = None,
                *, create_solution_symlink: bool = False,
            ) -> CgContribution:
        """Materialize the "remote" (current server) view into `target_dir`: a fresh
           `findContribution` (unless `contribution` is already given), then write nothing at all
           if `target_dir` already holds a materialization of that exact version (its own cached
           `contribution-version-data.json`, if any, already reports the same version--nothing
           could have changed). Otherwise downloads the cover image, unless its binary ID matches
           either `last_committed/`'s or `target_dir`'s own previous cover--in which case those
           already-known-good bytes are reused instead (binary IDs are as good as a hash for
           content identity once both sides already have one--see `CgContributionCommitData`'s
           docstring), avoiding a redundant download either way.

           Unlike the sacred `last_committed/` cache (see `_verify_last_committed_cover`), a
           corrupt/missing cached cover in `target_dir` itself is never a hard error here--it just
           means that opportunistic reuse is skipped and a fresh copy is downloaded instead
           (self-healing).

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is in progress, or see
                                         `_verify_last_committed_cover`.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before fetching."
                )
        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to diff/rebase/revert/merge against.")
        _, base_commit_data = loaded
        if contribution is None:
            contribution = await self.client.services.contribution.find_contribution(base_commit_data.contribution_id)
        version = contribution.last_version
        data = version.data

        existing = _load_view_and_snapshot(target_dir)
        if existing is not None and existing[1].prev_version == version.version:
            return contribution  # target_dir already reflects this exact version; nothing changed

        new_binary_id = data.cover_binary_id
        cover_bytes: bytes | None
        if new_binary_id is None:
            cover_bytes = None
        elif new_binary_id == base_commit_data.cover_binary_id:
            self._verify_last_committed_cover(base_commit_data)
            cover_path = self.last_committed_dir / DATA_SUBDIR_NAME / COVER_IMAGE_FILE_NAME
            cover_bytes = cover_path.read_bytes() if cover_path.is_file() else None
        elif existing is not None and new_binary_id == existing[1].cover_binary_id \
                and _cover_hash_matches(target_dir, existing[1]):
            cover_bytes = (target_dir / DATA_SUBDIR_NAME / COVER_IMAGE_FILE_NAME).read_bytes()
        else:
            download = await self.client.servlets.file_servlet(new_binary_id)
            cover_bytes = download.content

        _materialize_view(
                target_dir,
                puzzle_type=contribution.contribution_type,
                draft=version.draft if version.draft is not None else True,
                ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                data=data,
                cover_bytes=cover_bytes,
                snapshot_contribution=contribution,
                create_solution_symlink=create_solution_symlink,
            )
        return contribution

    # --- rebase ----------------------------------------------------------------------------------

    async def rebase(self) -> CgRebaseStatus:
        """Detect drift between the server, `last_committed/`, and this working directory's local
           content, and automatically resolve it when that's unambiguous:

           - Server unchanged since `last_committed/`: nothing to do, regardless of local edits
             (`CgRebaseStatus.UP_TO_DATE`).
           - Server changed, local unchanged (matches `last_committed/` exactly): fast-forward--
             refresh the working directory and `last_committed/` to the new server state
             (`CgRebaseStatus.FAST_FORWARDED`).
           - Both changed: a real conflict, left entirely alone (`CgRebaseStatus.CONFLICT`)--use
             `cg contribution diff` to inspect, and `cg contribution merge` to resolve.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is already in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before rebasing."
                )
        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to rebase against.")
        _, base_commit_data = loaded
        self._verify_last_committed_cover(base_commit_data)
        contribution = await self.materialize_remote(self.remote_dir)

        server_changed = any(
                entry.changed
                for entry in diff_two_trees(self.last_committed_dir / DATA_SUBDIR_NAME, self.remote_dir / DATA_SUBDIR_NAME)
            )
        if not server_changed:
            return CgRebaseStatus.UP_TO_DATE

        local_changed = any(
                entry.changed for entry in diff_two_trees(self.last_committed_dir / DATA_SUBDIR_NAME, self.data_dir)
            )
        if not local_changed:
            await self.import_(base_commit_data.contribution_id, contribution=contribution)
            return CgRebaseStatus.FAST_FORWARDED

        return CgRebaseStatus.CONFLICT

    # --- instant, one-shot merge resolutions (no .meta/merge/ state machine involved) ------------

    async def merge_discard_local(self) -> CgContributionView:
        """Discard all local edits: unconditionally replace the working directory (and
           `last_committed/`) with the current server state. Unlike `rebase()`, doesn't check
           whether local actually diverged first--always overwrites. An instant, one-shot
           operation--unlike `merge_start`/`merge_continue`/`merge_abort`, never touches
           `.meta/merge/`.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is already in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it first."
                )
        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to merge against.")
        _, commit_data = loaded
        return await self.import_(commit_data.contribution_id)

    async def merge_discard_server(self) -> CgContributionCommitData:
        """Update `last_committed/` to reflect the current server state, without touching any
           working-directory content files (the opposite of `merge_discard_local`: keep local,
           discard the server's changes as far as tracking is concerned--they'll simply be
           overwritten by the next `commit()`). An instant, one-shot operation--never touches
           `.meta/merge/`.

           A fresh cover download only happens if the server's `cover_binary_id` actually changed
           to a new non-null ID (changing to null just clears the cache; unchanged reuses the
           existing cached bytes).

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is already in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it first."
                )
        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to merge against.")
        _, commit_data = loaded
        contribution = await self.client.services.contribution.find_contribution(commit_data.contribution_id)
        new_binary_id = contribution.last_version.data.cover_binary_id
        old_binary_id = commit_data.cover_binary_id

        cover_bytes: bytes | None
        if new_binary_id == old_binary_id:
            self._verify_last_committed_cover(commit_data)
            cover_path = self.last_committed_dir / DATA_SUBDIR_NAME / COVER_IMAGE_FILE_NAME
            cover_bytes = cover_path.read_bytes() if cover_path.is_file() else None
        elif new_binary_id is None:
            cover_bytes = None
        else:
            download = await self.client.servlets.file_servlet(new_binary_id)
            cover_bytes = download.content

        self._save_last_committed(contribution, cover_bytes)
        loaded_after = self.load_last_committed()
        assert loaded_after is not None
        return loaded_after[1]

    # --- merge state machine ----------------------------------------------------------------------

    async def merge_start(self) -> CgMergeStartResult:
        """Begin (or, if one's already in progress, do nothing and report it) a merge:

           1. Materialize a fresh server fetch into `.meta/remote/` (via `materialize_remote()`--
              note this happens *before* step 3 creates `.meta/merge/`, since `materialize_remote`
              itself refuses to run while a merge is in progress). If the fetched version number
              already matches `last_committed/`'s, there's nothing to merge--return
              `CgMergeStartStatus.UP_TO_DATE` without creating `.meta/merge/` at all (any local
              edits are left exactly as they are, same as before this call).
           2. Snapshot the working directory's current content into `.meta/merge/local/` (creating
              `.meta/merge/`, which is what makes `merge_in_progress` true from here on).
           3. Resolve every file, comparing `last_committed/` (base) / `.meta/merge/local/`
              (local) / `.meta/remote/` (remote): unchanged everywhere, or changed on exactly one
              side -> applied directly to the working directory (a remote-only change is pulled
              in; a local-only change is already there). Both sides changed to the same content ->
              also a no-op. Both sides changed differently (a real conflict): for `cover.png` or
              any other binary content, the working directory's local version is kept as-is
              (recorded in `binary_conflicts`--pull `.meta/remote/<path>` in by hand if you want
              the server's version instead); for text (including `contribution-data.json`/
              `test.json`--see the `tree_diff` module docstring for why that's safe), `diff3 -m`
              conflict-marker output is written into the working-directory file for manual
              resolution (recorded in `text_conflicts`).

           The existing solution symlink (if any) is removed at the start and not recreated until
           `merge_continue()`--during an in-progress merge, `solution_language` itself might be
           part of an unresolved `contribution-data.json` conflict, so there's no reliable
           extension to symlink until that's settled.

           `last_committed/` and `.meta/remote/` are both guaranteed frozen for the whole merge
           (nothing that could refresh either is allowed to run while `merge_in_progress`), so
           they're read directly here rather than copied into merge-specific snapshots.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
        """
        if self.merge_in_progress:
            return CgMergeStartResult(status=CgMergeStartStatus.ALREADY_IN_PROGRESS)

        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to merge against.")
        _, base_commit_data = loaded

        contribution = await self.materialize_remote(self.remote_dir)
        if contribution.last_version.version == base_commit_data.prev_version:
            return CgMergeStartResult(status=CgMergeStartStatus.UP_TO_DATE)

        view = self.load()  # FileNotFoundError propagates if never imported
        local_data, local_cover_bytes = _read_local_data(self.contribution_dir, view.data)
        _materialize_view(
                self.merge_local_dir,
                puzzle_type=view.puzzle_type or "",
                draft=view.draft,
                ready_for_moderation=view.ready_for_moderation,
                data=local_data,
                cover_bytes=local_cover_bytes,
                snapshot_contribution=None,
                create_solution_symlink=False,
            )

        for path in self.contribution_dir.glob("solution.*"):
            if path.is_symlink() and path.name != SOLUTION_FILE_NAME:
                path.unlink()

        base_data_dir = self.last_committed_dir / DATA_SUBDIR_NAME
        local_data_dir = self.merge_local_dir / DATA_SUBDIR_NAME
        remote_data_dir = self.remote_dir / DATA_SUBDIR_NAME

        text_conflicts: list[str] = []
        binary_conflicts: list[str] = []
        for entry in diff_three_trees(base_data_dir, local_data_dir, remote_data_dir):
            status = entry.status
            if status in ("unchanged", "local_changed", "both_changed_same"):
                continue
            target_path = self.data_dir / entry.relative_path
            if status == "remote_changed":
                if entry.remote is None:
                    if target_path.is_file():
                        target_path.unlink()
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(entry.remote)
                continue
            # conflict: both sides changed, differently.
            is_text = all(c is None or looks_like_text(c) for c in (entry.base, entry.local, entry.remote))
            if not is_text:
                binary_conflicts.append(entry.relative_path)  # keep local as-is
                continue
            merged = compute_diff3_merge(
                    local_data_dir / entry.relative_path,
                    base_data_dir / entry.relative_path,
                    remote_data_dir / entry.relative_path,
                    labels=("local", "base", "remote"),
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(merged, encoding="utf-8")
            text_conflicts.append(entry.relative_path)

        return CgMergeStartResult(
                status=CgMergeStartStatus.STARTED,
                text_conflicts=tuple(text_conflicts),
                binary_conflicts=tuple(binary_conflicts),
            )

    def _scan_unresolved_markers(self) -> list[str]:
        """Every diffable text file in the working directory that still has an unresolved
           `diff3` conflict marker--see `_MERGE_MARKER_PREFIX`."""
        unresolved = []
        for rel_path, content in sorted(read_view_files(self.data_dir).items()):
            if not looks_like_text(content):
                continue
            text = content.decode("utf-8", errors="replace")
            if any(line.startswith(_MERGE_MARKER_PREFIX) for line in text.splitlines()):
                unresolved.append(rel_path)
        return unresolved

    def merge_continue(self) -> None:
        """Finish an in-progress merge: verify no unresolved conflict markers remain, promote the
           `.meta/remote/` snapshot captured at `merge_start()` time (frozen ever since, since
           nothing may refresh it while a merge is in progress) to the new `last_committed/`,
           refresh the working directory's solution symlink (in case a resolved
           `contribution-data.json` conflict changed `solution_language`), and remove
           `.meta/merge/`.

           The marker scan is a content-based heuristic, not an authoritative state (unlike git,
           which tracks resolution via index stages, independent of file content--see the
           conversation this design came out of for the full reasoning). In practice this isn't a
           real risk here: `diff3 -m -L local -L base -L remote` marker lines are specific enough
           (`<<<<<<< local`, not just `<<<<<<<`) that an accidental collision with genuine content
           is exceptionally unlikely.

        Raises:
            CgContributionManagerError: if no merge is in progress, or unresolved markers remain.
        """
        if not self.merge_in_progress:
            raise CgContributionManagerError("No merge in progress (run `cg contribution merge` to start one).")
        unresolved = self._scan_unresolved_markers()
        if unresolved:
            raise CgContributionManagerError(
                    "Unresolved conflict markers remain in: " + ", ".join(unresolved) +
                    ". Resolve them, then run `cg contribution merge continue` again."
                )
        if self.last_committed_dir.exists():
            shutil.rmtree(self.last_committed_dir)
        shutil.copytree(self.remote_dir, self.last_committed_dir)
        _cleanup_merge_dir(self)
        view = self.load()
        _refresh_solution_symlink(self.contribution_dir, view.data.solution_language)

    def merge_abort(self) -> None:
        """Abort an in-progress merge: restore the working directory's content from the
           `.meta/merge/local/` snapshot taken at `merge_start()` time (discarding any auto-
           resolution/manual edits made since), and remove `.meta/merge/`. `last_committed/` is
           left untouched--the merge never reached `merge_continue()`, so the base pointer never
           moved.

        Raises:
            CgContributionManagerError: if no merge is in progress.
        """
        if not self.merge_in_progress:
            raise CgContributionManagerError("No merge in progress.")
        preserved = {CONTRIBUTION_IDENTITY_FILE_NAME, META_SUBDIR_NAME}
        for path in list(self.contribution_dir.iterdir()):
            if path.name in preserved:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        for item in self.merge_local_dir.iterdir():
            dest = self.contribution_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        view = self.load()
        _refresh_solution_symlink(self.contribution_dir, view.data.solution_language)
        _cleanup_merge_dir(self)

    # --- revert ------------------------------------------------------------------------------

    def revert(self) -> CgContributionView:
        """Revert this working directory's content to match `last_committed/` (the cached base
           state) exactly--purely local, no network access at all.

           Copies only `last_committed/data/` -> `data/` (never `last_committed/`'s own
           `contribution-version-data.json`, which must never appear in the working directory
           root)--wiping the working directory's own top level first (except the preserved
           identity file and `.meta/`), the same pattern `merge_abort()` uses to restore from
           `.meta/merge/local/`.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is in progress, or see `_verify_last_committed_cover`.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before reverting."
                )
        loaded = self.load_last_committed()
        if loaded is None:
            raise FileNotFoundError(f"{self.last_committed_dir} does not exist--nothing to revert to.")
        view, commit_data = loaded
        self._verify_last_committed_cover(commit_data)
        preserved = {CONTRIBUTION_IDENTITY_FILE_NAME, META_SUBDIR_NAME}
        for path in list(self.contribution_dir.iterdir()):
            if path.name in preserved:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        shutil.copytree(self.last_committed_dir / DATA_SUBDIR_NAME, self.data_dir)
        _refresh_solution_symlink(self.contribution_dir, view.data.solution_language)
        return self.load()


def _load_view_and_snapshot(view_dir: Path) -> tuple[CgContributionView, CgContributionCommitData] | None:
    data_file = view_dir / DATA_SUBDIR_NAME / CONTRIBUTION_DATA_FILE_NAME
    snapshot_file = view_dir / CONTRIBUTION_COMMIT_DATA_FILE_NAME
    if not data_file.is_file() or not snapshot_file.is_file():
        return None
    return CgContributionView.load(data_file), CgContributionCommitData.load(snapshot_file)


def _cleanup_merge_dir(manager: CgContributionManager) -> None:
    shutil.rmtree(manager.merge_dir)
    with contextlib.suppress(OSError):
        manager.meta_dir.rmdir()  # only succeeds if now empty (tidiness, not required for correctness)
