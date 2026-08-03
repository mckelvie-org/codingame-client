"""Local test-output comparison, shared by `codingame_tools.puzzle_manager` and
   `codingame_tools.contribution_manager`. Actually running a solution locally is
   `codingame_tools.language.get_language(...).run(...)`/`.run_streaming(...)`--see that
   package; this module only keeps `outputs_match`, the leniency-aware stdout comparison used
   after a local run completes.
"""

from __future__ import annotations

__all__ = [
    "outputs_match",
]


def _split_trailing_newlines(text: str) -> tuple[str, int]:
    """`text` with all trailing newlines removed, plus how many there were."""
    body = text.rstrip("\n")
    return body, len(text) - len(body)


def outputs_match(actual: str, expected: str) -> bool:
    """Whether `actual` (captured stdout) matches `expected` (a test case's `output.txt`).

       Deliberately reproduces CodinGame's own comparison rather than being independently lenient:
       **everything is compared exactly, except that the two may differ by one trailing newline in
       either direction.** A local pass that would fail on the server is the worst outcome this
       function can produce, so its job is equivalence, not comfort.

       That one allowance is what makes the whole thing work, and it isn't optional: a test's stored
       expected output usually has *no* final newline (it was typed into a textarea), while every
       language's `print` supplies one, so a byte-exact comparison would fail essentially every test.

       Mapped live against `CgPlayResult.comparison.success` (2026-08-03), across two puzzles chosen
       because one's stored expected output ends in a newline and the other's doesn't:

           expected verbatim                        -> pass
           expected +/- one trailing newline        -> pass
           expected +/- two trailing newlines       -> fail
           trailing whitespace added to every line  -> fail
           per-line trailing whitespace stripped    -> fail
           a leading space added to every line      -> fail
           CRLF line endings                        -> fail
           a leading blank line added               -> fail

       The tolerance is a *difference* of one, not an absolute cap: `expected + "\\n\\n"` fails even
       for a puzzle whose expected value already ends in a newline. Note especially that trailing
       whitespace and CRLF are **not** forgiven--an earlier version of this function normalized both
       and so passed solutions the server rejects."""
    actual_body, actual_newlines = _split_trailing_newlines(actual)
    expected_body, expected_newlines = _split_trailing_newlines(expected)
    return actual_body == expected_body and abs(actual_newlines - expected_newlines) <= 1
