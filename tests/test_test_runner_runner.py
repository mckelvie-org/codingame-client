"""Unit tests for codingame_tools.test_runner.runner: the stdout comparison shared by
   puzzle_manager and contribution_manager. Actually running a solution locally is now
   codingame_tools.language.get_language(...).run()/.run_streaming()--see tests/test_language.py
   for that coverage.

Pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

import pytest

from codingame_tools.test_runner.runner import outputs_match

# The comparison's contract is *equivalence with CodinGame's own*, so the table below is a
# transcription of measured server behaviour (2026-08-03), not a set of preferences. Each row was
# produced by writing `actual` to stdout on a real puzzle and reading `CgPlayResult.comparison.
# success` back. Two puzzles were used deliberately: mandelbrot-set-approximation's stored expected
# output has no final newline, cgs-minifier's does, and the rule only falls out of seeing both.
#
# If a row here ever needs changing, re-measure it--don't reason about what "should" be lenient.
MANDELBROT = "          \n      *   \n    ****  \n ******   \n    ****  \n      *   \n          "
CGS = "($a$='hello';print$a$;)\n"


def _rstrip_lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.split("\n"))


SERVER_BEHAVIOUR = [
    # (label, actual, expected, server said)
    ("expected verbatim, unterminated", MANDELBROT, MANDELBROT, True),
    ("one extra newline (what print does)", MANDELBROT + "\n", MANDELBROT, True),
    ("two extra newlines", MANDELBROT + "\n\n", MANDELBROT, False),
    ("per-line trailing whitespace stripped", _rstrip_lines(MANDELBROT), MANDELBROT, False),
    ("trailing whitespace added to every line",
     "\n".join(line + "   " for line in MANDELBROT.split("\n")), MANDELBROT, False),
    ("leading space added to every line",
     "\n".join(" " + line for line in MANDELBROT.split("\n")), MANDELBROT, False),
    ("CRLF line endings", MANDELBROT.replace("\n", "\r\n"), MANDELBROT, False),
    ("a leading blank line", "\n" + MANDELBROT, MANDELBROT, False),
    ("expected verbatim, terminated", CGS, CGS, True),
    ("one newline fewer than expected", CGS[:-1], CGS, True),
    ("one newline more than expected", CGS + "\n", CGS, True),
    ("two newlines more than expected", CGS + "\n\n", CGS, False),
]


@pytest.mark.parametrize(
        ("actual", "expected", "server_accepted"),
        [(a, e, s) for _, a, e, s in SERVER_BEHAVIOUR],
        ids=[label for label, *_ in SERVER_BEHAVIOUR],
    )
def test_matches_measured_server_behaviour(actual: str, expected: str, server_accepted: bool) -> None:
    """Every case the server was actually asked about. A divergence in the *accepting* direction is
       the dangerous one--it means a solution passes locally and fails on submission."""
    assert outputs_match(actual, expected) is server_accepted


def test_trailing_whitespace_is_not_forgiven() -> None:
    """Called out on its own because it's a deliberate reversal: this function used to strip
       per-line trailing whitespace before comparing, which accepted output CodinGame rejects."""
    assert not outputs_match("1 \n2\t\n", "1\n2\n")


def test_the_tolerance_is_a_difference_not_a_cap() -> None:
    """Two trailing newlines are fine when the expected value has one--what matters is the
       difference between them, which is why the rule needed a terminated expected value to pin
       down."""
    assert outputs_match("x\n\n", "x\n")
    assert not outputs_match("x\n\n", "x")


def test_detects_a_real_difference() -> None:
    assert not outputs_match("1\n2\n", "1\n3\n")


def test_empty_outputs() -> None:
    assert outputs_match("", "")
    assert outputs_match("\n", "")
    assert not outputs_match("\n\n", "")
