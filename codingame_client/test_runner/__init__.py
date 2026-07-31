"""Package-agnostic local test execution, shared by `codingame_client.puzzle_manager` and
   `codingame_client.contribution_manager`: subprocess-based batch execution
   (`runner.run_solution_locally`) and an in-process, debugger-launchable single-run entry point
   (`python -m codingame_client.test_runner.debug_stdin`--see that module's docstring).

   Nothing here knows about either package's own on-disk test-case layout (`.meta/tests/` vs
   `data/tests/.../local|validator/`)--each package's own `test_cases_dir` module enumerates its
   own test cases and hands this package plain file paths/content.
"""

from __future__ import annotations

from .debug_stdin import CgDebugStdinOutputMismatchError, run_debug_stdin
from .runner import (
    DEFAULT_RUN_TIMEOUT_SECONDS,
    CgLocalRunResult,
    CgLocalRunUnsupportedLanguageError,
    outputs_match,
    run_solution_locally,
)

__all__ = [
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "CgLocalRunResult",
    "CgLocalRunUnsupportedLanguageError",
    "run_solution_locally",
    "outputs_match",
    "CgDebugStdinOutputMismatchError",
    "run_debug_stdin",
]
