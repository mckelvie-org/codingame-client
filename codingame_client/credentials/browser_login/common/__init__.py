"""
Common definitions for sync/async browser-based login for CodinGame.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from private_files import get_private_files

from ....client.common import BROWSER_LOGIN_SUBDIR, CLIENT_APP_NAME, DEFAULT_PROFILE_NAME, PROFILES_SUBDIR, logger
from ...cg_credentials import CgCredentials, get_credentials_store, validate_profile_name

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

def cg_browser_delete_session(
            *,
            app_name: str | None = None,
            profile_name: str | None = None,
            browser_login_subdir: str | None = None,
            delete_credentials: bool = True,
        ) -> None:
    """Deletes the persistent browser session state and optionally the persistent credentials for a given profile."""
    app_name = CLIENT_APP_NAME if app_name is None else app_name
    profile_name = DEFAULT_PROFILE_NAME if profile_name is None else profile_name
    validate_profile_name(profile_name)
    browser_login_subdir = BROWSER_LOGIN_SUBDIR if browser_login_subdir is None else browser_login_subdir
    pf = get_private_files(app_name=app_name)
    browser_login_dir_subpath = Path(PROFILES_SUBDIR) / profile_name / browser_login_subdir
    browser_login_dir = pf.get_private_dir(browser_login_dir_subpath)
    if delete_credentials:
        try:
            profile_store = get_credentials_store(app_name=app_name)
            profile_store.set_credentials(profile_name, None)
            profile_store.commit()
        except Exception as e:
            raise CgBrowserLoginError(f"Failed to delete credentials for profile {profile_name}.") from e
    if browser_login_dir.is_dir():
        try:
            pf.delete_private_dir(browser_login_dir_subpath)
        except Exception as e:
            raise CgBrowserLoginError(f"Failed to delete browser session state for profile {profile_name}.") from e
