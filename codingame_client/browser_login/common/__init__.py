"""
browser-based login for CodinGame.
"""

from __future__ import annotations

import asyncio
import sys

from ...client.common import BROWSER_LOGIN_SUBDIR, CLIENT_APP_NAME, DEFAULT_PROFILE_NAME, PROFILES_SUBDIR, logger
from ...client.common.credentials import CgCredentials, get_credentials_store, validate_profile_name

__all__ = [
    "BROWSER_LOGIN_SUBDIR",
    "CLIENT_APP_NAME",
    "DEFAULT_PROFILE_NAME",
    "PROFILES_SUBDIR",
    "CgCredentials",
    "get_credentials_store",
    "validate_profile_name",
    "logger",
]

class CgBrowserLoginError(Exception):
    """Raised when the browser login process fails."""
    pass

DEFAULT_TIMEOUT_SECS: float = 300.0
"""The default time to wait for the user to successfully log in."""

CG_SESSION_GRACE_TIMEOUT_SECS: float = 10.0
"""The time to wait for the cgSession cookie to appear after the rememberMe cookie has been detected.
   This is to allow for the case where the user logs in with a new account and the cgSession cookie
   is not immediately available."""

POLL_INTERVAL_SECS: float = 0.5
"""The interval at which to poll the browser for the presence of the login cookies."""


async def ensure_playwright_chromium_installed() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
    )
    returncode = await proc.wait()
    if returncode != 0:
        raise RuntimeError(f"playwright install chromium failed with code {returncode}")
