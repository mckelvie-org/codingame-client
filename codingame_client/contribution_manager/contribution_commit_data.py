"""Remote commit metadata for the git repo backing `data/` (see `manager`/`git_repo`)--split two
   ways, both built from a `CgContribution` at the moment it's fetched/pushed:

   - `CgContributionCommitMetadata`: the handful of fast facts (contribution ID, version, cover
     binary ID/hash) needed often and cheaply--written as git trailers on every `server`-branch
     commit (see `codingame_client.contribution_manager.layout`'s `TRAILER_*` constants), so a
     `server`-branch commit is self-describing without needing to look anywhere else.

   - `contribution-version-data.json` (built via `redact_commit_contribution`): the *complete*
     redacted `CgContribution`, committed onto the `version-data` orphan branch, one commit per
     server version--kept as a full snapshot rather than a narrower schema (deliberately, same
     rationale as before this was git-backed) so nothing here needs to change if some future need
     for another field shows up. Every field that's duplicated in `CgContributionView`/
     `contribution-data.json`--the diffable content living in `data/`--is redacted to an empty
     placeholder first, including `cover_binary_id` (tracked instead as its own
     `CgContributionCommitMetadata` field/trailer).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from ..client.common.protocol.contribution import CgContribution, CgContributionData, CgContributionId
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "CONTRIBUTION_COMMIT_DATA_FILE_NAME",
    "CgContributionCommitMetadata",
    "redact_commit_contribution",
]

CONTRIBUTION_COMMIT_DATA_FILE_NAME = "contribution-version-data.json"
"""Name of the single file committed onto the `version-data` branch (see
   `codingame_client.contribution_manager.layout.VERSION_DATA_BRANCH_NAME`) at each server version."""


def redact_commit_contribution(contribution: CgContribution) -> CgContribution:
    """Return a copy of `contribution` with every field that's duplicated in
       `CgContributionView`/`contribution-data.json` redacted to an empty placeholder--`draft`,
       `ready_for_moderation`, `contribution_type` (top-level), and `last_version.data` (the full
       content payload, including `cover_binary_id`--tracked separately as
       `CgContributionCommitMetadata.cover_binary_id` instead)--plus `last_version.statement_html`,
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
class CgContributionCommitMetadata(JSONWizardX):
    """The four fast facts about a `server`-branch commit--built from a `CgContribution` at fetch/
       push time, and the single canonical shape both directions of git trailer conversion
       (`layout.TRAILER_*` keys) go through, so there's one definition instead of hand-rolling
       trailer keys ad hoc at each call site."""

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)

    contribution_id: CgContributionId = ""
    """The opaque contribution ID (`CgContribution.public_handle`)."""

    version: int = 0
    """The server version number--passed to `updateContribution`'s idempotency check on the next
       `commit()`."""

    cover_binary_id: int | None = None
    """The binary ID of the cover image as of this commit (`None` if it has none)."""

    cover_binary_hash: str | None = None
    """The SHA256 (hex) content hash of the cover image identified by `cover_binary_id` (`None` if
       there is none)--the source of truth for cover-image identity against the *local* working
       copy (see `CgContribution.cover_binary_id` for why the ID alone isn't enough there). Always
       computed by the caller (from the actual cover bytes) alongside `redact_commit_contribution`,
       not derivable from a `CgContribution` alone--so there's no `from_contribution()` convenience
       constructor here; callers build this directly with all four fields at hand."""
