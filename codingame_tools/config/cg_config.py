"""Persistent, user-editable configuration schema for CodinGame client tools (CLI, contribution
   manager, and potentially the client itself), stored as a YAML file. See
   `codingame_tools.config.resolver` for how the config file is located, and for `CgConfig`--the
   functional wrapper around this raw data that resolves defaults (e.g. `dataDir`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "CgConfigData",
]


@dataclass
class CgConfigData(JSONWizardX):
    """Raw, user-editable persistent configuration, as literally stored in a config.yaml file.
       Serialized using `JSONWizardX`'s default camelCase key convention (e.g. `dataDir`),
       matching every other JSON-shaped format in this project rather than switching to
       snake_case for this one file format.

       This is deliberately just a data container--fields here may be unset/None, and relative
       paths are stored as plain strings rather than resolved. See `CgConfig` (in
       `codingame_tools.config.resolver`) for the functional wrapper that resolves defaults and
       is what callers should normally use instead of this class directly.
    """

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible. There are no
    # required fields in this class, so it ends up first overall.
    extra_data: CatchAll = field(default_factory=dict)
    """Unrecognized fields encountered when loading a config file, preserved so that
       round-tripping through `saves()`/`loads()` does not silently drop data."""

    data_dir: str | None = None
    """Override for the persistent, app-writable data directory. A relative path is resolved
       relative to the directory containing this config file; an absolute path (or a `~`-prefixed
       path) is used as-is. If not set, defaults to a sibling "data" directory next to the
       directory containing this config file (e.g. `.cg/data`, alongside `.cg/config`). See
       `CgConfig.data_dir` for the resolved value--this raw field is usually not what callers want."""

    default_profile: str | None = None
    """Override for the default codingame-tools credential profile name to use. If not set,
       defaults to "default". See `CgConfig.default_profile` for the resolved value, and
       `CgSettingsData.default_profile` for the app-writable settings.json override that takes
       precedence over this one."""
