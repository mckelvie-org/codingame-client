"""Filename/directory-name constants for a contribution working directory's on-disk layout,
   shared across `codingame_client.contribution_manager` submodules. Kept separate from
   `manager.py` (which owns the logic that uses these) specifically to avoid a circular import:
   `tree_diff.py` needs some of these names, and `manager.py` needs `tree_diff.py`'s comparison
   functions for the merge state machine.
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
    "LAST_COMMITTED_SUBDIR_NAME",
    "REMOTE_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "MERGE_SUBDIR_NAME",
    "MERGE_LOCAL_SUBDIR_NAME",
]

STATEMENT_FILE_NAME = "statement.cgmd"
INPUT_DESCRIPTION_FILE_NAME = "input_description.cgmd"
OUTPUT_DESCRIPTION_FILE_NAME = "output_description.cgmd"
CONSTRAINTS_FILE_NAME = "constraints.cgmd"
STUB_GENERATOR_FILE_NAME = "stub_generator.cgstub"

SOLUTION_FILE_NAME = "solution.src"
"""The one real solution file, in every materialized view, regardless of language--never varies.
   Deliberately not `.txt`: editors that infer syntax highlighting from a shebang line (e.g. VS
   Code) only bother for extensions they don't already recognize as plain text--`.txt` forces
   plain text with no highlighting, `.src` lets the shebang win. A convenience symlink
   `solution.<ext>` -> `data/solution.src` is additionally maintained at the working directory's
   own root (never inside `data/`, never in any view under `.meta/`) for the common case where the
   language *is* known; it's disposable/regeneratable."""

COVER_IMAGE_FILE_NAME = "cover.png"

DATA_SUBDIR_NAME = "data"
"""Every materialized view's actual diffable content (sidecar files, `solution.src`, `cover.png`,
   `tests/`, `contribution-data.json`) lives under a `data/` subdirectory of the view's root--never
   directly in the root itself. This keeps `data/` *purely* diffable content with no exceptions
   (nothing to exclude--see `tree_diff.py`): the view root itself is reserved for whatever
   non-diffable bookkeeping is specific to that kind of view (`contribution.json` for the working
   directory root, `contribution-version-data.json` for `.meta/last_committed/`/`.meta/remote/`,
   the `solution.<ext>` convenience symlink for the working directory root)--or nothing at all, for
   `.meta/merge/local/`, which has no bookkeeping file of its own."""

LAST_COMMITTED_SUBDIR_NAME = "last_committed"
"""Cached base (last-synced) materialized view, nested under `.meta/` (i.e.
   `.meta/last_committed/`)--internal bookkeeping, not something a user edits directly."""

REMOTE_SUBDIR_NAME = "remote"
"""Cached current-server-state materialized view, nested under `.meta/` (i.e. `.meta/remote/`)--
   refreshed by `cg contribution fetch`/`rebase`/`merge start`, and by `diff --remote` unless
   `--cached` is given. Persistent (unlike the old merge-only `.meta/merge/base|remote/` copies it
   replaces) so it can be inspected/diffed without a merge in progress, and frozen for the
   duration of any merge (nothing may refresh it while one is--see
   `CgContributionManager.merge_in_progress`)."""

META_SUBDIR_NAME = ".meta"
"""Container for internal, always-gitignored bookkeeping state: `last_committed/` (the cached
   base), `remote/` (the cached current server state), and `merge/` (present only while a merge
   is in progress)."""

MERGE_SUBDIR_NAME = "merge"
"""Presence of `.meta/merge/` indicates a merge is in progress; see
   `CgContributionManager.merge_start`/`merge_continue`/`merge_abort`."""

MERGE_LOCAL_SUBDIR_NAME = "local"
