"""Persistent, app-writable settings for CodinGame client tools (CLI, contribution manager, and
   potentially the client itself), stored as settings.json in the resolved config's data
   directory.

   Unlike config.yaml (user-edited, YAML, requires an explicit `cg config init` before it can be
   used), settings.json is managed by the app itself--written by commands like
   `cg settings set default-profile`--and simply defaults to empty/all-defaults if it doesn't
   exist yet, no explicit "init" required. This lives in its own top-level package (`settings/`,
   a sibling of `config/`) rather than inside `config/` itself, since it's runtime data the app
   writes, not configuration a user edits--a deliberately different concern even though the two
   are closely related (a `CgSettings` always belongs to a `CgConfig`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from json_data_types import JsonDict

from ..common.dataclass_wizard_x import CatchAll, JSONWizardX
from ..config import CgConfig

__all__ = [
    "SETTINGS_FILE_NAME",
    "CgSettingsData",
    "CgSettings",
    "resolve_settings",
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
    """Override for the default codingame-client credential profile name to use. If not set,
       falls back to `CgConfigData.default_profile` (and from there to "default"). See
       `CgSettings.default_profile` for the resolved value."""

    contribution_dir: str | None = None
    """Default contribution working directory (see `codingame_client.contribution_manager`), used
       when one isn't given explicitly and `CG_CONTRIBUTION_DIR` isn't set. Unlike
       `default_profile`, there is no further fallback--if unset here, contribution-dir discovery
       moves on to its cwd-based heuristics. May be relative (resolved against the current
       directory at the time it's consulted) or absolute; `~` is expanded. See
       `CgSettings.contribution_dir` for the resolved value."""


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
        """The default codingame-client credential profile name to use. Resolution order: this
           file's own `defaultProfile`, then `CgConfig.default_profile` (which itself falls back
           to "default")."""
        if self.raw_data.default_profile is not None:
            return self.raw_data.default_profile
        return self.config.default_profile

    @property
    def contribution_dir(self) -> Path | None:
        """The configured default contribution working directory, resolved to an absolute path
           (relative values resolved against the current directory, `~` expanded), or None if not
           set. There is no further fallback (unlike `default_profile`)--`None` here just means
           "not configured", and callers (see `codingame_client.contribution_manager.resolver`)
           move on to their own cwd-based discovery steps."""
        if self.raw_data.contribution_dir is None:
            return None
        return Path(self.raw_data.contribution_dir).expanduser().resolve()

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
