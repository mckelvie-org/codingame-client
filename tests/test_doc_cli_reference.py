"""Tests that keep `doc/` honest about the CLI.

Two separate jobs, both cheap and offline:

1. The generated command reference under `doc/cli/reference/` is regenerated into a temp directory
   and compared against what's committed, so adding/renaming/re-describing a command without
   running `pdm run gen-docs` fails the build instead of quietly rotting the docs.
2. Every `cg ...` invocation appearing in a *hand-written* page is resolved against the real parser.
   Renames are the drift that actually happens here--`cg puzzle push` became `cg puzzle submit`,
   `revert` became `discard-local`, `status --remote` became `--refresh`--and each would have
   invalidated every guide that mentioned it, silently. This can't check that the surrounding advice
   is still *correct*, but a command that no longer exists makes a whole page look abandoned.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shlex
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = REPO_ROOT / "doc"
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gen_cli_docs import REFERENCE_SUBDIR, generate  # noqa: E402  (needs the path fix above)


def test_generated_reference_is_up_to_date(tmp_path: Path) -> None:
    """`pdm run gen-docs` output must match what's committed.

       Committed rather than built on the fly so the reference is readable straight from GitHub even
       if the docs site is never built, and so an interface change shows up as a reviewable diff."""
    generate(tmp_path)

    committed_dir = REPO_ROOT / REFERENCE_SUBDIR
    fresh_dir = tmp_path / REFERENCE_SUBDIR
    committed = {p.relative_to(committed_dir): p for p in committed_dir.rglob("*.md")}
    fresh = {p.relative_to(fresh_dir): p for p in fresh_dir.rglob("*.md")}

    assert set(committed) == set(fresh), (
        "generated reference pages differ from what's committed; run `pdm run gen-docs`")
    stale = [str(name) for name, path in fresh.items()
             if path.read_text(encoding="utf-8") != committed[name].read_text(encoding="utf-8")]
    assert not stale, f"stale generated docs (run `pdm run gen-docs`): {stale}"


# `cg ...` inside a fenced block or inline code. Stops at anything that ends a command: a pipe,
# redirect, comment, or the end of the line.
_INVOCATION_RE = re.compile(r"(?<![\w`])cg((?: +[a-z0-9][a-z0-9-]*)+)")

# Words that follow `cg` in prose but aren't commands (placeholders, or a group named mid-sentence).
_PLACEHOLDERS = {"command", "options", "subcommand"}


def _hand_written_pages() -> list[Path]:
    reference = REPO_ROOT / REFERENCE_SUBDIR
    return sorted(p for p in DOC_ROOT.rglob("*.md") if reference not in p.parents)


def _command_paths(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    paths = {path}
    for action in parser._actions:  # noqa: SLF001  (argparse exposes no public traversal API)
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                paths |= _command_paths(sub, (*path, name))
    return paths


@pytest.fixture(scope="module")
def known_commands() -> set[tuple[str, ...]]:
    from codingame_tools.cli.main import CgCli

    original_argv0 = sys.argv[0]
    sys.argv[0] = "cg"
    try:
        cli = CgCli(["--help"])
        asyncio.run(cli.init_parser())
        return _command_paths(cli.parser)
    finally:
        sys.argv[0] = original_argv0


def test_documented_commands_all_exist(known_commands: set[tuple[str, ...]]) -> None:
    """Every `cg ...` written by hand in `doc/` resolves to a real command."""
    unknown: list[str] = []
    for page in _hand_written_pages():
        for match in _INVOCATION_RE.finditer(page.read_text(encoding="utf-8")):
            words = tuple(shlex.split(match.group(1)))
            # Trim trailing words until we reach a real command: everything after it is arguments
            # (`cg puzzle import temperatures`), which we deliberately don't validate.
            candidate = words
            while candidate and candidate not in known_commands:
                candidate = candidate[:-1]
            if not candidate and words and words[0] not in _PLACEHOLDERS:
                unknown.append(f"{page.relative_to(REPO_ROOT)}: cg {' '.join(words)}")
    assert not unknown, "documented commands that don't exist:\n  " + "\n  ".join(unknown)


def test_the_linter_would_catch_a_rename(known_commands: set[tuple[str, ...]]) -> None:
    """Guard the guard: a real past rename must not resolve.

       `cg puzzle push` was renamed to `cg puzzle submit`. If this ever passes, the matcher has gone
       slack (e.g. by trimming down to a bare group) and the check above is no longer protecting
       anything."""
    assert ("puzzle", "submit") in known_commands
    assert ("puzzle", "push") not in known_commands


_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _markdown_pages() -> list[Path]:
    """Every markdown file that's part of the docs, including the root-level ones."""
    pages = list(DOC_ROOT.rglob("*.md"))
    pages += [REPO_ROOT / name for name in ("README.md", "CONTRIBUTING.md")]
    return sorted(p for p in pages if p.is_file())


def test_relative_doc_links_resolve() -> None:
    """Every relative link between docs points at a file that exists.

       Cheap, and it's the other half of the rename problem: the command linter catches a `cg ...`
       that no longer exists, this catches a page that no longer exists. Both are the kind of rot
       that makes documentation look unmaintained long before anyone notices it's wrong."""
    broken: list[str] = []
    for page in _markdown_pages():
        for target in _LINK_RE.findall(page.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path, _, _anchor = target.partition("#")
            if not path:
                continue  # a bare anchor, into this same page
            if not (page.parent / path).resolve().exists():
                broken.append(f"{page.relative_to(REPO_ROOT)} -> {target}")
    assert not broken, "broken relative links:\n  " + "\n  ".join(broken)
