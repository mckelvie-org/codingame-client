"""Filename/directory-name constants for a contribution working directory's on-disk layout, plus
   the git branch/tag/trailer naming for the git repo backing `data/` (see
   `codingame_tools.contribution_manager.git_repo`/`manager`)--shared across
   `codingame_tools.contribution_manager` submodules.
"""

from __future__ import annotations

__all__ = [
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "SOLUTION_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
    "DATA_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "GIT_METADATA_SUBDIR_NAME",
    "CONTRIBUTION_STATUS_CACHE_FILE_NAME",
    "SOLUTION_SNAPSHOT_FILE_NAME",
    "GITIGNORE_FILE_NAME",
    "MAIN_BRANCH_NAME",
    "SERVER_BRANCH_NAME",
    "VERSION_DATA_BRANCH_NAME",
    "SERVER_TAG_PREFIX",
    "VERSION_DATA_TAG_PREFIX",
    "TRAILER_CONTRIBUTION_ID",
    "TRAILER_VERSION",
    "TRAILER_COVER_BINARY_ID",
    "TRAILER_COVER_BINARY_HASH",
]

STATEMENT_FILE_NAME = "statement.cgmd"
INPUT_DESCRIPTION_FILE_NAME = "input_description.cgmd"
OUTPUT_DESCRIPTION_FILE_NAME = "output_description.cgmd"
CONSTRAINTS_FILE_NAME = "constraints.cgmd"
STUB_GENERATOR_FILE_NAME = "stub_generator.cgstub"

SOLUTION_FILE_NAME = "solution.src"
"""The one real solution file--never varies. Deliberately not `.txt`: editors that infer syntax
   highlighting from a shebang line (e.g. VS Code) only bother for extensions they don't already
   recognize as plain text--`.txt` forces plain text with no highlighting, `.src` lets the shebang
   win. A convenience symlink `solution.<ext>` -> `data/solution.src` is additionally maintained
   at the working directory's own root (never inside `data/`) for the common case where the
   language *is* known; it's disposable/regeneratable."""

COVER_IMAGE_FILE_NAME = "cover.png"

DATA_SUBDIR_NAME = "data"
"""The actual contribution content (sidecar files, `solution.src`, `cover.png`, `tests/`,
   `contribution-data.json`) lives under a `data/` subdirectory of the working directory root--
   this is also the git working tree for the `main` branch (see `git_repo`/`manager`). The working
   directory root itself holds only `contribution.json` (identity), the `solution.<ext>`
   convenience symlink, and `.meta/` (bookkeeping)."""

META_SUBDIR_NAME = ".meta"
"""Container for internal bookkeeping--specifically `.contribution-git/` (see
   `GIT_METADATA_SUBDIR_NAME`), when this working directory's git-dir lives outside `data/` (see
   `manager.CgContributionManager.git_dir`). Lives as a sibling of `data/` in that case, or nested
   inside `data/` (i.e. `data/.meta/`) when the git-dir lives *inside* `data/` instead--either way,
   always paired with a `.gitignore` (see `GITIGNORE_FILE_NAME`) in its immediate parent, so it's
   never accidentally picked up by whatever project ends up tracking `data/`."""

GIT_METADATA_SUBDIR_NAME = ".contribution-git"
"""Name of the actual git-dir directory (objects/refs/HEAD/index/config) under `META_SUBDIR_NAME`.
   Deliberately not named `.git`--see `manager`'s module docstring for why nothing inside `data/`
   may ever carry a literal `.git` marker."""

CONTRIBUTION_STATUS_CACHE_FILE_NAME = "contribution-status.json"

SOLUTION_SNAPSHOT_FILE_NAME = "solution-snapshot.json"
"""Name of the `.meta/` file recording the starter stub this client last generated into
   `data/solution.src`--see `CgContributionSolutionSnapshot`."""
"""Name of the offline cache of non-version-tied server metadata (score/votes/comment count/
   views/moderator approve-reject tallies/etc.), under `META_SUBDIR_NAME`--see
   `schema.CgContributionStatusCache`. Deliberately NOT git-tracked (unlike `contribution-data.
   json`, which lives in `data/`)--this is a disposable, opportunistically-refreshed cache, not
   diffable/mergeable content, and none of it is tied to any particular content version."""

GITIGNORE_FILE_NAME = ".gitignore"
"""Written (containing just `.meta/`) at creation time, in whichever directory directly contains
   `META_SUBDIR_NAME`, so `.meta/`'s contents (our own internal git plumbing state) can never end
   up tracked by whatever outer project comes to track the rest of that directory, now or later."""

MAIN_BRANCH_NAME = "main"
"""The user's own working line--see `manager`'s module docstring."""

SERVER_BRANCH_NAME = "server"
"""Mirrors known server state--see `manager`'s module docstring. Its tip is always "the current
   remote"; `git merge-base main server` is always "the last synced point"."""

VERSION_DATA_BRANCH_NAME = "version-data"
"""Orphan branch, one commit per server version, holding only `contribution-version-data.json`--
   see `contribution_commit_data`."""

SERVER_TAG_PREFIX = "server."
"""`server.<version>` tags a `SERVER_BRANCH_NAME` commit by the server version it represents."""

VERSION_DATA_TAG_PREFIX = "version-data."
"""`version-data.<version>` tags a `VERSION_DATA_BRANCH_NAME` commit the same way."""

TRAILER_CONTRIBUTION_ID = "Cg-Contribution-Id"
TRAILER_VERSION = "Cg-Version"
TRAILER_COVER_BINARY_ID = "Cg-Cover-Binary-Id"
TRAILER_COVER_BINARY_HASH = "Cg-Cover-Binary-Hash"
"""Git trailer keys on every `SERVER_BRANCH_NAME` commit--see
   `contribution_commit_data.CgContributionCommitMetadata`, which is the single canonical shape
   these are built from/parsed back into."""
