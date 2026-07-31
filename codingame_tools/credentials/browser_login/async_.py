"""
Async browser-based login for CodinGame.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path

from private_files import get_private_files

from ...client.common import BROWSER_LOGIN_SUBDIR, CLIENT_APP_NAME, DEFAULT_PROFILE_NAME, PROFILES_SUBDIR, logger
from ..cg_credentials import CgCredentials, get_credentials_store, validate_profile_name
from .common import (
    CG_SESSION_GRACE_TIMEOUT_SECS,
    DEFAULT_TIMEOUT_SECS,
    POLL_INTERVAL_SECS,
    CgBrowserLoginError,
    ensure_playwright_chromium_installed,
)

__all__ = [
    "async_cg_browser_login",
]

async def async_cg_browser_login(
            *,
            app_name: str | None = None,
            profile_name: str | None = None,
            browser_login_subdir: str | None = None,
            timeout: float | None = None,
            clean: bool = False,
            save: bool = True,
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
    """

    logger.debug("Ensuring Playwright Chromium is installed...")
    await ensure_playwright_chromium_installed()

    from playwright.async_api import async_playwright

    app_name = CLIENT_APP_NAME if app_name is None else app_name
    profile_name = DEFAULT_PROFILE_NAME if profile_name is None else profile_name
    validate_profile_name(profile_name)
    browser_login_subdir = BROWSER_LOGIN_SUBDIR if browser_login_subdir is None else browser_login_subdir
    timeout = DEFAULT_TIMEOUT_SECS if timeout is None else timeout

    pf = get_private_files(app_name=app_name)
    browser_login_dir_subpath = Path(PROFILES_SUBDIR) / profile_name / browser_login_subdir
    browser_login_dir = pf.get_private_dir(browser_login_dir_subpath)
    if browser_login_dir.is_dir():
        logger.debug(f"Found existing browser login directory: {browser_login_dir}")
    else:
        logger.debug(f"No existing browser login directory; login will be clean: {browser_login_dir}")

    if clean:
        logger.debug("Forcing clean browser login directory...")
        pf.delete_private_dir(browser_login_dir_subpath)
    user_data_dir = pf.create_private_dir(browser_login_dir_subpath)
    logger.debug("Opening browser for Codingame login...")
    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            await page.goto("https://www.codingame.com/login")
            print("Please log in in the browser window. Waiting for credentials...", file=sys.stderr)

            remember_me: str | None = None
            cg_session: str | None = None
            deadline = time.monotonic() + timeout
            grace_deadline: float | None = None
            while time.monotonic() < deadline:
                if not context.pages:
                    raise CgBrowserLoginError("Browser window was closed before CodingGame login completed.")
                cookies = await context.cookies("https://www.codingame.com")
                cookie_map = {n: v for c in cookies if (n := c.get("name")) and (v := c.get("value"))}
                remember_me = cookie_map.get("rememberMe")
                cg_session = cookie_map.get("cgSession")
                if remember_me and grace_deadline is None:
                    logger.debug("Found rememberMe cookie; starting grace period for cgSession cookie.")
                    grace_deadline = time.monotonic() + CG_SESSION_GRACE_TIMEOUT_SECS
                if grace_deadline is not None and time.monotonic() >= grace_deadline:
                    raise CgBrowserLoginError("Timeout waiting for CodinGame login....")
                if remember_me and cg_session:
                    logger.debug("Found both rememberMe and cgSession cookies; exiting early.")
                    break
                await asyncio.sleep(POLL_INTERVAL_SECS)
            with contextlib.suppress(Exception):
                await context.close()
                
        if remember_me is None or cg_session is None:
            raise CgBrowserLoginError("Timed out waiting for CodinGame login to complete.")
        credentials = CgCredentials(
            remember_me_cookie=remember_me,
            cg_session_cookie=cg_session,
        )
        try:
            profile_store = get_credentials_store(app_name=app_name)
            profile_store.set_credentials(profile_name, credentials)
            if save:
                profile_store.commit()
        except Exception as e:
            logger.warning(f"Failed to save credentials after browser login: {e}")
            raise CgBrowserLoginError("Failed to save credentials after browser login.") from e
    except CgBrowserLoginError:
        raise
    except Exception as e:
        raise CgBrowserLoginError("An error occurred during the Codingame browser login process.") from e
    
    logger.info("CodingGame browser login completed successfully.")
    return credentials

