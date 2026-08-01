"""Persistent, app-writable settings for CodinGame client tools (CLI, contribution manager, and
   potentially the client itself), stored as settings.json in the resolved config's data
   directory.

   Unlike config.yaml (user-edited, YAML, requires an explicit `cg config init` before it can be
   used), settings.json is managed by the app itself--written by commands like
   `cg settings set default-profile`--and simply defaults to empty/all-defaults if it doesn't
   exist yet, no explicit "init" required. This lives in its own top-level package (`settings/`,
   a sibling of `config/`) rather than inside `config/` itself, since it's runtime data the app
   writes, not configuration a user edits--a deliberately different concern even though the two
   are closely related (a `CgSettings` always belongs to a `CgConfig`, and `CgConfigData` embeds
   this module's own `CgSettingsData` shape as its `settings` sub-object--see
   `CgConfigData.settings` and `CgConfig.settings` for how that's merged in).

   `CgConfig` is only imported under `TYPE_CHECKING` here (used purely for type annotations) to
   avoid a real circular import: `codingame_tools.config.cg_config` needs `CgSettingsData` (for
   `CgConfigData.settings`), so this module cannot import `codingame_tools.config` eagerly at
   module-load time without creating a cycle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from json_data_types import JsonDict

from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

if TYPE_CHECKING:
    from ..config import CgConfig

__all__ = [
    "SETTINGS_FILE_NAME",
    "CgSettingsData",
    "CgSettings",
    "overlay_settings_data",
    "relativize_settings_dir",
    "resolve_settings",
    "resolve_settings_dir",
    "write_settings",
]

SETTINGS_FILE_NAME = "settings.json"
"""Name of the app-writable settings file, stored directly in the resolved data directory (e.g.
   `.cg/data/settings.json`)--no `config/`-style subdirectory nesting needed, since (unlike
   config.yaml) there's no multi-profile-sharing concern for this file."""


@dataclass
class CgSettingsData(JSONWizardX):
    """Raw, app-writable settings, as literally stored in settings.json. Deliberately just a data
       container, same spirit as `CgConfigData`--see `CgSettings` for the functional wrapper that
       resolves defaults (falling back to `CgConfig` where appropriate) and is what callers
       should normally use instead of this class directly."""

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible. There are no
    # required fields in this class, so it ends up first overall.
    extra_data: CatchAll = field(default_factory=dict)
    """Unrecognized fields encountered when loading a settings file, preserved so that
       round-tripping through `saves()`/`loads()` does not silently drop data."""

    default_profile: str | None = None
    """Override for the default codingame-tools credential profile name to use. If not set,
       falls back to `CgConfig.settings.default_profile` (see `CgConfigData.settings`--itself
       merged from the global then a project config.yaml's own `settings.defaultProfile`), and
       from there to "default". See `CgSettings.default_profile` for the resolved value."""

    contribution_dir: str | None = None
    """Default contribution working directory (see `codingame_tools.contribution_manager`), used
       when one isn't given explicitly and `CG_CONTRIBUTION_DIR` isn't set. If not set, falls
       back to `CgConfig.settings.contribution_dir` the same way `default_profile` does--only
       once that's also unset does contribution-dir discovery move on to its cwd-based
       heuristics. May be relative or absolute; `~` is expanded. A relative value is resolved
       against the directory settings.json itself lives in (i.e. the owning `CgConfig.data_dir`)
       --NOT the current working directory at the time it's consulted--so the effective directory
       doesn't move around depending on where `cg` happens to be run from. `cg settings set
       contribution-dir` takes care of converting a path typed relative to the CLI's own cwd into
       this form--see `relativize_settings_dir`/`resolve_settings_dir`, and
       `CgSettings.contribution_dir` for the resolved value."""

    puzzle_dir: str | None = None
    """Default puzzle working directory (see `codingame_tools.puzzle_manager`), used when one
       isn't given explicitly and `CG_PUZZLE_DIR` isn't set. Same resolution rules as
       `contribution_dir`--see `CgSettings.puzzle_dir` for the resolved value."""


def overlay_settings_data(base: CgSettingsData, override: CgSettingsData) -> CgSettingsData:
    """Return a new `CgSettingsData` with each of `default_profile`/`contribution_dir`/
       `puzzle_dir` taken from `override` where it's set there, else from `base`. The building
       block for the base-to-refined settings resolution chain (global config.yaml's `settings`
       -> a project config.yaml's `settings` -> settings.json)--see `CgConfig.settings` for where
       the first two tiers get combined, and `CgSettings`'s properties for where settings.json
       itself gets layered on top as the final, most-refined tier."""
    return CgSettingsData(
            default_profile=override.default_profile if override.default_profile is not None else base.default_profile,
            contribution_dir=override.contribution_dir if override.contribution_dir is not None else base.contribution_dir,
            puzzle_dir=override.puzzle_dir if override.puzzle_dir is not None else base.puzzle_dir,
        )


def resolve_settings_dir(raw_value: str | None, base_dir: Path) -> Path | None:
    """Resolve a raw `contributionDir`/`puzzleDir`-shaped string--as stored in a `CgSettingsData`,
       whether it came from settings.json directly or from a config.yaml `settings` tier--to an
       absolute `Path`.

       `None` if `raw_value` is `None`. Otherwise `~`-expanded, and--if still not absolute--
       resolved against `base_dir` (the *resolved data directory* settings.json lives in, i.e.
       `CgConfig.data_dir`/`CgSettings.settings_file.parent`), never the current working
       directory--so the effective directory is the same regardless of where `cg` is run from.
       See `relativize_settings_dir` for the inverse, used when a value is first set."""
    if raw_value is None:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def relativize_settings_dir(path: Path, base_dir: Path) -> str:
    """The inverse of `resolve_settings_dir`: given a path as typed at the CLI (relative to the
       current working directory if not absolute--the natural way to type a path on a command
       line), return the string that should actually be stored in `CgSettingsData.
       contribution_dir`/`puzzle_dir` so that `resolve_settings_dir()` reconstructs the exact
       same absolute location later, regardless of `cg`'s cwd at that later time.

       Absolute input (after `~`-expansion) is stored as-is, unchanged. Relative input is first
       resolved against the current working directory (i.e. what it actually refers to right
       now), then re-expressed relative to `base_dir`--which may include `..` segments if the
       target isn't under `base_dir`."""
    expanded = path.expanduser()
    if expanded.is_absolute():
        return str(expanded)
    absolute = expanded.resolve()
    return os.path.relpath(absolute, start=base_dir.resolve())


@dataclass
class CgSettings:
    """A resolved, functional settings object: pairs the raw `CgSettingsData` loaded from
       settings.json with the `CgConfig` it belongs to, and resolves defaults reliably (falling
       back to config-level values, and from there to hardcoded defaults)--this is the class
       callers should normally use, rather than `CgSettingsData` directly."""

    settings_file: Path
    """The resolved, absolute path to the settings.json file. May not exist yet on disk--see
       `resolve_settings()`, which uses `CgSettingsData()` (all defaults) if so, rather than
       requiring the file to already exist the way config.yaml does."""

    raw_data: CgSettingsData
    """The raw settings as loaded from `settings_file` (or all-defaults if it doesn't exist yet),
       unresolved (fields may be None)."""

    config: CgConfig
    """The resolved CgConfig this CgSettings belongs to, used to fall back to config-level
       defaults for settings not overridden here."""

    @property
    def default_profile(self) -> str:
        """The default codingame-tools credential profile name to use. Resolution order: this
           file's own `defaultProfile`, then `CgConfig.default_profile` (itself merged from the
           global then a project config.yaml's `settings.defaultProfile`, falling back to
           "default" if neither sets it)."""
        if self.raw_data.default_profile is not None:
            return self.raw_data.default_profile
        return self.config.default_profile

    @property
    def contribution_dir(self) -> Path | None:
        """The configured default contribution working directory, resolved to an absolute path
           (relative values resolved against `settings_file`'s own directory--see
           `resolve_settings_dir`--NOT the current working directory). Resolution order: this
           file's own `contributionDir`, then `CgConfig.contribution_dir` (itself merged from the
           global then a project config.yaml's `settings.contributionDir`). `None` if still unset
           after that--callers (see `codingame_tools.contribution_manager.resolver`) move on to
           their own cwd-based discovery steps."""
        resolved = resolve_settings_dir(self.raw_data.contribution_dir, self.settings_file.parent)
        if resolved is not None:
            return resolved
        return self.config.contribution_dir

    @property
    def puzzle_dir(self) -> Path | None:
        """The configured default puzzle working directory, resolved to an absolute path (same
           rules as `contribution_dir`). See `codingame_tools.puzzle_manager.resolver`."""
        resolved = resolve_settings_dir(self.raw_data.puzzle_dir, self.settings_file.parent)
        if resolved is not None:
            return resolved
        return self.config.puzzle_dir

    def save(self) -> None:
        """Write `raw_data` back to `settings_file`."""
        write_settings(self.raw_data, self.settings_file)

    def to_dump_dict(self) -> JsonDict:
        """Assemble a JSON-friendly summary for e.g. `cg settings dump`: resolved values at the
           top level, plus the raw (unresolved) settings content under `"rawSettings"`."""
        return {
            "settingsFile": str(self.settings_file),
            "defaultProfile": self.default_profile,
            "contributionDir": str(self.contribution_dir) if self.contribution_dir is not None else None,
            "puzzleDir": str(self.puzzle_dir) if self.puzzle_dir is not None else None,
            "rawSettings": self.raw_data.to_dict(),
        }


def resolve_settings(config: CgConfig) -> CgSettings:
    """Load (or default) the settings.json file for the given resolved config's data directory.

       Unlike config resolution, this never raises for "not found"--a missing settings.json is
       just `CgSettingsData()` (all defaults), since this file is app-managed state, not
       something the user needs to have explicitly set up first.
    """
    settings_file = config.data_dir / SETTINGS_FILE_NAME
    raw_data = CgSettingsData.load(settings_file) if settings_file.is_file() else CgSettingsData()
    return CgSettings(settings_file=settings_file, raw_data=raw_data, config=config)


def write_settings(settings: CgSettingsData, settings_file: Path | str) -> None:
    """Write `settings` to `settings_file` as JSON, creating parent directories if necessary."""
    path = Path(settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings.save(path)
