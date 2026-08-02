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


def _normalize_output(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def outputs_match(actual: str, expected: str) -> bool:
    """Whether `actual` (captured stdout) matches `expected` (a test case's `output.txt`),
       ignoring trailing whitespace per line and a missing/extra final newline--an exact byte
       comparison is too fragile to be useful locally (mirrors typical judge leniency)."""
    return _normalize_output(actual) == _normalize_output(expected)
