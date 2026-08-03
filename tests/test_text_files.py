"""Unit tests for codingame_tools.common.text_files: the server-value <-> local-file final-newline
   conversion.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

import pytest

from codingame_tools.common.text_files import file_to_server_text, server_text_to_file

# Every shape that showed up while surveying 1478 real server values (the pending community-review
# queue plus published community puzzles' test-case files), plus the degenerate ones that didn't.
CORPUS = [
    "",
    "\n",
    "\n\n",
    "abc",
    "abc\n",
    "abc\n\n",
    "3\nG0 XOR A B\n1 0",          # the common shape: multi-line, unterminated
    "4\n(\n$hello$ = 'hello';\n)\n",  # the ~1-in-12 shape: multi-line, terminated
    "  leading and trailing spaces  ",
    "trailing tab\t",
    "\n\n\n\n",
]


@pytest.mark.parametrize("text", CORPUS)
def test_round_trip_is_exact(text: str) -> None:
    """`file_to_server_text(server_text_to_file(s)) == s` for every `s`--the property the whole
       conversion exists to provide, and the one the previous conditional scheme lacked."""
    assert file_to_server_text(server_text_to_file(text)) == text


@pytest.mark.parametrize("text", CORPUS)
def test_repeated_round_trips_never_drift(text: str) -> None:
    """Exactness once isn't enough on its own: the bug this replaced also round-tripped a value
       correctly the *first* time and only eroded on subsequent cycles, so iterate."""
    current = text
    for _ in range(5):
        current = file_to_server_text(server_text_to_file(current))
    assert current == text


@pytest.mark.parametrize("text", CORPUS)
def test_written_files_are_well_formed(text: str) -> None:
    """Every file is either empty or newline-terminated--the reason for the conversion in the first
       place, since anything else is a file that git and editors immediately want to rewrite."""
    content = server_text_to_file(text)
    assert content == "" or content.endswith("\n")


def test_zero_length_is_the_carve_out() -> None:
    """An empty server value stays a genuinely empty file rather than becoming a one-byte one.
       `contribution_manager` spells "no reference solution" as a zero-length `solution.src`, so
       this is load-bearing, not cosmetic."""
    assert server_text_to_file("") == ""
    assert file_to_server_text("") == ""


def test_a_lone_newline_file_decodes_to_empty() -> None:
    """The single place the conversion isn't injective, asserted so it stays a known trade rather
       than becoming a surprise: an empty file and a file holding just a terminator both mean the
       empty string. Only reachable by hand editing--`server_text_to_file` never emits `"\\n"`."""
    assert file_to_server_text("\n") == ""
    assert server_text_to_file("") != "\n"


def test_unterminated_files_are_aliases_not_errors() -> None:
    """A hand-edited file whose last line lacks a terminator means the same thing as the terminated
       one. That collapse is on the file side, which is the harmless side--no server value is
       unrepresentable because of it."""
    assert file_to_server_text("abc") == file_to_server_text("abc\n") == "abc"


@pytest.mark.parametrize("content", ["", "\n", "abc\n", "abc", "abc\n\n"])
def test_canonicalizing_a_file_is_idempotent(content: str) -> None:
    """Round-tripping an arbitrary file through the pair (what happens when a solution's captured stdout
       is accepted as a new expected-output baseline) settles after one pass."""
    once = server_text_to_file(file_to_server_text(content))
    assert server_text_to_file(file_to_server_text(once)) == once
