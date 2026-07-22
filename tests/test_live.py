"""Tests marked @pytest.mark.live hit the real CodinGame API directly on every run--no
   cassette, no caching--and require a real, already-logged-in session. They are excluded
   by default (see addopts in [tool.pytest.ini_options]) and never run in CI; run them
   explicitly with `pdm run test-live` or `pytest -m live`.

   These do not perform an interactive browser login themselves (there is no way to do that
   without a human present); run `python -m codingame_client.async_.browser_login` first to
   establish a real session. If no usable credentials are found, tests here skip with a
   message explaining that, rather than failing.

   For tests that need no login at all, see test_live_unauthenticated.py instead.
"""

from __future__ import annotations

import pytest

from codingame_client.client.async_.raw_client import CgAsyncClientHttpError, CgAsyncRawClient
from codingame_client.client.common.credentials import get_credentials


def _require_real_credentials() -> None:
    credentials = get_credentials()
    if credentials.remember_me_cookie is None or credentials.cg_session_cookie is None:
        pytest.skip(
            "No logged-in credentials available; run "
            "`python -m codingame_client.async_.browser_login` first."
        )


@pytest.mark.live
async def test_find_unread_notifications_live() -> None:
    _require_real_credentials()
    async with CgAsyncRawClient() as client:
        await client.login()
        try:
            notifications = await client.service_request_to_list(
                "Notification", "findUnreadNotifications", [client.codingamer_id]
            )
        except CgAsyncClientHttpError as e:
            pytest.fail(f"Authenticated request failed; credentials may be stale: {e}")
    assert isinstance(notifications, list)
