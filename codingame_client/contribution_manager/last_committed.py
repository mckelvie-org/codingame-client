"""The `last_committed/` subdirectory of a contribution working directory: a cached record of the
   server-side contribution state as of the last successful `import_`/`commit`/`merge`--the "base"
   for 3-way comparisons against the current server state ("remote") and the working directory's
   own content ("local"). See `codingame_client.contribution_manager.manager` for how this is
   built/consumed, and `codingame_client.contribution_manager.tree_diff` for how it's compared.

   Kept as a separate file/subdirectory (rather than embedded in `contribution.json`, as in an
   earlier version of this design) specifically so it can be treated uniformly with `contribution.json`
   itself when materializing directory trees for diffing--see `CgContributionManager.materialize_base`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..client.common.protocol.contribution import CgContribution, CgContributionId
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "LAST_COMMITTED_SUBDIR_NAME",
    "LAST_COMMITTED_CONTRIBUTION_FILE_NAME",
    "LAST_COMMITTED_COVER_FILE_NAME",
    "CgLastCommittedContribution",
]

LAST_COMMITTED_SUBDIR_NAME = "last_committed"
"""Name of the subdirectory (within a contribution working directory) holding the cached base
   state. Absent entirely for a working directory that has never been imported/committed."""

LAST_COMMITTED_CONTRIBUTION_FILE_NAME = "contribution.json"
"""Name of the manifest file within `last_committed/`."""

LAST_COMMITTED_COVER_FILE_NAME = "cover.png"
"""Name of the cached cover-image file within `last_committed/`, if any. A cache only--
   `cover_binary_hash` (not this file's bytes) is the source of truth for cover-image identity
   comparisons; this file exists so a cover can still be recovered/diffed even if the server has
   since garbage-collected the binary ID it's not otherwise attached to."""


@dataclass
class CgLastCommittedContribution(JSONWizardX):
    """The cached record of the server-side contribution state as of the last successful
       `import_`/`commit`/`merge`. Stored at `last_committed/contribution.json`; the file simply
       doesn't exist for a working directory that has never been associated with a server-side
       contribution."""

    contribution: CgContribution
    """The full `findContribution` (or, immediately after a normal `commit()`, `updateContribution`)
       response, as of the last sync--with `last_version.statement_html` always nulled out (see
       `CgContributionWorkingDir`'s former docstring for why) and `active_version` refreshed to be
       accurate (see `CgContributionManager._refresh_active_version`)."""

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)

    cover_binary_hash: str | None = None
    """The SHA256 (hex) content hash of `contribution`'s cover image (`None` if it has none). This
       is the source of truth for cover-image identity comparisons against the *local* working
       copy (which has no server-assigned binary ID to compare directly until it's uploaded)--see
       the module docstring on `LAST_COMMITTED_COVER_FILE_NAME`. Comparisons against the *remote*
       (current server) state should compare `cover_binary_id` values directly instead--binary IDs
       are as good as a hash for content-identity purposes there, since both sides already have a
       real server-assigned ID."""

    @property
    def contribution_id(self) -> CgContributionId:
        """The opaque contribution ID (`CgContribution.public_handle`) this working directory is
           tracking."""
        return self.contribution.public_handle

    @property
    def prev_version(self) -> int:
        """The version number to pass to `updateContribution`'s idempotency check."""
        return self.contribution.last_version.version
