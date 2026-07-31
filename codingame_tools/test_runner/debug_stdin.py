"""python -m codingame_tools.test_runner.debug_stdin INPUT_FILE TARGET_FILE [EXPECTED_OUTPUT_FILE] [--update-expected]

Runs TARGET_FILE in-process (via `runpy.run_path`--not a subprocess) with INPUT_FILE's content
bound to stdin. Meant to be launched directly under a debugger--e.g. from a VS Code
`launch.json` entry with `"module": "codingame_tools.test_runner.debug_stdin"`--not run
standalone for its own sake. `codingame_tools.test_runner.runner.run_solution_locally` is the
subprocess-based, non-debugger equivalent used by `cg puzzle play-local`/`cg contribution
play-local`; this module exists specifically because a subprocess can't be stepped into by a
debugger attached to the parent process, and in-process execution is what makes a breakpoint
placed directly in a solution file actually get hit.

TARGET_FILE is run at exactly the path given, never resolved/realpath'd--so if launch.json
passes VS Code's own `${file}` macro (the path of whichever file/symlink tab was focused when
the debug session started, which is also where a breakpoint would have been set), the debugger's
breakpoint-to-source-file matching lines up automatically no matter how many symlink hops (e.g. a
puzzle working directory's `solution.py` -> `data/solution.src`, or a contribution working
directory's own equivalent symlink) sit between the two--this module never has to know or care.

If EXPECTED_OUTPUT_FILE is given, stdout is tee'd (still streams live to the console exactly as
before--nothing about the interactive debugging experience changes) and, once TARGET_FILE runs to
completion:

- By default, the captured content is *compared* against EXPECTED_OUTPUT_FILE and
  `CgDebugStdinOutputMismatchError` is raised on a mismatch (using the same lenient comparison as
  `play-local`--see `runner.outputs_match`).
- With `--update-expected`, instead of comparing, the captured content *overwrites*
  EXPECTED_OUTPUT_FILE--for accepting a solution's current output as the new known-good baseline
  (e.g. after deliberately changing behavior/input and needing to regenerate the expected output
  rather than hand-editing it). Meaningless for `puzzle_manager` (`.meta/tests/` is downloaded
  server truth, regenerated on every `repair()`--never something to overwrite from a local run),
  but a real, useful mode for `contribution_manager` (`data/tests/.../local|validator/output.txt`
  is author-owned content).

If TARGET_FILE itself raises, that exception propagates as-is and neither comparison nor update is
attempted--you're presumably already looking at why in the debugger at that point.
EXPECTED_OUTPUT_FILE is optional: omit it to just run with some input bound to stdin, with no
assertion/update at the end (`--update-expected` without EXPECTED_OUTPUT_FILE is a usage error--
there's nothing to update).

Deliberately generic and layout-agnostic--nothing here reads `.meta/tests/`, `data/tests/`, or any
other package-specific structure, it just wires stdin to a file and runs a script (paired with an
optional expected-output file, still just a plain path--not resolved from a test index/ordinal).
That's intentional: whatever resolves "which INPUT_FILE/EXPECTED_OUTPUT_FILE" is the caller's
problem--this module isn't tied to `CgPuzzleManager`/`CgContributionManager` in any way. The actual
logic is `run_debug_stdin`, a plain function (not just a CLI entry point)--`codingame_tools.
puzzle_manager.debug`/`codingame_tools.contribution_manager.debug` are thin, package-aware
wrappers that resolve a test index (and, for contributions, a side) into `input_file`/
`target_file`/`expected_output_file` and call it directly, in-process (never as a subprocess--that
would defeat the entire point of this module).
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import runpy
import sys
from pathlib import Path
from typing import TextIO

from .runner import outputs_match

__all__ = ["CgDebugStdinOutputMismatchError", "run_debug_stdin", "main"]


class CgDebugStdinOutputMismatchError(AssertionError):
    """Raised after TARGET_FILE runs to completion if its captured stdout didn't match
       EXPECTED_OUTPUT_FILE (compare mode only--never raised with `--update-expected`)."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        diff = "".join(difflib.unified_diff(
                expected.splitlines(keepends=True), actual.splitlines(keepends=True),
                fromfile="expected", tofile="actual",
            ))
        super().__init__(f"Output did not match expected:\n{diff}")


class _TeeTextIO:
    """A minimal stdout stand-in that writes through to `real` (so console output during an
       interactive debug session is completely unaffected) while also buffering everything into
       `capture` for comparison/update once the run completes."""

    def __init__(self, real: TextIO, capture: io.StringIO) -> None:
        self._real = real
        self._capture = capture

    def write(self, s: str) -> int:
        self._capture.write(s)
        return self._real.write(s)

    def flush(self) -> None:
        self._real.flush()


def run_debug_stdin(
            input_file: Path,
            target_file: Path,
            expected_output_file: Path | None = None,
            *,
            update_expected: bool = False,
        ) -> None:
    """The actual logic behind `python -m codingame_tools.test_runner.debug_stdin`--see the
       module docstring for the full behavior. Callable directly (not just via CLI argv) so
       package-aware wrappers (`codingame_tools.puzzle_manager.debug`/`codingame_tools.
       contribution_manager.debug`) can invoke it in-process after resolving which files to pass,
       without shelling back out to this module as a subprocess.

    Raises:
        ValueError: if `update_expected` is True but `expected_output_file` is None--nothing to
                    update.
        CgDebugStdinOutputMismatchError: in compare mode (the default, when `expected_output_file`
                                          is given), if the captured output didn't match.
    """
    if update_expected and expected_output_file is None:
        raise ValueError("update_expected requires expected_output_file")

    capture = io.StringIO()
    original_stdin = sys.stdin
    original_argv = sys.argv
    try:
        # `runpy.run_path` doesn't sandbox `sys.argv`--left alone, the target script would see
        # our own CLI's argv (e.g. this module's own `--update-expected`, or a package-aware
        # wrapper's ordinal/side arguments) rather than nothing, same as a plain `python
        # target_file` invocation would give it. Confirmed live: a real solution script that
        # itself reads `sys.argv[1]` as an input file path (its own standalone-testing
        # convenience convention) silently misinterpreted one of our own arguments as a path and
        # read its *own source code* as "input" instead of `input_file`.
        sys.argv = [str(target_file)]
        with input_file.open(encoding="utf-8") as input_file_obj:
            sys.stdin = input_file_obj
            if expected_output_file is None:
                runpy.run_path(str(target_file), run_name="__main__")
            else:
                with contextlib.redirect_stdout(_TeeTextIO(sys.stdout, capture)):
                    runpy.run_path(str(target_file), run_name="__main__")
    finally:
        sys.stdin = original_stdin
        sys.argv = original_argv

    if expected_output_file is not None:
        actual = capture.getvalue()
        if update_expected:
            expected_output_file.write_text(actual, encoding="utf-8")
        else:
            expected = expected_output_file.read_text(encoding="utf-8")
            if not outputs_match(actual, expected):
                raise CgDebugStdinOutputMismatchError(expected, actual)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
            prog="python -m codingame_tools.test_runner.debug_stdin",
            description="Run TARGET_FILE in-process with INPUT_FILE's content bound to stdin, "
                        "optionally comparing (or, with --update-expected, overwriting) "
                        "EXPECTED_OUTPUT_FILE from captured stdout.",
        )
    parser.add_argument("input_file", type=Path, metavar="INPUT_FILE")
    parser.add_argument("target_file", type=Path, metavar="TARGET_FILE")
    parser.add_argument("expected_output_file", type=Path, metavar="EXPECTED_OUTPUT_FILE", nargs="?", default=None)
    parser.add_argument(
            "--update-expected", action="store_true",
            help="Overwrite EXPECTED_OUTPUT_FILE with the captured output instead of comparing "
                 "against it.",
        )
    args = parser.parse_args(argv)
    if args.update_expected and args.expected_output_file is None:
        parser.error("--update-expected requires EXPECTED_OUTPUT_FILE")
    run_debug_stdin(
            args.input_file, args.target_file, args.expected_output_file,
            update_expected=args.update_expected,
        )


if __name__ == "__main__":
    main()
