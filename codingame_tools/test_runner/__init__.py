"""Package-agnostic local test support, shared by `codingame_tools.puzzle_manager` and
   `codingame_tools.contribution_manager`: output comparison (`runner.outputs_match`) and an
   in-process, debugger-launchable single-run entry point
   (`python -m codingame_tools.test_runner.debug_stdin`--see that module's docstring). Actually
   running a solution locally is `codingame_tools.language.get_language(...).run(...)`, not this
   package.

   Nothing here knows about either package's own on-disk test-case layout (`.meta/tests/` vs
   `data/tests/.../local|validator/`)--each package's own `test_cases_dir` module enumerates its
   own test cases and hands this package plain file paths/content.
"""

from __future__ import annotations

from .debug_stdin import CgDebugStdinOutputMismatchError, run_debug_stdin
from .runner import outputs_match

__all__ = [
    "outputs_match",
    "CgDebugStdinOutputMismatchError",
    "run_debug_stdin",
]
