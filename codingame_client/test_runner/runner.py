"""Runs a solution file against a single test case's input, by shelling out to the appropriate
   interpreter/compiler as a subprocess--the general-purpose case, since only a subprocess can run
   every `CgSolutionLanguage`. (A from-the-same-process, debugger-friendly runner is the separate
   `codingame_client.test_runner.debug_stdin`.)

   Only "Python3" is wired up so far (via `sys.executable`, guaranteeing the same interpreter
   version this client itself runs under, rather than hoping a "python3" on PATH matches)--see
   `_RUN_COMMAND_BUILDERS`. Extending to another language just means adding another entry there;
   nothing else in this module is Python-specific.

   Shared by `codingame_client.puzzle_manager` (`CgPuzzleManager.play_local`) and
   `codingame_client.contribution_manager` (`CgContributionManager.run_local_test`)--nothing here
   is aware of either package's own on-disk layout (`.meta/tests/` vs `data/tests/.../local/`);
   each package's own `test_cases_dir` module enumerates its own test cases and hands this module
   plain `solution_file`/`solution_language`/`input_text` values.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..client.common.protocol.schema import CgSolutionLanguage

__all__ = [
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "CgLocalRunUnsupportedLanguageError",
    "CgLocalRunResult",
    "run_solution_locally",
    "outputs_match",
]

DEFAULT_RUN_TIMEOUT_SECONDS = 10.0
"""Default wall-clock timeout for a single local test run--a solution under active development
   can easily infinite-loop; this keeps a bad run from hanging a batch of runs indefinitely rather
   than reporting it as a (timed-out) failure."""

_RUN_COMMAND_BUILDERS: dict[str, Callable[[Path], list[str]]] = {
    "Python3": lambda solution_file: [sys.executable, str(solution_file)],
}


class CgLocalRunUnsupportedLanguageError(Exception):
    """Raised by `run_solution_locally` for a `solution_language` not yet in
       `_RUN_COMMAND_BUILDERS`."""

    def __init__(self, solution_language: str) -> None:
        self.solution_language = solution_language
        supported = ", ".join(sorted(_RUN_COMMAND_BUILDERS))
        super().__init__(
                f"Local test execution doesn't yet know how to run {solution_language!r} "
                f"solutions (supported so far: {supported})."
            )


@dataclass(frozen=True)
class CgLocalRunResult:
    """The outcome of running a solution file against one test case's input."""

    output: str
    """Everything the solution wrote to stdout."""

    stderr: str
    """Everything the solution wrote to stderr--not treated as failure by itself (a solution may
       legitimately write debug output there), but surfaced for inspection when a run does fail."""

    returncode: int
    """The subprocess's exit code (0 conventionally means "ran without crashing")."""

    timed_out: bool
    """Whether the run was killed for exceeding its timeout (see `DEFAULT_RUN_TIMEOUT_SECONDS`).
       `output`/`stderr` hold whatever was captured before the kill; `returncode` is meaningless
       (always -1) when this is True."""


def run_solution_locally(
            solution_file: Path,
            solution_language: CgSolutionLanguage,
            input_text: str,
            *,
            timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
        ) -> CgLocalRunResult:
    """Run `solution_file` as a subprocess in `solution_language`, feeding `input_text` in as
       stdin and capturing stdout/stderr.

    Raises:
        CgLocalRunUnsupportedLanguageError: if `solution_language` isn't yet supported (see
                                             `_RUN_COMMAND_BUILDERS`).
    """
    build_command = _RUN_COMMAND_BUILDERS.get(solution_language)
    if build_command is None:
        raise CgLocalRunUnsupportedLanguageError(solution_language)
    command = build_command(solution_file)
    try:
        completed = subprocess.run(
                command, input=input_text, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout, check=False,
            )
    except subprocess.TimeoutExpired as e:
        timeout_stdout = e.stdout.decode("utf-8") if isinstance(e.stdout, bytes) else e.stdout
        timeout_stderr = e.stderr.decode("utf-8") if isinstance(e.stderr, bytes) else e.stderr
        return CgLocalRunResult(
                output=timeout_stdout or "", stderr=timeout_stderr or "", returncode=-1, timed_out=True,
            )
    return CgLocalRunResult(
            output=completed.stdout, stderr=completed.stderr, returncode=completed.returncode,
            timed_out=False,
        )


def _normalize_output(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def outputs_match(actual: str, expected: str) -> bool:
    """Whether `actual` (captured stdout) matches `expected` (a test case's `output.txt`),
       ignoring trailing whitespace per line and a missing/extra final newline--an exact byte
       comparison is too fragile to be useful locally (mirrors typical judge leniency)."""
    return _normalize_output(actual) == _normalize_output(expected)
