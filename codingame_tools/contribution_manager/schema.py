"""The working-directory root's own manifest (`contribution.json`) and the per-view content
   manifest inside `data/` (`contribution-data.json`):

   - `contribution.json` (`CgContributionIdentity`): global identity, and only that--which
     contribution this directory tracks. Lives only at the working directory's own root (a sibling
     of `data/`, never inside it, and never itself git-tracked as part of `data/`'s content). Its
     presence is what identifies a directory as a contribution working directory at all.

   - `.meta/contribution-meta.json` (`CgContributionMeta`): how the working directory is put
     together (currently just where its git-dir is)--chosen and maintained by this client rather
     than describing the contribution, so it is meta state rather than identity. See
     `codingame_tools.contribution_manager.manager`'s module docstring for the `--git-dir`/
     `--work-tree` layout it selects between.

   - `contribution-data.json` (`CgContributionView`): the actual content manifest, inside `data/`
     (see `codingame_tools.contribution_manager.layout.DATA_SUBDIR_NAME`)--part of `data/`'s
     ordinary git-tracked content, diffed/merged by real git like everything else there.

   - `.meta/contribution-status.json` (`CgContributionStatusCache`): an offline, non-git-tracked
     cache of server metadata that isn't tied to any content version (score/votes/comment count/
     views/moderator approve-reject tallies/etc.)--see that class's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..client.common.protocol.contribution import (
    CgContribution,
    CgContributionData,
    CgContributionId,
    CgContributionModerator,
    CgPuzzleType,
    CgSolutionLanguage,
)
from ..common.dataclass_wizard_x import Alias, CatchAll, CgEpochMillis, JSONWizardX

__all__ = [
    "CONTRIBUTION_IDENTITY_FILE_NAME",
    "CONTRIBUTION_DATA_FILE_NAME",
    "CONTRIBUTION_SCHEMA_VERSION",
    "CgContributionIdentity",
    "CgContributionMeta",
    "CgContributionView",
    "CgContributionStatusCache",
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
class CgContributionSelectedTest(JSONWizardX):
    """`.meta/selected-test.json`: which single test case the debugger should run against.

       See `codingame_tools.puzzle_manager.schema.CgPuzzleSelectedTest` for why this lives in
       `.meta/` rather than as a `pickString` in `launch.json`. A contribution needs a side as well
       as an ordinal, since the same ordinal can hold both a local and a validator test.

       Absent means "no explicit choice", and callers fall back to the first *local* test--the one
       an author is normally iterating on. Validators are the hidden, scoring ones; defaulting to a
       validator would be a surprising thing to land in a debugger."""

    ordinal: str
    """The ordinal directory name, e.g. `"01"`. A sort key, not necessarily a clean integer."""

    side: str
    """`"local"` or `"validator"`."""

    extra_data: CatchAll = field(default_factory=dict)


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


@dataclass
class CgContributionMeta(JSONWizardX):
    """`.meta/contribution-meta.json`: this client's own state about how the working directory is
       put together, as opposed to what it *is* (`contribution.json`) or what it *holds* (`data/`).

       Chosen and maintained entirely by the meta infrastructure, so it belongs here rather than in
       the identity manifest, which describes the contribution itself and is constant for the
       directory's lifetime.

       Not merely a tidiness argument--see `manager`'s "portability contract". `contribution.json`
       and `data/` are the *exportable* state: copy them elsewhere, `repair()`, and you have a
       working directory. So they may hold only facts true of the contribution wherever it is. Where
       the git-dir goes is a fact about *this checkout on this machine*, and two checkouts of one
       contribution can legitimately differ--the same content exported from a standalone directory
       into a colleague's monorepo must come up external rather than embedded. Recorded in
       `contribution.json` it would travel and be wrong on arrival, which is what 1.0.x did.

       Being in `.meta/` makes it disposable, like everything else here--so nothing may depend on
       it surviving. `CgContributionManager.git_dir` treats it as a cached answer and falls back to
       looking for the repository on disk, which is why deleting `.meta/` can never orphan a
       `data/.git`, and why a freshly exported directory with no `.meta/` at all still works (see
       `_resolve_git_dir`)."""

    git_repo: str
    """Where this working directory's git-dir is, relative to the working directory root, in POSIX
       form--either `".meta/.contribution-git"` (external, with `data/` as its work tree) or
       `"data/.git"` (embedded, making `data/` an ordinary git working directory). Decided once at
       `create()`/`import_()` time--see `manager`'s module docstring for how, and why it is not
       re-derived on every command.

       A path rather than a flag because it is read far more often than it is written, and a path
       is directly usable. It is still only ever one of those two values; anything else is not
       something the rest of this package knows how to drive."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgContributionSolutionSnapshot(JSONWizardX):
    """`.meta/solution-snapshot.json`: the starter stub this client last generated into
       `data/solution.src`, and the language it was generated for.

       Records **only generated stubs**, never a real reference solution. Its one job is to answer
       "is `solution.src` still just the placeholder we wrote, or does it hold actual work?"--which
       is what `CgContributionManager.set_language` needs, because switching a contribution's
       language is destructive in a way switching a puzzle's is not.

       A contribution stores exactly one solution server-side, with no per-language history (unlike
       a puzzle--see `CgTestSessionService.get_previous_code_by_language_id`). So there is nothing
       to restore when switching, and the previous solution is gone for good once the next
       `updateContribution` lands. "Matches what the server currently has" deliberately does *not*
       count as safe here for that reason.

       Deliberately not updated by git-driven writes (`merge`, `discard_local`, `rebase`): after any
       of those, `solution.src` holds real content and no longer matches this snapshot, which is
       exactly the answer wanted."""

    solution_language: CgSolutionLanguage
    """The language the stub was generated for. A snapshot whose language no longer matches
       `CgContributionData.solution_language` describes a previous state and must not be trusted."""

    code: str | None
    """The exact stub text written, or `None` when the language had no stub to offer and
       `solution.src` was removed entirely (see
       `CgLanguage.build_contribution_create_stub_source`)."""

    extra_data: CatchAll = field(default_factory=dict)


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
                                `codingame_tools.contribution_manager.layout.SOLUTION_FILE_NAME`)
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


@dataclass
class CgContributionStatusCache(JSONWizardX):
    """The `.meta/contribution-status.json` cache: an offline snapshot of every piece of server
       metadata that is NOT tied to any particular content version--`status`/`status_history`/
       `score`/`up_votes`/`down_votes`/`comment_count`/`views`/`editable`/`active_version`/
       `validate_action`/the moderation-window timestamps (all live on `contribution.last_version`
       or `contribution` itself), plus `moderator_approvals`/`moderator_denials` (from a wholly
       separate endpoint, `Contribution/findContributionModerators`--not part of `CgContribution`
       at all).

       Deliberately NOT git-tracked (see `layout.CONTRIBUTION_STATUS_CACHE_FILE_NAME`)--unlike
       `contribution-data.json`, none of this is diffable/mergeable content, it's just the most
       recent snapshot available, refreshed every time `CgContributionManager.fetch()`/`import_()`/
       `repair()` obtain a fresh `CgContribution` from the server--regardless of whether the
       content version changed, since none of these fields are tied to it (a moderator vote or a
       new comment doesn't bump the content version).

       `contribution` is stored whole and unredacted here (unlike the `version-data` git branch's
       copy, which redacts `draft`/`ready_for_moderation`/`contribution_type`/`last_version.data`
       to keep those out of diffable git history)--this file isn't git-tracked at all, so nothing
       is gained by redacting it, and keeping the full object avoids having to duplicate every
       field name into a narrower cache-specific shape."""

    version: int
    """The content version (`contribution.last_version.version`) as of this refresh--informational
       only; this cache's own fields are current as of `refreshed_at` regardless of whether the
       content version has since moved on."""

    contribution: CgContribution
    """The complete, unredacted `CgContribution` as returned by `findContribution` at
       `refreshed_at`."""

    moderator_approvals: list[CgContributionModerator]
    """Moderators who had cast a `"validate"` (approve) vote as of `refreshed_at`."""

    moderator_denials: list[CgContributionModerator]
    """Moderators who had cast a `"deny"` (reject) vote as of `refreshed_at`."""

    # `_refreshed_at` (below) is an Alias()'d field with no real default--mypy's dataclass plugin
    # still treats any `= Alias(...)` assignment as if it provided one, so (matching every other
    # Alias()'d epoch-millis field in this codebase, e.g. CgAchievement._completion_time) it must
    # be the LAST field before the true defaults (`extra_data` on down), not the first--otherwise
    # mypy flags every genuinely-required field that follows it as a field-ordering error.
    _refreshed_at: CgEpochMillis = Alias("refreshedAt")
    """When this cache was last written."""

    extra_data: CatchAll = field(default_factory=dict)

    @property
    def refreshed_at(self) -> datetime:
        """See the field docstring for `_refreshed_at`. Always UTC."""
        return self._refreshed_at

    @refreshed_at.setter
    def refreshed_at(self, value: datetime) -> None:
        self._refreshed_at = CgEpochMillis.upcast(value)
