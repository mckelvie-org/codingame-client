"""Simple module to run the browser login flow in an async context."""

import asyncio
import logging

from codingame_client.async_.browser_login import cg_browser_login

logger = logging.getLogger(__name__)

async def main():
    logging.basicConfig(level=logging.DEBUG)
    credentials = await cg_browser_login()
    print("Login successful!")
    print(f"Remember Me Cookie: [{credentials.remember_me_cookie}]")
    if credentials.cg_session_cookie is not None:
        print(f"cgSession Cookie: [{credentials.cg_session_cookie}]")

if __name__ == "__main__":
    asyncio.run(main())