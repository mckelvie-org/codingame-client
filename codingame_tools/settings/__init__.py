"""Persistent, app-writable runtime settings for CodinGame client tools (CLI, contribution
   manager, and potentially the client itself). See `codingame_tools.config` for the related but
   distinct concept of user-edited configuration.
"""

from __future__ import annotations

from .cg_settings import (
    SETTINGS_FILE_NAME,
    CgSettings,
    CgSettingsData,
    resolve_settings,
    write_settings,
)

__all__ = [
    "CgSettingsData",
    "CgSettings",
    "resolve_settings",
    "write_settings",
    "SETTINGS_FILE_NAME",
]
