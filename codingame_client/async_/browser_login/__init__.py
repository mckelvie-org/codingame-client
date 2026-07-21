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

from ...common import BROWSER_LOGIN_SUBDIR, CLIENT_APP_NAME, DEFAULT_PROFILE_NAME, PROFILES_SUBDIR, logger
from ...common.credentials import CgCredentials, get_credentials_store, validate_profile_name


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

async def cg_browser_login(
            *,
            app_name: str | None = None,
            profile_name: str | None = None,
            browser_login_subdir: str | None = None,
            timeout: float | None = None,
            clean: bool = False,
            save: bool = True,
        ) -> CgCredentials:
    """Opens a Chromium browser window for the user to log in to CodinGame, and
       after successful login, returns the credentials, including
       the rememberMe and cgSession cookies. The credentials are also cached in the given profile's
       credentials store, and optionally saved to the app's private storage directory where they are
       usable by the codingame client, at profiles/<profile_name>/credentials.json.

       The browser's own persistent session state (cookies, local storage, etc., separate from the
       resolved CgCredentials) is stored per-profile as well, at
       profiles/<profile_name>/<browser_login_subdir>, so that logging in under different profiles
       does not cause browser session state to bleed between them.

       Note that the returned credentials are not overriden by environment variables here; that case
       is handled in the codingame client itself.
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
