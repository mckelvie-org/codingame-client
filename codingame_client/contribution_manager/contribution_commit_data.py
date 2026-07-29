"""`contribution-version-data.json` (`CgContributionCommitData`): remote commit metadata for a
   materialized view that originated from the server (`findContribution`/`updateContribution`)--
   `.meta/last_committed/` and `.meta/remote/`. Lives at the *view's root*, as a sibling of `data/`
   (see `codingame_client.contribution_manager.layout.DATA_SUBDIR_NAME`)--never inside `data/`
   itself, and never present in the working directory root or in `.meta/merge/local/` (a plain
   snapshot of local edits, not something the server ever returned, so it has no commit data of
   its own).

   Deliberately just the real `CgContribution` type--rather than a parallel schema tracking only
   the handful of fields (`public_handle`, `last_version.version`, `active_version`) actually
   consumed today--so nothing needs to change here if a future need for some other field shows up.
   It contains *only* remote commit metadata, never diff-relevant content: every field that maps
   onto the sibling `data/contribution-data.json` (see
   `codingame_client.contribution_manager.manager.CgContributionView`)--including
   `cover_binary_id`, tracked here instead as its own explicit field--is redacted to an empty
   placeholder before saving.

   Excluded from diffing entirely by construction--diffing only ever looks at a view's `data/`
   subdirectory (see `tree_diff`), and this file lives outside it--it's bookkeeping, not diffable
   content, and not user-editable.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from ..client.common.protocol.contribution import CgContribution, CgContributionData, CgContributionId
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "CONTRIBUTION_COMMIT_DATA_FILE_NAME",
    "CgContributionCommitData",
    "redact_commit_contribution",
]

CONTRIBUTION_COMMIT_DATA_FILE_NAME = "contribution-version-data.json"
"""Name of the remote-commit-metadata manifest file, at the root of any materialized view that
   originated from the server--a sibling of that view's `data/` subdirectory (which holds the
   corresponding `contribution-data.json`), never inside it."""


def redact_commit_contribution(contribution: CgContribution) -> CgContribution:
    """Return a copy of `contribution` with every field that's duplicated in
       `CgContributionView`/`contribution-data.json` redacted to an empty placeholder--`draft`,
       `ready_for_moderation`, `contribution_type` (top-level), and `last_version.data` (the full
       content payload, including `cover_binary_id`--tracked separately as
       `CgContributionCommitData.cover_binary_id` instead)--plus `last_version.statement_html`,
       which is never needed at all (purely derivative, see its own docstring)."""
    cleaned_version = dataclasses.replace(
            contribution.last_version,
            data=CgContributionData(title=""),
            draft=None,
            ready_for_moderation=None,
            statement_html=None,
        )
    return dataclasses.replace(
            contribution,
            last_version=cleaned_version,
            draft=False,
            ready_for_moderation=False,
            contribution_type="",
        )


@dataclass
class CgContributionCommitData(JSONWizardX):
    """The `contribution-version-data.json` manifest: remote commit metadata only--a redacted
       `CgContribution` (see `redact_commit_contribution`), the cover image's binary ID as of this
       commit, and the locally-computed cover-image content hash (the source of truth for
       cover-image identity against the *local* working copy--see `CgContribution.cover_binary_id`
       for why the ID alone isn't enough there)."""

    contribution: CgContribution
    """The server's `CgContribution`, redacted--see `redact_commit_contribution`. Use
       `.public_handle` for the contribution ID and `.last_version.version` for the version
       number this commit data is for."""

    extra_data: CatchAll = field(default_factory=dict)

    cover_binary_id: int | None = None
    """The binary ID of the cover image as of this commit (`None` if it has none). Tracked here
       rather than left in `contribution.last_version.data` (which is otherwise fully redacted)
       since it's remote commit metadata, not diffable content--the same category as
       `public_handle`/`version`, just specific to the cover image."""

    cover_binary_hash: str | None = None
    """The SHA256 (hex) content hash of the cover image identified by `cover_binary_id` (`None` if
       there is none)."""

    @property
    def contribution_id(self) -> CgContributionId:
        """The opaque contribution ID (`CgContribution.public_handle`) this commit data is for."""
        return self.contribution.public_handle

    @property
    def prev_version(self) -> int:
        """The version number to pass to `updateContribution`'s idempotency check."""
        return self.contribution.last_version.version
