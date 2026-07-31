"""Unit tests for codingame_tools.test_runner.debug_stdin: in-process, debugger-launchable
   single-run entry point (stdin binding, tee'd stdout capture, compare-or-update-expected-output).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
Runs `main()` in-process (that's the whole point of the module), capturing real process
stdout/stdin via monkeypatch/capsys rather than spawning a subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_tools.test_runner.debug_stdin import CgDebugStdinOutputMismatchError, main


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def test_binds_stdin_and_streams_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_file = _write(tmp_path / "input.txt", "21\n")
    solution_file = _write(tmp_path / "solution.src", "n = int(input())\nprint(n * 2)\n")

    main([str(input_file), str(solution_file)])

    assert capsys.readouterr().out == "42\n"


def test_propagates_target_exception_untouched(tmp_path: Path) -> None:
    input_file = _write(tmp_path / "input.txt", "")
    solution_file = _write(tmp_path / "solution.src", "raise ValueError('boom')\n")

    with pytest.raises(ValueError, match="boom"):
        main([str(input_file), str(solution_file)])


# --- compare mode (default, with EXPECTED_OUTPUT_FILE) --------------------------------------


def test_compare_mode_passes_silently_on_match(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_file = _write(tmp_path / "input.txt", "21\n")
    solution_file = _write(tmp_path / "solution.src", "n = int(input())\nprint(n * 2)\n")
    expected_file = _write(tmp_path / "output.txt", "42\n")

    main([str(input_file), str(solution_file), str(expected_file)])

    assert capsys.readouterr().out == "42\n"  # still streamed live--tee, not swallowed
    assert expected_file.read_text() == "42\n"  # untouched


def test_compare_mode_raises_on_mismatch_but_still_streams_output(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    input_file = _write(tmp_path / "input.txt", "21\n")
    solution_file = _write(tmp_path / "solution.src", "n = int(input())\nprint(n * 3)\n")
    expected_file = _write(tmp_path / "output.txt", "42\n")

    with pytest.raises(CgDebugStdinOutputMismatchError) as exc_info:
        main([str(input_file), str(solution_file), str(expected_file)])

    assert capsys.readouterr().out == "63\n"
    assert exc_info.value.expected == "42\n"
    assert exc_info.value.actual == "63\n"
    assert expected_file.read_text() == "42\n"  # never overwritten in compare mode


# --- update mode (--update-expected) ---------------------------------------------------------


def test_update_mode_overwrites_expected_from_actual_output(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    input_file = _write(tmp_path / "input.txt", "21\n")
    solution_file = _write(tmp_path / "solution.src", "n = int(input())\nprint(n * 2)\n")
    expected_file = _write(tmp_path / "output.txt", "stale wrong value\n")

    main([str(input_file), str(solution_file), str(expected_file), "--update-expected"])

    assert capsys.readouterr().out == "42\n"
    assert expected_file.read_text() == "42\n"


def test_update_mode_requires_expected_output_file(tmp_path: Path) -> None:
    input_file = _write(tmp_path / "input.txt", "")
    solution_file = _write(tmp_path / "solution.src", "print('hi')\n")

    with pytest.raises(SystemExit):
        main([str(input_file), str(solution_file), "--update-expected"])
