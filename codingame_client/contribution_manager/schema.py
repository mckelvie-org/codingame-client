"""The two working-directory manifest files that aren't a `CgContributionCommitData`
   (`codingame_client.contribution_manager.contribution_commit_data`):

   - `contribution.json` (`CgContributionIdentity`): global identity, lives only at the working
     directory's own root (a sibling of `data/`, never inside it). Never part of any materialized
     view--not propagated to `.meta/last_committed/` or `.meta/merge/local/`, never diffed, never
     touched by merge machinery. Its presence is what identifies a directory as a contribution
     working directory at all; most commands (especially the merge state machine) only need this
     file to be valid, never `contribution-data.json`.

   - `contribution-data.json` (`CgContributionView`): the actual per-view materialized content,
     inside a view's `data/` subdirectory (see
     `codingame_client.contribution_manager.layout.DATA_SUBDIR_NAME`)--present in every
     materialized view: the working directory's own `data/`, `.meta/last_committed/data/`,
     `.meta/remote/data/`, and `.meta/merge/local/data/`. Fully diffable, ordinary JSON--if it
     conflicts during a merge, it gets `diff3` conflict markers like any other text file, same as
     everything else; that's safe specifically because `contribution.json` lives outside `data/`
     entirely, so nothing that needs to keep working mid-merge (the merge state machine itself)
     depends on this file being valid JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..client.common.protocol.contribution import CgContributionData, CgContributionId, CgPuzzleType
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "CONTRIBUTION_IDENTITY_FILE_NAME",
    "CONTRIBUTION_DATA_FILE_NAME",
    "CONTRIBUTION_SCHEMA_VERSION",
    "CgContributionIdentity",
    "CgContributionView",
]

CONTRIBUTION_IDENTITY_FILE_NAME = "contribution.json"
"""Name of the global-identity manifest file, directly inside the contribution directory root
   only (never inside `data/`)--never propagated to any materialized view."""

CONTRIBUTION_DATA_FILE_NAME = "contribution-data.json"
"""Name of the per-view materialized-content manifest file, inside every view's `data/`
   subdirectory."""

CONTRIBUTION_SCHEMA_VERSION = 1
"""Current on-disk format version for a contribution working directory, recorded in
   `CgContributionIdentity.schema_version` so a future format change can detect and offer to
   migrate an older working directory."""


@dataclass
class CgContributionIdentity(JSONWizardX):
    """The `contribution.json` manifest: global identity for a contribution working directory,
       constant for its lifetime (never changes across `import_`/`commit`/`merge`/etc.--unlike
       everything else in the working directory, this is not tied to any specific commit/version)."""

    schema_version: int
    """The on-disk format version this working directory was written in--see
       `CONTRIBUTION_SCHEMA_VERSION`."""

    contribution_handle: CgContributionId
    """The opaque contribution ID (`CgContribution.public_handle`) this working directory tracks."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgContributionView(JSONWizardX):
    """The `contribution-data.json` manifest: the materialized content of one view of a
       contribution (the working directory's own local edits, `.meta/last_committed/`'s cached
       base, or a `.meta/merge/` snapshot)--everything needed to `commit()` this view, or to
       compare it against another view.

       `data` is a working version of `CgContributionData`, with several fields deliberately kept
       always-empty by convention (not schema-enforced) because their real content lives in
       sibling files/directories instead--overwritten from those sources when a view is
       materialized, so a stray hand-edited value here is harmless, just confusing to read:

         - `statement`      -> `statement.cgmd`
         - `input_description` -> `input_description.cgmd`
         - `output_description` -> `output_description.cgmd`
         - `constraints`    -> `constraints.cgmd`
         - `stub_generator` -> `stub_generator.cgstub`
         - `solution`       -> `solution.src` (always this exact name--see
                                `codingame_client.contribution_manager.layout.SOLUTION_FILE_NAME`)
         - `test_cases`     -> built from the `tests/` subdirectory (see `test_cases_dir`)
         - `cover_binary_id` -> built from `cover.png`

       All other fields of `data` (`title`, `difficulty`, `topics`, `solution_language`) are used
       normally--there's no sidecar file for them.
    """

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)

    puzzle_type: CgPuzzleType | None = None
    """The contribution type, e.g. "PUZZLE_INOUT". A required top-level parameter to
       `updateContribution`--must be set before `commit()` can succeed."""

    draft: bool = True
    """Whether the version being committed is a private draft. A required top-level parameter to
       `updateContribution`. Defaults to True (the safe default for a working dir that hasn't
       explicitly decided to publish yet)."""

    ready_for_moderation: bool = False
    """Whether the version being committed is being formally submitted for moderation. A required
       top-level parameter to `updateContribution`."""

    data: CgContributionData = field(default_factory=lambda: CgContributionData(title=""))
    """The materialized contribution content--see the class docstring for which fields are real
       and which are always-empty placeholders backed by sibling files/directories instead."""
