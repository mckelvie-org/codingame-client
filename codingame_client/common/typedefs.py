"""Basic type definitions"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override  # type: ignore[no-redef]

from typing import Final

from json_data_types import JsonData, JsonDict, JsonList, JsonScalar

CLIENT_APP_NAME: Final[str] = "codingame"
"""The default name of the application for the purpose of isolating app-specific files (cached credentials, etc.)."""

DEFAULT_PROFILE_NAME: Final[str] = "default"
"""The default profile name for managing independent sets of credentials and browser session state."""

PROFILES_SUBDIR: Final[str] = "profiles"
"""Subdirectory under an app's private storage directory under which all per-profile state
   (credentials, browser session state, etc.) is stored, e.g., `profiles/<profile_name>/...`."""

BROWSER_LOGIN_SUBDIR: Final[str] = "browser-login"
"""Subdirectory under a profile's private storage directory in which browser persistent session
   state for login is stored, e.g., `profiles/<profile_name>/browser-login`."""

__all__ = [
    "BROWSER_LOGIN_SUBDIR",
    "CLIENT_APP_NAME",
    "DEFAULT_PROFILE_NAME",
    "PROFILES_SUBDIR",
    "JsonDict",
    "JsonList",
    "JsonScalar",
    "JsonData",
    "override",
]
