"""Simple module to run the browser login flow in an async context."""

import argparse
import asyncio
import logging

from codingame_client.browser_login.async_ import async_cg_browser_login

logger = logging.getLogger(__name__)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log in to CodinGame via a real browser session.")
    parser.add_argument(
        "--profile", "-p",
        default=None,
        help="Profile name to store credentials and browser session state under. Defaults to the client's default profile.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force a fresh browser login flow, even if credentials are already cached.",
    )
    return parser.parse_args()

async def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG)
    credentials = await async_cg_browser_login(profile_name=args.profile, clean=args.force)
    print("Login successful!")
    print(f"Remember Me Cookie: [{credentials.remember_me_cookie}]")
    if credentials.cg_session_cookie is not None:
        print(f"cgSession Cookie: [{credentials.cg_session_cookie}]")

if __name__ == "__main__":
    asyncio.run(main())