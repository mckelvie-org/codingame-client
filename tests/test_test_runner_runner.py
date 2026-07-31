"""Unit tests for codingame_client.test_runner.runner: subprocess-based local test execution and
   output comparison. Shared by puzzle_manager and contribution_manager.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
They do spawn real `sys.executable` subprocesses (Python3 is the only supported language so far),
which is the whole point of this module, so no fake/mock is used here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_client.test_runner.runner import (
    CgLocalRunUnsupportedLanguageError,
    outputs_match,
    run_solution_locally,
)


def _write_solution(tmp_path: Path, source: str) -> Path:
    solution_file = tmp_path / "solution.src"
    solution_file.write_text(source)
    return solution_file


# --- run_solution_locally ------------------------------------------------------------------


def test_run_echoes_input_to_output(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "n = int(input())\nprint(n * 2)\n")

    result = run_solution_locally(solution_file, "Python3", "21\n")

    assert result.output == "42\n"
    assert result.returncode == 0
    assert not result.timed_out


def test_run_captures_stderr_without_failing(tmp_path: Path) -> None:
    solution_file = _write_solution(
            tmp_path, "import sys\nprint('debug', file=sys.stderr)\nprint('ok')\n")

    result = run_solution_locally(solution_file, "Python3", "")

    assert result.output == "ok\n"
    assert "debug" in result.stderr
    assert result.returncode == 0


def test_run_reports_nonzero_returncode_on_uncaught_exception(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "raise ValueError('boom')\n")

    result = run_solution_locally(solution_file, "Python3", "")

    assert result.returncode != 0
    assert "ValueError" in result.stderr


def test_run_times_out_on_infinite_loop(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "while True:\n    pass\n")

    result = run_solution_locally(solution_file, "Python3", "", timeout=0.5)

    assert result.timed_out
    assert result.returncode == -1


def test_run_refuses_unsupported_language(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "print('hi')\n")

    with pytest.raises(CgLocalRunUnsupportedLanguageError):
        run_solution_locally(solution_file, "Java", "")


# --- outputs_match ---------------------------------------------------------------------------


def test_outputs_match_exact() -> None:
    assert outputs_match("1\n2\n", "1\n2\n")


def test_outputs_match_ignores_trailing_line_whitespace() -> None:
    assert outputs_match("1 \n2\t\n", "1\n2\n")


def test_outputs_match_ignores_missing_final_newline() -> None:
    assert outputs_match("1\n2", "1\n2\n")


def test_outputs_match_detects_real_difference() -> None:
    assert not outputs_match("1\n2\n", "1\n3\n")
