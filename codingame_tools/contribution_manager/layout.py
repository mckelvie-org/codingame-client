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
    "ASSETS_SUBDIR_NAME",
    "COVER_PLACEHOLDER_ASSET_NAME",
    "DATA_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "CONTRIBUTION_META_FILE_NAME",
    "GIT_METADATA_SUBDIR_NAME",
    "CONTRIBUTION_STATUS_CACHE_FILE_NAME",
    "SELECTED_TEST_FILE_NAME",
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

ASSETS_SUBDIR_NAME = "assets"
"""Package-data subdirectory of `codingame_tools.contribution_manager` holding static files shipped
   in the wheel (currently just the cover placeholder)."""

COVER_PLACEHOLDER_ASSET_NAME = "cover-placeholder.png"
"""The "under construction" 1920x1080 cover `create()` seeds, as package data.

   Baked rather than rendered at runtime: it's identical for every contribution, so generating it
   on demand would make every consumer of this library carry a 15 MB compiled imaging dependency to
   produce a constant. Regenerate with `bin/gen-default-cover-image` (see `scripts/gen_cover_placeholder.py`,
   which owns the only Pillow dependency and explains why the image is deliberately ugly)."""

COVER_IMAGE_FILE_NAME = "cover.png"

DATA_SUBDIR_NAME = "data"
"""The actual contribution content (sidecar files, `solution.src`, `cover.png`, `tests/`,
   `contribution-data.json`) lives under a `data/` subdirectory of the working directory root--
   this is also the git working tree for the `main` branch (see `git_repo`/`manager`). The working
   directory root itself holds only `contribution.json` (identity), the `solution.<ext>`
   convenience symlink, and `.meta/` (bookkeeping)."""

META_SUBDIR_NAME = ".meta"
"""Container for this client's own generated bookkeeping--the status cache, the selected test, the
   solution snapshot, the generated editor/devcontainer files, and (in one of the two layouts) the
   git-dir itself.

   **Always `<contribution_dir>/.meta`, a sibling of `data/`--never inside it**, in either layout.
   `data/` holds user state and nothing else: it is the git working tree, it is what gets pushed to
   CodinGame, and it is the only part worth backing up. Generated, disposable, rebuildable-by-
   `repair()` state has no business in there. Paired with a `.gitignore` (see `GITIGNORE_FILE_NAME`)
   in `<contribution_dir>`, so it's never picked up by whatever outer project comes to track the
   working directory."""

GIT_METADATA_SUBDIR_NAME = ".contribution-git"
"""Name of the git-dir directory (objects/refs/HEAD/index/config) under `META_SUBDIR_NAME`, used in
   the **external** layout--i.e. `<contribution_dir>/.meta/.contribution-git/`, with `data/` as its
   work tree via `--git-dir`/`--work-tree` decoupling.

   Deliberately not named `.git`: in this layout the working directory sits inside some outer git
   project, and a `.git` marker anywhere under `<contribution_dir>` would trip that project's own
   embedded-repository detection. See `DATA_GIT_DIR_NAME` for the other layout, and `manager`'s
   module docstring for how one is chosen."""

DATA_GIT_DIR_NAME = ".git"
"""Name of the git-dir in the **embedded** layout, i.e. `data/.git`--which makes `data/` a
   perfectly ordinary git working directory the user can drive with plain `git` commands.

   Chosen when nothing was already tracking the working directory at creation time, and recorded in
   `.meta/contribution-meta.json` (see `schema.CgContributionMeta.git_repo`). Only the git-dir ever
   moves between layouts: `.meta/` stays at `<contribution_dir>/.meta` in both (see
   `META_SUBDIR_NAME`)."""

SELECTED_TEST_FILE_NAME = "selected-test.json"
"""Name of `.meta/`'s selected-test file--see `CgContributionSelectedTest`."""

CONTRIBUTION_META_FILE_NAME = "contribution-meta.json"
"""Name of the `.meta/` file recording how this working directory is put together--currently just
   where its git-dir is. See `schema.CgContributionMeta`."""

CONTRIBUTION_STATUS_CACHE_FILE_NAME = "contribution-status.json"
"""Name of the offline cache of non-version-tied server metadata (score/votes/comment count/
   views/moderator approve-reject tallies/etc.), under `META_SUBDIR_NAME`--see
   `schema.CgContributionStatusCache`. Deliberately NOT git-tracked (unlike `contribution-data.
   json`, which lives in `data/`)--this is a disposable, opportunistically-refreshed cache, not
   diffable/mergeable content, and none of it is tied to any particular content version."""

SOLUTION_SNAPSHOT_FILE_NAME = "solution-snapshot.json"
"""Name of the `.meta/` file recording the starter stub this client last generated into
   `data/solution.src`--see `CgContributionSolutionSnapshot`."""

GITIGNORE_FILE_NAME = ".gitignore"
"""Written (containing just `.meta/`) at creation time in `<contribution_dir>`, which is where
   `META_SUBDIR_NAME` always lives, so `.meta/`'s contents (this client's generated state) can never
   end up tracked by whatever outer project comes to track the working directory, now or later.

   Written unconditionally, in both git-dir layouts. In the external layout there is an outer
   project tracking this directory *today*; in the embedded one there is not, but there may well be
   later, and a `.gitignore` costs nothing until then."""

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
