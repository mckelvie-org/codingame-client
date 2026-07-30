"""`CgContributionManager`: builds a contribution working directory from an existing server-side
   contribution (`import_`), pushes a working directory's content back to the server (`commit`),
   and reconciles local/server drift (`rebase`, `fetch`, and the `merge_start`/`merge_continue`/
   `merge_abort` state machine)--backed by a real git repository whose working tree is `data/`.

   Three branches (see `codingame_client.contribution_manager.layout` for the exact names):

   - `main`: the user's own line--`data/` is always `main`'s checkout. Commits here are optional/
     user-initiated for the user's own benefit, except a few points where this class also commits
     automatically (a successful `commit()`, a `rebase()` fast-forward, `merge_discard_local`)--see
     each method's docstring.
   - `server`: mirrors known server state. Every commit carries git trailers (contribution ID,
     version, cover binary ID/hash--see `contribution_commit_data.CgContributionCommitMetadata`)
     and a `server.<version>` tag. Its tip is always "the current remote"; `git merge-base main
     server` is always "the last point `main` synced with the server"--no separate last-committed/
     remote cache needed, it falls out of branch topology for free.
   - `version-data`: an orphan branch (unrelated tree history), one commit per server version,
     holding just `contribution-version-data.json` (see `contribution_commit_data`)--the complete
     redacted `CgContribution`, kept in full rather than a narrower schema so nothing here needs to
     change if some future need for another field shows up.

   `server`/`version-data` are never checked out--every write to them goes through
   `git_repo.CgGitRepo`'s plumbing (a scratch index, or a single-blob tree for `version-data`),
   never touching `HEAD`, the real index, or anything under `data/`. This is deliberate: `data/`
   must always and only ever reflect `main`'s real content.

   The repo's actual git-dir (objects/refs/HEAD/index/config) is kept *outside* `data/`'s tracked
   content, via `--git-dir`/`--work-tree` decoupling (see `git_repo`)--so a `data/`-containing
   directory can also be tracked normally by whatever outer project the user keeps it in, without
   `data/` ever carrying a `.git` marker that would trip that outer project's own embedded-
   repository detection. Where the git-dir actually lives is decided once, at `import_()` time (see
   `CgContributionIdentity.git_dir_in_data`), and never re-derived afterward.
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
from ..client.common.protocol.schema import cg_solution_language_to_extension
from ..client.common.raw_client import compute_content_hash
from .contribution_commit_data import (
    CONTRIBUTION_COMMIT_DATA_FILE_NAME,
    CgContributionCommitMetadata,
    redact_commit_contribution,
)
from .git_repo import CgGitError, CgGitRepo, init_repo, is_inside_existing_repo
from .layout import (
    CONSTRAINTS_FILE_NAME,
    COVER_IMAGE_FILE_NAME,
    DATA_SUBDIR_NAME,
    GIT_METADATA_SUBDIR_NAME,
    GITIGNORE_FILE_NAME,
    INPUT_DESCRIPTION_FILE_NAME,
    MAIN_BRANCH_NAME,
    META_SUBDIR_NAME,
    OUTPUT_DESCRIPTION_FILE_NAME,
    SERVER_BRANCH_NAME,
    SERVER_TAG_PREFIX,
    SOLUTION_FILE_NAME,
    STATEMENT_FILE_NAME,
    STUB_GENERATOR_FILE_NAME,
    TRAILER_CONTRIBUTION_ID,
    TRAILER_COVER_BINARY_HASH,
    TRAILER_COVER_BINARY_ID,
    TRAILER_VERSION,
    VERSION_DATA_BRANCH_NAME,
    VERSION_DATA_TAG_PREFIX,
)
from .schema import (
    CONTRIBUTION_DATA_FILE_NAME,
    CONTRIBUTION_IDENTITY_FILE_NAME,
    CONTRIBUTION_SCHEMA_VERSION,
    CgContributionIdentity,
    CgContributionView,
)
from .test_cases_dir import TESTS_SUBDIR_NAME, commit_test_cases, import_test_cases

__all__ = [
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "SOLUTION_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
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


class CgContributionManagerError(Exception):
    """Raised for contribution-manager-level errors not better represented by a more specific
       exception (e.g. attempting to `commit()` without a `puzzle_type` set, or an operation that
       refuses because a merge is in progress)."""


class CgRebaseStatus(str, Enum):
    """The outcome of `CgContributionManager.rebase()`."""

    UP_TO_DATE = "up_to_date"
    """`server` hasn't advanced since `main` last synced with it (its tip already equals
       `git merge-base main server`)--nothing to do, regardless of whether `main`/the working
       directory have uncommitted edits."""

    FAST_FORWARDED = "fast_forwarded"
    """`server` advanced, but `main` had no edits since it last synced (`main`'s tip still equals
       the old merge-base)--fast-forward: `main` gets a new commit matching `server`'s new tip."""

    CONFLICT = "conflict"
    """Both `server` and `main` have diverged since they last synced--nothing was changed. Use
       `cg contribution diff` to inspect, and `cg contribution merge` to resolve."""


class CgMergeStartStatus(str, Enum):
    """The outcome of `CgContributionManager.merge_start()`."""

    STARTED = "started"
    """A real `git merge server` was attempted. If `text_conflicts`/`binary_conflicts` are both
       empty, it already completed (git commits automatically when there's nothing left
       unresolved)--`merge_in_progress` is already `False` again, no `merge_continue()` needed or
       possible. Otherwise, resolve the conflicts and run `merge_continue()`."""

    ALREADY_IN_PROGRESS = "already_in_progress"
    """`merge_start()` is idempotent--if a merge is already in progress (`MERGE_HEAD` exists), it
       leaves it completely untouched rather than erroring or restarting it."""

    UP_TO_DATE = "up_to_date"
    """`server`'s tip already equals `git merge-base main server`--nothing to merge. Consistent
       with `CgRebaseStatus.UP_TO_DATE`."""


@dataclasses.dataclass(frozen=True)
class CgMergeStartResult:
    """The outcome of `CgContributionManager.merge_start()`."""

    status: CgMergeStartStatus

    text_conflicts: tuple[str, ...] = ()
    """Relative paths where git left `<<<<<<<`-style conflict markers for manual resolution."""

    binary_conflicts: tuple[str, ...] = ()
    """Relative paths where both sides changed differently but the content isn't text--git's own
       default behavior for a binary conflict is to leave `main`'s (local) version as-is, no
       markers; pull `.git show server:<path>` (or `cg contribution git show server:<path>`) by
       hand if you want the server's version instead."""


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


def _refresh_solution_symlink(contribution_dir: Path, solution_language: str | None) -> None:
    """Remove any existing `solution.<ext>` convenience symlink at `contribution_dir`'s root, then
       recreate one pointing at `data/solution.src` if that file actually exists and
       `solution_language` maps to a known extension. Never touches `solution.src` itself."""
    for path in contribution_dir.glob("solution.*"):
        if path.is_symlink() and path.name != SOLUTION_FILE_NAME:
            path.unlink()
    if not (contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME).is_file():
        return
    extension = cg_solution_language_to_extension(solution_language) if solution_language else None
    if extension is None:
        return
    link_name = f"solution.{extension}"
    if link_name == SOLUTION_FILE_NAME:
        return
    (contribution_dir / link_name).symlink_to(f"{DATA_SUBDIR_NAME}/{SOLUTION_FILE_NAME}")


def _write_meta_gitignore(parent_dir: Path) -> None:
    """Write `parent_dir/.gitignore` containing `.meta/`, so `.meta/`'s contents (our own internal
       git plumbing state--see `META_SUBDIR_NAME`/`GIT_METADATA_SUBDIR_NAME`) can never end up
       tracked by whatever project comes to track the rest of `parent_dir`, now or later."""
    (parent_dir / GITIGNORE_FILE_NAME).write_text(f"{META_SUBDIR_NAME}/\n")


def _materialize_data(
            target_dir: Path,
            *,
            puzzle_type: CgPuzzleType,
            draft: bool,
            ready_for_moderation: bool,
            data: CgContributionData,
            cover_bytes: bytes | None,
            git_dir_in_data: bool,
        ) -> CgContributionView:
    """Write one view's content directly into `target_dir`: sidecar text files, `solution.src`,
       `cover.png`, `tests/`, `contribution-data.json`, and (if `git_dir_in_data`) `.gitignore`.
       `target_dir` is whatever the caller wants--`self.data_dir` (the real working tree) for
       `import_()`, or a throwaway staging directory for `fetch()`'s `server` tree-building (see
       `CgGitRepo.write_tree_from_dir`)--this function itself has no opinion about which.

       `git_dir_in_data` must be threaded through here (rather than writing `.gitignore` once,
       only in `import_()`) so that *every* tree ever committed onto `server`--not just the first
       one--includes it when the git-dir actually lives under `data/`. Otherwise a later
       `checkout_all()` landing on a `.gitignore`-less `server` commit would delete the file from
       disk, and the very next `git clean -fd` would then delete `.meta/` (the git-dir itself,
       unprotected once nothing excludes it)--confirmed by direct testing.

    Returns:
        The `CgContributionView` that was written to `target_dir/contribution-data.json`.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    if git_dir_in_data:
        _write_meta_gitignore(target_dir)

    _write_sidecar(target_dir / STATEMENT_FILE_NAME, data.statement)
    _write_sidecar(target_dir / INPUT_DESCRIPTION_FILE_NAME, data.input_description)
    _write_sidecar(target_dir / OUTPUT_DESCRIPTION_FILE_NAME, data.output_description)
    _write_sidecar(target_dir / CONSTRAINTS_FILE_NAME, data.constraints)
    _write_sidecar(target_dir / STUB_GENERATOR_FILE_NAME, data.stub_generator)
    _write_sidecar(target_dir / SOLUTION_FILE_NAME, data.solution)

    cover_path = target_dir / COVER_IMAGE_FILE_NAME
    if cover_bytes is not None:
        cover_path.write_bytes(cover_bytes)
    elif cover_path.is_file():
        cover_path.unlink()

    import_test_cases(data.test_cases, target_dir / TESTS_SUBDIR_NAME)

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
    view.save(target_dir / CONTRIBUTION_DATA_FILE_NAME)
    return view


def _read_local_data(data_dir: Path, working_data: CgContributionData) -> tuple[CgContributionData, bytes | None]:
    """Read the real content files (sidecar text files, `solution.src`, `tests/`, `cover.png`)
       currently in `data_dir` into a full `CgContributionData`--merging in `working_data`'s
       non-file-backed fields (`title`/`difficulty`/`topics`/`solution_language`)--and the current
       `cover.png` bytes, if any. `cover_binary_id` is left `None`; resolving it (network/hash-
       reuse) is `commit()`'s job, not this function's."""
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


def _metadata_to_trailers(metadata: CgContributionCommitMetadata) -> dict[str, str]:
    trailers = {
            TRAILER_CONTRIBUTION_ID: metadata.contribution_id,
            TRAILER_VERSION: str(metadata.version),
        }
    if metadata.cover_binary_id is not None:
        trailers[TRAILER_COVER_BINARY_ID] = str(metadata.cover_binary_id)
    if metadata.cover_binary_hash is not None:
        trailers[TRAILER_COVER_BINARY_HASH] = metadata.cover_binary_hash
    return trailers


def _trailers_to_metadata(trailers: dict[str, str]) -> CgContributionCommitMetadata:
    return CgContributionCommitMetadata(
            contribution_id=trailers.get(TRAILER_CONTRIBUTION_ID, ""),
            version=int(trailers.get(TRAILER_VERSION, "0")),
            cover_binary_id=int(trailers[TRAILER_COVER_BINARY_ID]) if TRAILER_COVER_BINARY_ID in trailers else None,
            cover_binary_hash=trailers.get(TRAILER_COVER_BINARY_HASH),
        )


def _looks_like_text(content: bytes) -> bool:
    """Same heuristic git and most other tools use: binary content almost always contains a NUL
       byte within the first few KB; text content essentially never does."""
    return b"\x00" not in content[:8192]


class CgContributionManager:
    """Builds/updates a contribution working directory (`contribution_dir`) against the server,
       via an already-authenticated `CgAsyncClient`. See the module docstring for the git repo
       this is backed by."""

    contribution_dir: Path
    client: CgAsyncClient

    def __init__(self, contribution_dir: Path | str, client: CgAsyncClient) -> None:
        # Always resolved to an absolute path: git_repo.py's subprocess calls set `cwd` to
        # `git_dir`/`work_tree` themselves (see CgGitRepo._run), so a relative `contribution_dir`
        # here would make `--git-dir=`/`--work-tree=` (built from it) resolve against the *wrong*
        # cwd inside git's own subprocess--not the caller's original cwd--confirmed live (`cg
        # contribution import ... contribution` from a repo root failed `git init` outright, since
        # the relative `--git-dir=contribution/.meta/...` was interpreted relative to
        # `contribution/data`, not the original cwd).
        self.contribution_dir = Path(contribution_dir).resolve()
        self.client = client

    # --- paths -------------------------------------------------------------------------------

    @property
    def identity_file(self) -> Path:
        """Path to this working directory's `contribution.json` (global identity) manifest."""
        return self.contribution_dir / CONTRIBUTION_IDENTITY_FILE_NAME

    @property
    def data_dir(self) -> Path:
        """Path to this working directory's `data/` subdirectory--`main`'s git working tree."""
        return self.contribution_dir / DATA_SUBDIR_NAME

    @property
    def contribution_data_file(self) -> Path:
        return self.data_dir / CONTRIBUTION_DATA_FILE_NAME

    @property
    def tests_dir(self) -> Path:
        return self.data_dir / TESTS_SUBDIR_NAME

    def _git_dir_for(self, git_dir_in_data: bool) -> Path:
        root = self.data_dir if git_dir_in_data else self.contribution_dir
        return root / META_SUBDIR_NAME / GIT_METADATA_SUBDIR_NAME

    @property
    def git_dir(self) -> Path:
        """Path to this working directory's git-dir--see the module docstring for the two
           possible locations, and `CgContributionIdentity.git_dir_in_data` for which one this
           working directory actually uses (decided once, at `import_()` time).

        Raises:
            FileNotFoundError: if this working directory has never been imported--nothing to
                                derive it from.
        """
        identity = self.load_identity()
        if identity is None:
            raise FileNotFoundError(f"{self.identity_file} does not exist--this working directory has never been imported.")
        return self._git_dir_for(identity.git_dir_in_data)

    @property
    def git_repo(self) -> CgGitRepo:
        return CgGitRepo(self.git_dir, self.data_dir)

    @property
    def merge_in_progress(self) -> bool:
        return self.git_repo.merge_head_exists()

    def server_metadata(self) -> CgContributionCommitMetadata | None:
        """The `CgContributionCommitMetadata` (version, cover info) at `server`'s current tip, or
           None if this working directory has never been imported. Public specifically so the CLI
           can display version numbers without reaching into `git_repo`/trailer-parsing details."""
        server_sha = self.git_repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_sha is None:
            return None
        return _trailers_to_metadata(self.git_repo.read_trailers(server_sha))

    # --- identity / view load-save -------------------------------------------------------------

    def load_identity(self) -> CgContributionIdentity | None:
        """Load `contribution.json`, or None if this directory has never been imported."""
        if not self.identity_file.is_file():
            return None
        return CgContributionIdentity.load(self.identity_file)

    def load(self) -> CgContributionView:
        """Load `data/contribution-data.json`.

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
        """
        return CgContributionView.load(self.contribution_data_file)

    def save(self, view: CgContributionView) -> None:
        """Write `view` back to `data/contribution-data.json`, creating `data/` if needed."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        view.save(self.contribution_data_file)

    def _save_identity(self, contribution_id: CgContributionId, *, git_dir_in_data: bool) -> None:
        """Write `contribution.json` if it doesn't already exist (never overwrites--identity is
           constant for a working directory's lifetime)."""
        if self.identity_file.is_file():
            return
        self.contribution_dir.mkdir(parents=True, exist_ok=True)
        CgContributionIdentity(
                schema_version=CONTRIBUTION_SCHEMA_VERSION, contribution_handle=contribution_id,
                git_dir_in_data=git_dir_in_data,
            ).save(self.identity_file)

    # --- server-branch commit helper (shared by import_/fetch/commit) --------------------------

    def _record_server_commit(
                self, repo: CgGitRepo, tree: str, contribution: CgContribution,
                cover_bytes: bytes | None, message: str,
            ) -> str:
        """Commit `tree` onto `server` (trailers + `server.<version>` tag), and record the
           corresponding `version-data` commit alongside it. Returns the new `server` commit SHA.
        """
        version = contribution.last_version
        metadata = CgContributionCommitMetadata(
                contribution_id=contribution.public_handle, version=version.version,
                cover_binary_id=version.data.cover_binary_id,
                cover_binary_hash=compute_content_hash(cover_bytes) if cover_bytes is not None else None,
            )
        parent = repo.resolve_ref(SERVER_BRANCH_NAME)
        parents = [parent] if parent is not None else []
        sha = repo.commit_tree(tree, parents, message, trailers=_metadata_to_trailers(metadata))
        repo.update_ref(f"refs/heads/{SERVER_BRANCH_NAME}", sha)
        repo.tag(f"{SERVER_TAG_PREFIX}{version.version}", sha)

        redacted = redact_commit_contribution(contribution)
        blob = repo.write_blob((redacted.saves() + "\n").encode("utf-8"))
        vd_tree = repo.write_tree_single_file(CONTRIBUTION_COMMIT_DATA_FILE_NAME, blob)
        vd_parent = repo.resolve_ref(VERSION_DATA_BRANCH_NAME)
        vd_parents = [vd_parent] if vd_parent is not None else []
        vd_sha = repo.commit_tree(vd_tree, vd_parents, message)
        repo.update_ref(f"refs/heads/{VERSION_DATA_BRANCH_NAME}", vd_sha)
        repo.tag(f"{VERSION_DATA_TAG_PREFIX}{version.version}", vd_sha)

        return sha

    # --- import_ / commit ----------------------------------------------------------------------

    async def import_(
                self,
                contribution_id: CgContributionId,
                *,
                contribution: CgContribution | None = None,
            ) -> CgContributionView:
        """Build this working directory from an existing server-side contribution:
           `findContribution` (unless `contribution` is already given), downloading the cover
           image if one is set, then initializing the git repo with a single shared root commit
           on both `main` and `server` (so `git merge-base main server` starts out meaningful),
           plus the corresponding `version-data` commit. Writes `contribution.json` (deciding and
           recording `git_dir_in_data`) if this is a fresh working directory.

           Also doubles as the *rehydration* entry point: if `contribution.json` and `data/`
           already exist (e.g. from cloning an outer project that tracks them) but the git-dir
           itself is missing (e.g. because it was deliberately outer-gitignored), this re-runs the
           same initialization *without* overwriting `data/`'s already-on-disk content for `main`--
           only `server`/`version-data` are seeded fresh from the current server state. There's no
           attempt to reconstruct the *true* historical sync point in this case--nothing durable
           survives to reconstruct it from; `main` and `server` simply start sharing a root again,
           from right now.

        Raises:
            CgContributionManagerError: if this directory already tracks a *different*
                                         contribution, or already has a git repository.
        """
        identity = self.load_identity()
        if identity is not None and identity.contribution_handle != contribution_id:
            raise CgContributionManagerError(
                    f"{self.identity_file} already tracks contribution "
                    f"{identity.contribution_handle!r}; refusing to import {contribution_id!r} "
                    "into the same directory."
                )
        rehydrating = identity is not None
        git_dir_in_data = identity.git_dir_in_data if identity is not None else not is_inside_existing_repo(self.contribution_dir)
        git_dir = self._git_dir_for(git_dir_in_data)
        if git_dir.is_dir():
            raise CgContributionManagerError(
                    f"{git_dir} already exists--this working directory has already been imported "
                    "(see `cg contribution git` to inspect it directly)."
                )

        if contribution is None:
            contribution = await self.client.services.contribution.find_contribution(contribution_id)
        version = contribution.last_version
        data = version.data

        cover_bytes: bytes | None = None
        if data.cover_binary_id is not None:
            download = await self.client.servlets.file_servlet(data.cover_binary_id)
            cover_bytes = download.content

        if not rehydrating:
            _materialize_data(
                    self.data_dir,
                    puzzle_type=contribution.contribution_type,
                    draft=version.draft if version.draft is not None else True,
                    ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                    data=data,
                    cover_bytes=cover_bytes,
                    git_dir_in_data=git_dir_in_data,
                )
            if not git_dir_in_data:
                _write_meta_gitignore(self.contribution_dir)
            self._save_identity(contribution_id, git_dir_in_data=git_dir_in_data)
            _refresh_solution_symlink(self.contribution_dir, data.solution_language)

        init_repo(git_dir, self.data_dir)
        repo = CgGitRepo(git_dir, self.data_dir)
        repo.set_head(MAIN_BRANCH_NAME)

        tree = repo.write_tree_from_worktree()
        message = "Rehydrate from server" if rehydrating else "Import from server"
        server_sha = self._record_server_commit(repo, tree, contribution, cover_bytes, f"{message} (version {version.version})")
        repo.reset_index_to(server_sha)

        return self.load()

    async def commit(self) -> CgContribution:
        """Push this working directory's content to the server via `updateContribution`, updating
           `server`/`version-data` to reflect the result on success, then auto-committing `main`
           to match (its content already matches what was just pushed, by construction).

        Raises:
            FileNotFoundError: if this working directory hasn't been imported/initialized yet.
            CgContributionManagerError: if `puzzle_type` isn't set, or a merge is in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before committing."
                )
        view = self.load()
        if view.puzzle_type is None:
            raise CgContributionManagerError("Cannot commit: puzzle_type is not set in contribution-data.json.")

        repo = self.git_repo
        server_sha = repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_sha is None:
            raise FileNotFoundError(f"{self.git_dir} has no {SERVER_BRANCH_NAME} branch--nothing to commit against.")
        current_metadata = _trailers_to_metadata(repo.read_trailers(server_sha))
        contribution_id = current_metadata.contribution_id
        prev_version = current_metadata.version

        cover_path = self.data_dir / COVER_IMAGE_FILE_NAME
        cover_binary_id: int | None
        cover_bytes: bytes | None
        if cover_path.is_file():
            cover_bytes = cover_path.read_bytes()
            cover_content_hash = compute_content_hash(cover_bytes)
            if cover_content_hash == current_metadata.cover_binary_hash and current_metadata.cover_binary_id is not None:
                cover_binary_id = current_metadata.cover_binary_id
            else:
                upload = await self.client.servlets.file_upload(
                        cover_bytes, filename=COVER_IMAGE_FILE_NAME, content_type="image/png")
                cover_binary_id = upload.id
        else:
            cover_binary_id = None
            cover_bytes = None

        local_data, _ = _read_local_data(self.data_dir, view.data)
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

        tree = repo.write_tree_from_worktree()
        server_sha = self._record_server_commit(
                repo, tree, result, cover_bytes, f"Push to server (version {result.last_version.version})")
        # main's ref moves directly onto server's new commit (not a separate sibling commit with
        # matching content)--deliberately, so `git merge-base main server` still equals server's
        # tip afterward. A sibling commit here (e.g. via commit_worktree()) would have the *same*
        # tree but a *different* SHA (different parent/message/trailers), leaving merge-base stuck
        # at the pre-push point and making the next rebase()/merge_start() wrongly see "local
        # changed" even though content-wise nothing has, confirmed by direct testing. Uses
        # reset_index_to() rather than a raw update_ref(), so the real index (never touched by
        # write_tree_from_worktree()'s scratch-index tree build) stays in sync with main's new
        # tip too--otherwise a later real `git merge` (merge_start()) reads a stale index.
        repo.reset_index_to(server_sha)
        return result

    async def _refresh_active_version(self, result: CgContribution, contribution_id: CgContributionId) -> CgContribution:
        """`updateContribution`'s response has been confirmed live to report a stale
           `active_version` (lagging one version behind `last_version.version` in that same
           response), apparently because the server finishes activating the new version slightly
           asynchronously--see `CgContribution.active_version`'s docstring. This re-fetches via
           `findContribution`, polling briefly (a few seconds, best-effort) until `active_version`
           catches up to the version just submitted.

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

    # --- fetch -------------------------------------------------------------------------------

    async def fetch(self) -> CgContribution:
        """Refresh `server`'s tip from a fresh `findContribution`. A no-op (no new commit) if the
           version hasn't changed. Never touches `main`, the working tree, or the real index--the
           fetched content is staged into a throwaway temp directory purely to build a tree object
           from, so this is safe to call regardless of what's currently on disk in `data/`.

           Reuses the previous cover image's bytes (read straight out of the object database, via
           `server`'s current tip) rather than re-downloading, if its binary ID is unchanged;
           self-heals (re-downloads) rather than raising if that reuse ever turns out to be stale/
           corrupted--this cache is opportunistic, not sacred.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before fetching."
                )
        identity = self.load_identity()
        assert identity is not None  # merge_in_progress above already required a loadable git_dir

        repo = self.git_repo
        server_sha = repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_sha is None:
            raise FileNotFoundError(f"{self.git_dir} has no {SERVER_BRANCH_NAME} branch--nothing to fetch against.")
        current_metadata = _trailers_to_metadata(repo.read_trailers(server_sha))

        contribution = await self.client.services.contribution.find_contribution(current_metadata.contribution_id)
        if contribution.last_version.version == current_metadata.version:
            return contribution  # server's tip already reflects this exact version

        version = contribution.last_version
        data = version.data
        new_binary_id = data.cover_binary_id
        cover_bytes: bytes | None
        if new_binary_id is None:
            cover_bytes = None
        elif new_binary_id == current_metadata.cover_binary_id:
            cached = repo.read_file_at(SERVER_BRANCH_NAME, COVER_IMAGE_FILE_NAME)
            if cached is not None and compute_content_hash(cached) == current_metadata.cover_binary_hash:
                cover_bytes = cached
            else:
                download = await self.client.servlets.file_servlet(new_binary_id)
                cover_bytes = download.content
        else:
            download = await self.client.servlets.file_servlet(new_binary_id)
            cover_bytes = download.content

        with tempfile.TemporaryDirectory(prefix="cg-contribution-fetch-") as tmp:
            staging = Path(tmp)
            _materialize_data(
                    staging,
                    puzzle_type=contribution.contribution_type,
                    draft=version.draft if version.draft is not None else True,
                    ready_for_moderation=version.ready_for_moderation if version.ready_for_moderation is not None else False,
                    data=data,
                    cover_bytes=cover_bytes,
                    git_dir_in_data=identity.git_dir_in_data,
                )
            tree = repo.write_tree_from_dir(staging)
        self._record_server_commit(repo, tree, contribution, cover_bytes, f"Fetch from server (version {version.version})")
        return contribution

    # --- rebase ----------------------------------------------------------------------------------

    async def rebase(self) -> CgRebaseStatus:
        """Detect drift between `server` and `main`, and automatically resolve it when that's
           unambiguous:

           - `server` unchanged since `main` last synced: nothing to do, regardless of local edits
             (`CgRebaseStatus.UP_TO_DATE`).
           - `server` changed, `main` unchanged since it last synced: fast-forward--`main` gets a
             new commit matching `server`'s new tip (`CgRebaseStatus.FAST_FORWARDED`).
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
        repo = self.git_repo
        base_before = repo.merge_base(MAIN_BRANCH_NAME, SERVER_BRANCH_NAME)
        if base_before is None:
            raise FileNotFoundError(f"{self.git_dir} has no shared history between main/server--nothing to rebase against.")

        await self.fetch()

        server_after = repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_after == base_before:
            return CgRebaseStatus.UP_TO_DATE
        assert server_after is not None  # can't have changed away from a real SHA to nothing

        main_sha = repo.resolve_ref(MAIN_BRANCH_NAME)
        if main_sha == base_before:
            # A *true* fast-forward: main's ref moves directly onto server's tip, same as real
            # git's own definition--no new commit created. checkout_all() still needs to run to
            # bring the working tree/index along with it.
            repo.checkout_all(SERVER_BRANCH_NAME)
            repo.update_ref(f"refs/heads/{MAIN_BRANCH_NAME}", server_after)
            _refresh_solution_symlink(self.contribution_dir, self.load().data.solution_language)
            return CgRebaseStatus.FAST_FORWARDED

        return CgRebaseStatus.CONFLICT

    # --- instant, one-shot merge resolutions (no merge state machine involved) -----------------

    async def merge_discard_local(self) -> CgContributionView:
        """Discard all local edits: unconditionally fetch, then move `main`'s ref directly onto
           `server`'s new tip (same as `git reset --hard server`--no new commit, and deliberately
           *not* a new commit with matching content either: a sibling commit here would leave
           `git merge-base main server` stuck at the old sync point instead of advancing to
           server's tip, making the next `rebase()`/`merge_start()` wrongly see "local changed"
           even though nothing would be, confirmed by direct testing--see `commit()`'s docstring
           for the same reasoning). Any local commits `main` had are not deleted, just no longer
           reachable from `main` itself--recoverable via `main`'s reflog for as long as it lasts.
           Unlike `rebase()`, doesn't check whether local actually diverged first--always
           overwrites. Instant--never touches `MERGE_HEAD`.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is already in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it first."
                )
        await self.fetch()
        repo = self.git_repo
        server_sha = repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_sha is None:
            raise FileNotFoundError(f"{self.git_dir} has no {SERVER_BRANCH_NAME} branch--nothing to discard local changes to.")
        repo.checkout_all(SERVER_BRANCH_NAME)
        repo.update_ref(f"refs/heads/{MAIN_BRANCH_NAME}", server_sha)
        _refresh_solution_symlink(self.contribution_dir, self.load().data.solution_language)
        return self.load()

    async def merge_discard_server(self) -> CgContribution:
        """Update `server` to reflect the current server state, without touching `main`/the
           working tree at all--just `fetch()` under a different name, kept as its own method for
           CLI-naming continuity with the old design (where `last_committed`/`remote` were
           distinct concepts this bridged; they no longer are).

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is already in progress.
        """
        return await self.fetch()

    # --- merge state machine ----------------------------------------------------------------------

    async def merge_start(self) -> CgMergeStartResult:
        """Begin (or, if one's already in progress, do nothing and report it) a merge:

           1. `fetch()` (refuses if a merge is already in progress--checked first, so this never
              runs in that case).
           2. If `server`'s tip already equals `git merge-base main server`, there's nothing to
              merge (`CgMergeStartStatus.UP_TO_DATE`).
           3. Otherwise, a real `git merge server` against the working tree. If it completes
              cleanly (including a trivial fast-forward), git has already committed the result--
              `merge_in_progress` is `False` again, nothing more to do. If it stops with
              conflicts, `text_conflicts`/`binary_conflicts` (split by content--see
              `_looks_like_text`) list the affected paths; resolve them (by hand, or `cg
              contribution merge interactive`) and run `merge_continue()`.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
        """
        if self.merge_in_progress:
            return CgMergeStartResult(status=CgMergeStartStatus.ALREADY_IN_PROGRESS)

        repo = self.git_repo
        await self.fetch()

        base = repo.merge_base(MAIN_BRANCH_NAME, SERVER_BRANCH_NAME)
        server_sha = repo.resolve_ref(SERVER_BRANCH_NAME)
        if server_sha == base:
            return CgMergeStartResult(status=CgMergeStartStatus.UP_TO_DATE)

        clean = repo.merge_branch(SERVER_BRANCH_NAME)
        if clean:
            return CgMergeStartResult(status=CgMergeStartStatus.STARTED)

        conflicts = repo.status_conflicts()
        text_conflicts: list[str] = []
        binary_conflicts: list[str] = []
        for rel_path in conflicts:
            content = (self.data_dir / rel_path).read_bytes() if (self.data_dir / rel_path).is_file() else b""
            (text_conflicts if _looks_like_text(content) else binary_conflicts).append(rel_path)
        return CgMergeStartResult(
                status=CgMergeStartStatus.STARTED,
                text_conflicts=tuple(text_conflicts),
                binary_conflicts=tuple(binary_conflicts),
            )

    def merge_continue(self) -> None:
        """Finish an in-progress merge: stage everything (refusing first if a still-unmerged path
           still has a leftover `<<<<<<<` marker--see `CgGitRepo.merge_continue`) and commit.
           Refreshes the solution symlink afterward (a resolved `contribution-data.json` conflict
           may have changed `solution_language`).

        Raises:
            CgContributionManagerError: if no merge is in progress, or (wrapping git's own error)
                                         if unresolved conflict markers remain.
        """
        if not self.merge_in_progress:
            raise CgContributionManagerError("No merge in progress (run `cg contribution merge` to start one).")
        try:
            self.git_repo.merge_continue()
        except CgGitError as e:
            raise CgContributionManagerError(str(e)) from e
        _refresh_solution_symlink(self.contribution_dir, self.load().data.solution_language)

    def merge_abort(self) -> None:
        """Abort an in-progress merge: restore `main`'s pre-merge working tree state and discard
           `MERGE_HEAD`. `server` is left untouched--the merge never reached `merge_continue()`, so
           nothing about it was ever recorded anywhere.

        Raises:
            CgContributionManagerError: if no merge is in progress.
        """
        if not self.merge_in_progress:
            raise CgContributionManagerError("No merge in progress.")
        self.git_repo.merge_abort()
        _refresh_solution_symlink(self.contribution_dir, self.load().data.solution_language)

    # --- revert ------------------------------------------------------------------------------

    def revert(self) -> CgContributionView:
        """Revert this working directory's content to match `server`'s current tip exactly--
           purely local, no network access at all. Resets both the index and working tree (via
           `CgGitRepo.checkout_all`, i.e. `git read-tree --reset -u`--`git checkout <ref> -- .`
           would *not* remove a file that exists locally but not in `server`'s tree, confirmed by
           direct testing), without moving `main`'s ref or creating a commit--if `main` had local
           commits beyond the last sync, this discards them from the working tree too (matching
           the old `revert()`'s "match the last synced state exactly" contract), but they remain
           recoverable via `main`'s own history, since this never does a hard reset of the ref
           itself.

        Raises:
            FileNotFoundError: if this working directory has never been imported/committed.
            CgContributionManagerError: if a merge is in progress.
        """
        if self.merge_in_progress:
            raise CgContributionManagerError(
                    "A merge is in progress (see `cg contribution merge continue`/`abort`)--"
                    "resolve or abort it before reverting."
                )
        repo = self.git_repo
        if repo.resolve_ref(SERVER_BRANCH_NAME) is None:
            raise FileNotFoundError(f"{self.git_dir} has no {SERVER_BRANCH_NAME} branch--nothing to revert to.")
        repo.checkout_all(SERVER_BRANCH_NAME)
        _refresh_solution_symlink(self.contribution_dir, self.load().data.solution_language)
        return self.load()
