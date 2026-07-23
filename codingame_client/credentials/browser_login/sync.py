"""
Synchronous browser-based login for CodinGame.

Currently, this just wraps the async browser login implementation by
running an event loop, so it cannot be used in a thread that already has an event loop running. In
that environment, you must use async_cg_browser_login.
"""

from __future__ import annotations

import asyncio

from ..cg_credentials import CgCredentials
from .async_ import async_cg_browser_login

__all__ = [
    "cg_browser_login",
]

def cg_browser_login(
            *,
            app_name: str | None = None,
            profile_name: str | None = None,
            timeout: float | None = None,
            clean: bool = False,
            save: bool = True,
            browser_login_subdir: str | None = None,
        ) -> CgCredentials:
    """
    Opens a sandboxed Chromium browser window for the user to log in to CodinGame, and
    after successful login, returns the credentials, including the rememberMe and
    cgSession cookies.
    
    Args:
        app_name:             The name of the client application. Used to isolate state per-app.  If None, defaults to
                              the codingame client app name.
        profile_name:         The name of the profile to use for storing credentials and browser session state. Allows
                              for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                              If None, defaults to the default profile.
        timeout:              The maximum time in seconds to wait for the user to log in. If None, defaults to DEFAULT_TIMEOUT_SECS.
        clean:                If True, erases browser session state and forces a fresh login flow even if valid credentials
                              are already cached in the browser. Defaults to False.
        save:                 If True (the default), saves the credentials to the persistent credential store for the profile,
                              for future use by CodingGame client sessions. Defaults to True.
        browser_login_subdir: The subdirectory under the profile directory where the browser session state is stored.
                              If None, defaults to the default subdirectory. Should not normally be changed, since there is
                              already one browser session per profile.
    
    The browser's own persistent session state (cookies, local storage, etc.) is stored alongside the
    per-profile persistent credentials in the app's private storage directory, so that repeated
    logins for the same profile are generally automatic (A browser window briefly pops
    up, the credentials are extracted, and the window closes, without the user having to log in again).

    The Python package "playwright" is used to install a sandboxed Chromium browser
    and orchestrate a Chromium browser session. The user's normal browser(s) are not touched.

    The browser's own persistent session state (cookies, local storage, etc., separate from the
    resolved CgCredentials) is stored in the private app directory per-profile as well, so that
    different profiles can be associated with different CodinGame accounts. Because browser session
    state is persisted, repeated logins for the same profile are generally automatic (a browser
    window briefly pops up, the credentials are extracted, and the window closes).

    Note that the returned credentials are not overriden by environment variables here; that case
    is handled in the codingame client itself.
    
    NOTE: The returned credentials and those persisted in the credential store, as well as the persistent
    browser session state, are sensitive information that should be protected. The codingame client stores
    them in the app's private storage directory. On unix-like systems, this is under ~/.private, with
    restrictive mode permissions on directories and files so only the owner can access them.

    Currently, this function just wraps the async implementation by running an event loop, so it cannot be
    used in a thread that already has an event loop running. In
    that environment, you must use async_cg_browser_login.
    """
    return asyncio.run(async_cg_browser_login(
        app_name=app_name,
        profile_name=profile_name,
        browser_login_subdir=browser_login_subdir,
        timeout=timeout,
        clean=clean,
        save=save,
    ))
