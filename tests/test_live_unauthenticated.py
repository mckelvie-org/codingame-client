"""Tests marked @pytest.mark.live_unauthenticated hit the real CodinGame API directly on
   every run--no cassette, no caching--but call genuinely public endpoints that require no
   login. They are excluded by default (see addopts in [tool.pytest.ini_options]) and never
   run in CI; run them explicitly with `pdm run test-live-unauthenticated` or
   `pytest -m live_unauthenticated`.

   For tests that require a logged-in session, see test_live.py instead.
"""

from __future__ import annotations

import pytest

from codingame_client.client.async_.raw_client import CgAsyncRawClient


@pytest.mark.live_unauthenticated
async def test_find_codingamer_public_informations_live() -> None:
    async with CgAsyncRawClient() as client:
        result = await client.service_request_to_dict(
            "CodinGamer", "findCodinGamerPublicInformations", [1486857],
            require_login=False,
        )
    assert result["userId"] == 1486857
