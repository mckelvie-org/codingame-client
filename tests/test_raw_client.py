"""Tests for codingame_client.async_.raw_client, backed by VCR cassettes (see conftest.py).

These exercise genuinely public, unauthenticated endpoints, so the cassettes here were
recorded from real live requests but require no login and carry no cookie data.
"""

from __future__ import annotations

import pytest

from codingame_client.async_.raw_client import CgAsyncClientHttpError, CgAsyncRawClient


@pytest.mark.usefixtures("vcr_cassette")
async def test_find_codingamer_public_informations() -> None:
    async with CgAsyncRawClient() as client:
        result = await client.service_request_to_dict(
            "CodinGamer", "findCodinGamerPublicInformations", [1486857],
            require_login=False,
        )
    assert result["userId"] == 1486857
    assert result["pseudo"] == "sammck"
    assert "publicHandle" in result


@pytest.mark.usefixtures("vcr_cassette")
async def test_service_request_body_must_be_json_array_error() -> None:
    """Regression test: the request body must be a bare JSON array, not {"args": [...]}."""
    async with CgAsyncRawClient() as client:
        with pytest.raises(CgAsyncClientHttpError) as exc_info:
            async with client.session.post(
                f"{client.CODINGAME_SERVICES_URL}CodinGamer/findCodinGamerPublicInformations",
                json={"args": [1486857]},
            ) as response:
                await client.get_json_data_response(response)
    error = exc_info.value
    assert error.status_code == 400
    assert error.api_error_response is not None
    assert error.api_error_response.code == "BODY_MUST_BE_JSON_ARRAY"
