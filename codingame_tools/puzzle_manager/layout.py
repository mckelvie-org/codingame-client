"""Filename/directory-name constants for a puzzle working directory's on-disk layout--shared
   across `codingame_tools.puzzle_manager` submodules. Deliberately not shared with
   `codingame_tools.contribution_manager.layout`, even though a couple of names coincide (e.g.
   `SOLUTION_FILE_NAME`)--the two packages solve unrelated problems (authoring a contribution vs.
   solving an existing puzzle) and are kept fully independent rather than cross-coupled just to
   save duplicating a few string constants.

   Layout:

       puzzle/
           puzzle.json                 # CgPuzzleIdentity--stable, git-tracked
           solution.<ext>              # convenience symlink -> data/solution.src
           .gitignore                  # contains ".meta/"
           .meta/                      # gitignored--see META_SUBDIR_NAME
               puzzle-server-data.json # CgPuzzleServerData--cache, rebuilt by repair()
               statement.html          # read-only reference, regenerated each import_()/repair()
               stub_generator.cgstub   # read-only reference, regenerated each import_()/repair()
               tests/                  # downloaded test case input/output--see
                                        # codingame_tools.puzzle_manager.test_cases_dir
           data/
               solution.src            # the one real, editable/submittable file
               puzzle-data.json        # CgPuzzleData--user-editable, git-tracked
"""

from __future__ import annotations

__all__ = [
    "DATA_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "GITIGNORE_FILE_NAME",
    "SOLUTION_FILE_NAME",
    "STATEMENT_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
]

DATA_SUBDIR_NAME = "data"
"""The puzzle's user-editable content (`solution.src`, `puzzle-data.json`) lives under a `data/`
   subdirectory of the working directory root."""

META_SUBDIR_NAME = ".meta"
"""Container for gitignored, server-derived cache (`puzzle-server-data.json`) and read-only
   reference files (`statement.html`, `stub_generator.cgstub`)--none of it is user-managed state,
   and none of it is expected to survive a fresh git clone into a different repo (see
   `CgPuzzleManager.repair`, which reconstructs it from `puzzle.json`'s stable `puzzle_id`).
   Always paired with a `.gitignore` (see `GITIGNORE_FILE_NAME`) at the working directory root, so
   it's never accidentally tracked by whatever project ends up tracking the rest of the working
   directory."""

GITIGNORE_FILE_NAME = ".gitignore"
"""Written (containing just `.meta/`) at the working directory root by `import_()`/`repair()`, so
   `.meta/`'s contents can never end up tracked by whatever project comes to track the rest of the
   working directory, now or later."""

SOLUTION_FILE_NAME = "solution.src"
"""The one real, editable/submittable file--never varies. Same rationale as
   `contribution_manager.layout.SOLUTION_FILE_NAME` for the `.src` extension (lets editors that
   infer syntax highlighting from a shebang line win, rather than a recognized-as-plain-text
   extension like `.txt` forcing no highlighting). A convenience symlink `solution.<ext>` ->
   `data/solution.src` is additionally maintained at the working directory's own root (never
   inside `data/`), same as `codingame_tools.contribution_manager`'s--disposable/regeneratable."""

STATEMENT_FILE_NAME = "statement.html"
"""Read-only reference copy of the puzzle's rendered problem statement (see
   `CgTestSessionQuestionDetails.statement`), under `.meta/`--not user-managed state, so it
   doesn't belong in `data/`; regenerated on every `import_()`/`repair()`, never read back or
   diffed; purely for the solver's own convenience (e.g. to reread the problem without a network
   round trip)."""

STUB_GENERATOR_FILE_NAME = "stub_generator.cgstub"
"""Read-only reference copy of the puzzle's stub-generation script (see
   `CgTestSessionQuestionDetails.stub_generator`), under `.meta/`--informational only; this
   package doesn't interpret the stub-generator DSL to produce a real starter `solution.src`,
   unlike `codingame_tools.contribution_manager`'s Python-only trivial stub for *authoring* a new
   contribution (see `CgPuzzleManager.import_`'s docstring)."""
