"""The `contribution.json` manifest schema for a contribution working directory--a local,
   possibly-uncommitted working view of a single contribution, analogous to a git working
   directory backed by a remote repo. See `codingame_client.contribution_manager.manager` for the
   code that builds/consumes this from the server (`import_`/`commit`), and
   `codingame_client.contribution_manager.last_committed` for the separate `last_committed/`
   subdirectory that tracks the base (last-synced) server state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..client.common.protocol.contribution import CgContributionData, CgPuzzleType
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "CONTRIBUTION_FILE_NAME",
    "CgContributionWorkingDir",
]

CONTRIBUTION_FILE_NAME = "contribution.json"
"""Name of the working-directory manifest file, directly inside the contribution directory."""


@dataclass
class CgContributionWorkingDir(JSONWizardX):
    """The `contribution.json` manifest for a contribution working directory: purely local/working
       state. The last-synced server state ("base") lives separately, in `last_committed/`--see
       `codingame_client.contribution_manager.last_committed.CgLastCommittedContribution`--so that
       it can be materialized and diffed uniformly with this file rather than being an embedded
       field here.

       `data` is a working version of `CgContributionData`, with several fields deliberately kept
       always-empty by convention (not schema-enforced) because their real content lives in
       sibling files/directories instead--overwritten from those sources at `commit()` time, so a
       stray hand-edited value here is harmless, just confusing to read:

         - `statement`      -> `statement.cgmd`
         - `input_description` -> `input_description.cgmd`
         - `output_description` -> `output_description.cgmd`
         - `constraints`    -> `constraints.cgmd`
         - `stub_generator` -> `stub_generator.cgstub`
         - `solution`       -> built from the file named by `solution_file`
         - `test_cases`     -> built from the `tests/` subdirectory (see `test_cases_dir`)
         - `cover_binary_id` -> built from `cover.png` (reusing `last_committed/`'s cached
                                `cover_binary_hash` to decide whether a previously-uploaded image
                                can be reused)

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

    solution_file: str | None = None
    """Path, relative to and always inside this working directory (e.g. "solution.py"), to the
       file containing the puzzle's reference solution source code, in any language. `None` if no
       solution has been provided yet. This file is always a real, plain file here--recommended
       way to also access it from elsewhere is a symlink *outside* the working directory pointing
       in at it (that symlink is entirely outside our management--we never see or touch it). The
       reverse (a symlink at this path, pointing out to a real file elsewhere) is also supported,
       relying on one guarantee: as long as `data.solution_language` doesn't change, new content
       is always written by overwriting this path in place, never by deleting and recreating it--
       so a symlink here survives every `import_`/`commit`/`revert` untouched, only its target's
       content changes. That guarantee only breaks when the language actually changes (see below).

       Preserved across `import_`/`revert` as long as its extension still matches
       `data.solution_language`; if the language changes, a fresh default name is generated and
       the old file (or symlink itself, never whatever it points to) is deleted."""

    data: CgContributionData = field(default_factory=lambda: CgContributionData(title=""))
    """The working contribution content--see the class docstring for which fields are real and
       which are always-empty placeholders backed by sibling files/directories instead."""
