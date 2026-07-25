"""
Async Achievement service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ....common.protocol.achievement import CgAchievement
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncAchievementService(CgAsyncService):
    """Async Achievement service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Achievement")

    async def find_by_codingamer_id(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgAchievement]:
        """Find the achievements a codingamer has unlocked.

        Args:
            codingamer_id: The codingamer whose achievements to list. If not provided, defaults
                           to the logged-in codingamer's ID.

        Returns:
            A list of CgAchievement objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_achievements = await self.service_request_to_list("findByCodingamerId", [codingamer_id])
        return CgAchievement.from_list(cast(list[JsonDict], raw_achievements))
