"""Unit tests for codingame_tools.test_runner.runner: leniency-aware stdout comparison, shared by
   puzzle_manager and contribution_manager. Actually running a solution locally is now
   codingame_tools.language.get_language(...).run()/.run_streaming()--see tests/test_language.py
   for that coverage.

Pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from codingame_tools.test_runner.runner import outputs_match


def test_outputs_match_exact() -> None:
    assert outputs_match("1\n2\n", "1\n2\n")


def test_outputs_match_ignores_trailing_line_whitespace() -> None:
    assert outputs_match("1 \n2\t\n", "1\n2\n")


def test_outputs_match_ignores_missing_final_newline() -> None:
    assert outputs_match("1\n2", "1\n2\n")


def test_outputs_match_detects_real_difference() -> None:
    assert not outputs_match("1\n2\n", "1\n3\n")
