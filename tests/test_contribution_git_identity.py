"""Tests for the git author/committer identity fallback in `contribution_manager.git_repo`.

`.meta/`'s repository is local, gitignored scaffolding and its commits are never pushed anywhere, so
who authored them is meaningless -- but `git commit` still refuses to run without an identity.

Git usually papers over this by auto-detecting `user@host`, which is why nothing broke locally. It
fails where the hostname has no domain (`runner@fv-az123.(none)` on a GitHub Actions runner) or
wherever `user.useConfigOnly` is set, and it fails for any real user who has never run
`git config --global user.email`. So `cg contribution` was, in effect, requiring a configured git
identity for no reason.

These tests run git with a scrubbed configuration and `user.useConfigOnly=true`, which reproduces
the CI failure deterministically on a developer machine that does have an identity configured.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codingame_tools.contribution_manager.git_repo import (
    FALLBACK_IDENTITY_EMAIL,
    FALLBACK_IDENTITY_NAME,
    CgGitRepo,
    init_repo,
)

# Point config at nothing, then forbid git's own `user@host` auto-detection. Without that last
# part this passes everywhere and tests nothing, since git invents an identity when none is set.
NO_IDENTITY_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "user.useConfigOnly",
    "GIT_CONFIG_VALUE_0": "true",
}

# These must be *removed*, not blanked. Git reads them ahead of any config, including our `-c`
# fallback, and treats an empty one as an explicit empty identity: `fatal: empty ident name`.
IDENTITY_ENV_VARS = (
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL",
)


@pytest.fixture
def no_git_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    (tmp_path / "empty-home").mkdir()
    for key, value in NO_IDENTITY_ENV.items():
        monkeypatch.setenv(key, value)
    for key in IDENTITY_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


def _commit_one(root: Path) -> tuple[CgGitRepo, Path]:
    git_dir, work_tree = root / "gitdir", root / "work"
    init_repo(git_dir, work_tree)
    repo = CgGitRepo(git_dir, work_tree)
    (work_tree / "f.txt").write_text("hi\n")
    repo._run(["add", "-A"])  # noqa: SLF001
    repo._run(["commit", "-m", "test"])  # noqa: SLF001
    return repo, git_dir


def _last_author(git_dir: Path) -> str:
    return subprocess.run(
            ["git", f"--git-dir={git_dir}", "log", "-1", "--format=%an <%ae>"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()


@pytest.mark.usefixtures("no_git_identity")
def test_commits_work_with_no_git_identity_configured(tmp_path: Path) -> None:
    """The actual regression: without the fallback this raises `CgGitError` with
       "Author identity unknown", and essentially every contribution-manager test fails with it."""
    _repo, git_dir = _commit_one(tmp_path / "repo")

    assert _last_author(git_dir) == f"{FALLBACK_IDENTITY_NAME} <{FALLBACK_IDENTITY_EMAIL}>"


def test_a_configured_identity_is_not_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback must stay a fallback. `-c` outranks every config file, so applying it
       unconditionally would stamp our synthetic name over the user's real one -- which is what they
       see in `git log` while resolving a merge conflict."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Real Person")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "real@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Real Person")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "real@example.com")

    _repo, git_dir = _commit_one(tmp_path / "repo")

    assert _last_author(git_dir) == "Real Person <real@example.com>"


@pytest.mark.usefixtures("no_git_identity")
def test_identity_probe_runs_once_per_repo(tmp_path: Path) -> None:
    """The probe shells out, so it's cached. Asserted because the natural place to put the check is
       inside `_run`, where it would fire on every single git invocation."""
    repo, _ = _commit_one(tmp_path / "repo")
    cached = repo._identity_args  # noqa: SLF001
    assert cached, "expected the fallback to have been engaged"

    repo._run(["status", "--porcelain"])  # noqa: SLF001

    assert repo._identity_args is cached  # noqa: SLF001
