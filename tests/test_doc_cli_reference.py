"""Tests that keep the *hand-written* docs honest about the CLI.

Every `cg ...` invocation appearing in a hand-written page is resolved against the real parser, and
every relative link between pages is checked to point at a file that exists. Renames are the drift
that actually happens here--`cg puzzle push` became `cg puzzle submit`, `revert` became
`discard-local`, `status --remote` became `--refresh`--and each would have silently invalidated
every guide mentioning it. This can't check that the surrounding advice is still *correct*, but a
command that no longer exists makes a whole page look abandoned.

**Deliberately does not check that `doc/cli/reference/` is up to date.** That directory is a build
artifact, not source: it can be deleted and rebuilt from the parser at any time, and on `main` it is
a cached copy that may lag. `bin/cut-rc` regenerates it into every release commit, which is where
being current actually matters. A staleness test here would quietly reclassify it as source and fail
builds over a file nobody has to hand-maintain.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = REPO_ROOT / "doc"
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gen_cli_docs import REFERENCE_SUBDIR  # noqa: E402  (needs the path fix above)


def test_generated_pages_contain_no_terminal_escapes(tmp_path: Path) -> None:
    """Generated pages must be plain text, whatever terminal the generator was run from.

       Python 3.14's argparse colourises help when `sys.stdout` is a terminal, which is right for a
       human running `cg --help` and wrong when `format_help()` is being captured into files.
       Generating from an interactive shell wrote raw ANSI escapes into every page; generating
       through a pipe produced clean text. The same source, different files, decided by how the
       command happened to be invoked -- and it reached a commit before anyone noticed, because
       every automated run here is piped.

       Generated under `FORCE_COLOR`, which is the loudest thing a caller's environment can say, so
       this fails if the generator ever stops pinning colour off."""
    env = dict(os.environ, FORCE_COLOR="1")
    env.pop("PYTHON_COLORS", None)
    env.pop("NO_COLOR", None)
    subprocess.run(
            [sys.executable, str(SCRIPTS / "gen_cli_docs.py"), str(tmp_path)],
            check=True, capture_output=True, env=env, cwd=REPO_ROOT,
        )

    offenders = [
        str(page.relative_to(tmp_path))
        for page in (tmp_path / REFERENCE_SUBDIR).rglob("*.md")
        if "\x1b" in page.read_text(encoding="utf-8")
    ]
    assert not offenders, f"ANSI escapes leaked into generated pages: {offenders[:5]}"


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
