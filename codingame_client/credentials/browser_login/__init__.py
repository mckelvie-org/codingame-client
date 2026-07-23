"""
Interactive browser-based login for CodinGame.

The tools in this module allow a user to log in to CodinGame via a real browser session, and then
retrieve and persist the resulting credentials (the rememberMe and cgSession cookies) for subsequent
use in a CodinGame client session.
The browser's own persistent session state (cookies, local storage, etc.) is stored alongside the
per-profile persistent credentials in the app's private storage directory, so that repeated
logins for the same profile are generally automatic (A browser window briefly pops
up, the credentials are extracted, and the window closes, without the user having to log in again).

Multiple independent profiles can be used to manage separate sets of credentials and browser session state,
if multiple CodinGame accounts are used.

The Python package "playwright" is used to install a sandboxed Chromium browser
and orchestrate a Chromium browser session. The user's normal browsers are not touched.
"""

from .async_ import async_cg_browser_login
from .common import (
    CG_SESSION_GRACE_TIMEOUT_SECS,
    DEFAULT_TIMEOUT_SECS,
    POLL_INTERVAL_SECS,
    CgBrowserLoginError,
    cg_browser_delete_session,
    ensure_playwright_chromium_installed,
)
from .sync import cg_browser_login

__all__ = [
    "async_cg_browser_login",
    "cg_browser_login",
    "CgBrowserLoginError",
    "DEFAULT_TIMEOUT_SECS",
    "CG_SESSION_GRACE_TIMEOUT_SECS",
    "POLL_INTERVAL_SECS",
    "cg_browser_delete_session",
    "ensure_playwright_chromium_installed",
]
