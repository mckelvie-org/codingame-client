"""Discovery of the contribution working directory--analogous to `codingame_client.config`'s
   config.yaml discovery, but much simpler: no upward search, no global per-user fallback. A
   contribution working directory is inherently a local, per-task thing (like a git working
   directory), not shared/global state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .schema import CONTRIBUTION_IDENTITY_FILE_NAME

if TYPE_CHECKING:
    from ..settings import CgSettings

__all__ = [
    "CG_CONTRIBUTION_DIR_ENV_VAR",
    "DEFAULT_CONTRIBUTION_SUBDIR_NAME",
    "CgContributionDirNotFoundError",
    "find_contribution_dir",
    "resolve_contribution_dir",
]

CG_CONTRIBUTION_DIR_ENV_VAR = "CG_CONTRIBUTION_DIR"
"""Environment variable that can override contribution-dir discovery, same as an explicit
   `--contribution-dir` CLI flag (parsing/wiring that flag is the CLI layer's job--this module
   just accepts the resolved `explicit` value)."""

DEFAULT_CONTRIBUTION_SUBDIR_NAME = "contribution"
"""Name of the subdirectory of the current directory checked as a last-resort discovery step."""


class CgContributionDirNotFoundError(Exception):
    """Raised by `resolve_contribution_dir()` (unless `allow_default=True`) when no contribution
       working directory could be located by any discovery step. Does not indicate a bug--this is
       the normal outcome before a contribution has been imported/started in the current
       directory."""

    def __init__(self) -> None:
        super().__init__(
                "No contribution working directory found (checked the current directory and "
                "\"./contribution\" for a contribution.json). Pass an explicit directory, set "
                f"{CG_CONTRIBUTION_DIR_ENV_VAR}, or run `cg settings set contribution-dir DIR`."
            )


def find_contribution_dir(
            explicit: Path | str | None = None,
            *,
            settings: CgSettings | None = None,
            start_dir: Path | str | None = None,
        ) -> Path | None:
    """Locate the contribution working directory to use, following the documented discovery
       precedence:

        1. `explicit` (typically the resolved value of a `--contribution-dir` CLI flag), if given.
        2. The `CG_CONTRIBUTION_DIR` environment variable, if set.
        3. `settings.contribution_dir` (see `CgSettings.contribution_dir`), if given and set.
        4. `start_dir` (or the current directory, if not given), if it contains a
           `contribution.json`.
        5. `start_dir / "contribution"`, if it contains a `contribution.json`.

       Steps 1-3 are taken at face value--the resolved directory need not contain a
       `contribution.json` yet (e.g. a fresh, empty target directory for `cg contribution
       import`). Steps 4-5 are implicit inference and are deliberately conservative: they only
       match if a `contribution.json` is actually already there.

    Returns:
        The resolved contribution directory path, or None if nothing was found at all. This
        function never creates anything.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_value = os.environ.get(CG_CONTRIBUTION_DIR_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve()
    if settings is not None and settings.contribution_dir is not None:
        return settings.contribution_dir
    start = Path(start_dir).resolve() if start_dir is not None else Path.cwd()
    if (start / CONTRIBUTION_IDENTITY_FILE_NAME).is_file():
        return start
    default_subdir = start / DEFAULT_CONTRIBUTION_SUBDIR_NAME
    if (default_subdir / CONTRIBUTION_IDENTITY_FILE_NAME).is_file():
        return default_subdir
    return None


def resolve_contribution_dir(
            explicit: Path | str | None = None,
            *,
            settings: CgSettings | None = None,
            start_dir: Path | str | None = None,
            allow_default: bool = False,
        ) -> Path:
    """Locate the contribution working directory, following the discovery precedence documented
       on `find_contribution_dir`.

       If `allow_default` is True and no directory can be found, falls back to `start_dir` (or the
       current directory)--useful for commands like `cg contribution import` that are happy to
       treat "nothing found" as "use the current directory as the new working directory".
       `commit()`-style callers, where there must already be a working directory, should leave
       this False.

    Raises:
        CgContributionDirNotFoundError: if no directory could be located anywhere, and
                                         `allow_default` is False.
    """
    found = find_contribution_dir(explicit, settings=settings, start_dir=start_dir)
    if found is not None:
        return found
    if allow_default:
        return Path(start_dir).resolve() if start_dir is not None else Path.cwd()
    raise CgContributionDirNotFoundError()
