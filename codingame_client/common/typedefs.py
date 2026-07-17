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

BROWSER_PROFILE_SUBDIR: Final[str] = "browser-profile"
"""Subdirectory under app's private storage directory in which browser persistent session state for login is stored."""

__all__ = [
    "BROWSER_PROFILE_SUBDIR",
    "CLIENT_APP_NAME",
    "JsonDict",
    "JsonList",
    "JsonScalar",
    "JsonData",
    "override",
]
