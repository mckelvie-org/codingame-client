"""
Async browser-based login for CodinGame.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

from private_files import private_files

from ...common import BROWSER_PROFILE_SUBDIR, CLIENT_APP_NAME, logger
from ...common.credentials import CgCredentials, set_credentials


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
            browser_profile_subdir: str | None = None,
            timeout: float | None = None,
            clean: bool = False,
            save: bool = True,
        ) -> CgCredentials:
    """Opens a Chromium browser window for the user to log in to CodinGame, and
       after successful login, returns the credentials, including
       the rememberMe and cgSession cookies. The credentials are also cached in module credentials, and
       optionally saved to the app's private storage directory where they are usable by the codingame client.
       Note that the returned credentials are not overriden by environment variables here; that case
       is handled in the codingame client itself.
    """
    
    logger.debug("Ensuring Playwright Chromium is installed...")
    await ensure_playwright_chromium_installed()
    
    from playwright.async_api import async_playwright
    
    app_name = CLIENT_APP_NAME if app_name is None else app_name
    browser_profile_subdir = BROWSER_PROFILE_SUBDIR if browser_profile_subdir is None else browser_profile_subdir
    timeout = DEFAULT_TIMEOUT_SECS if timeout is None else timeout
    
    pf = private_files(app_name=app_name)
    browser_profile_dir = pf.get_private_dir(browser_profile_subdir)
    if browser_profile_dir.is_dir():
        logger.debug(f"Found existing browser profile directory: {browser_profile_dir}")
    else:
        logger.debug(f"No existing browser profile directory; login will be clean: {browser_profile_dir}")
    
    if clean:
        logger.debug("Forcing Clean browser profile...")
        pf.delete_private_dir(browser_profile_subdir)
    user_data_dir = pf.create_private_dir(browser_profile_subdir)
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
                
        assert remember_me is not None, "remember_me should not be None here"

        if cg_session is None:
            logger.warning(
                    "CodingGame browser login completed without cgSession cookie--"
                    "some functions (e.g., file upload) may not succeed.")
        credentials = CgCredentials(
            remember_me_cookie=remember_me,
            cg_session_cookie=cg_session,
        )
        try:
            set_credentials(credentials, save=save, app_name=app_name)
        except Exception as e:
            logger.warning(f"Failed to save credentials after browser login: {e}")
            raise CgBrowserLoginError("Failed to save credentials after browser login.") from e
    except CgBrowserLoginError:
        raise
    except Exception as e:
        raise CgBrowserLoginError("An error occurred during the Codingame browser login process.") from e
    
    logger.info("CodingGame browser login completed successfully.")
    return credentials
