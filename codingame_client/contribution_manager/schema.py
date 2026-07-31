"""The working-directory root's own manifest (`contribution.json`) and the per-view content
   manifest inside `data/` (`contribution-data.json`):

   - `contribution.json` (`CgContributionIdentity`): global identity plus the (effectively
     constant, once decided) location of this working directory's git-dir--see
     `codingame_client.contribution_manager.manager`'s module docstring for the `--git-dir`/
     `--work-tree` layout this supports. Lives only at the working directory's own root (a sibling
     of `data/`, never inside it, and never itself git-tracked as part of `data/`'s content). Its
     presence is what identifies a directory as a contribution working directory at all.

   - `contribution-data.json` (`CgContributionView`): the actual content manifest, inside `data/`
     (see `codingame_client.contribution_manager.layout.DATA_SUBDIR_NAME`)--part of `data/`'s
     ordinary git-tracked content, diffed/merged by real git like everything else there.
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
       constant for its lifetime (never changes across `import_`/`push`/`merge`/etc.--unlike
       everything else in the working directory, this is not tied to any specific commit/version).

       Exception: `contribution_handle` itself transitions exactly once, from `None` to a real
       value, the first time `CgContributionManager.push()` succeeds against a working directory
       created via `create()` rather than `import_()`--see `push()`'s docstring for why."""

    schema_version: int
    """The on-disk format version this working directory was written in--see
       `CONTRIBUTION_SCHEMA_VERSION`."""

    # `extra_data` is deliberately the first field with a default, same rationale as
    # `CgContributionView.extra_data` below: dataclass_wizard 1.0.0 mis-binds any defaulted field
    # positioned immediately before it (silently, no error) to the CatchAll's own value.
    extra_data: CatchAll = field(default_factory=dict)

    contribution_handle: CgContributionId | None = None
    """The opaque contribution ID (`CgContribution.public_handle`) this working directory
       tracks--`None` if it was `create()`d and has never been successfully `push()`d yet (there's
       no server-side contribution to have a handle for). Also the one fact that decides which of
       `CgContributionManager.repair()`'s two modes applies, and (when set) the one fact that mode
       actually needs--everything else about prior git history is either present (git-dir found
       where recorded) or, if not, deliberately not reconstructed, just re-fetched fresh."""

    git_dir_in_data: bool = False
    """Where this working directory's git-dir lives, decided once at creation time and never
       re-derived afterward (so a git project appearing around this directory *after* creation
       can't cause the git-dir location to be miscomputed for a repo that already exists at a
       fixed spot): `True` -> nested inside `data/` (at `data/.meta/.contribution-git/`, chosen
       when nothing else was already tracking this location); `False` -> external, at
       `<contribution_dir>/.meta/.contribution-git/` (chosen when this directory was already
       inside another git repository at creation time). See `manager`'s module docstring."""


@dataclass
class CgContributionView(JSONWizardX):
    """The `contribution-data.json` manifest: the content of `data/`--everything needed to
       `push()` it, or to compare it against `main`/`server` at any other commit via `git diff`.

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
       `updateContribution`--must be set before `push()` can succeed."""

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
