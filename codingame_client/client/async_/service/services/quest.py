"""
Async Quest service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ....common.protocol.quest import CgQuestMap
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncQuestService(CgAsyncService):
    """Async Quest service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Quest")

    async def find_quest_map(
                self,
                codingamer_id: int | None = None,
            ) -> CgQuestMap:
        """Find a codingamer's quest map (the graph of quest nodes and links shown on the
           "Path" / quest-tree page), including their own progress on each quest.

        Args:
            codingamer_id: The codingamer whose quest map to fetch. If not provided, defaults
                           to the logged-in codingamer's ID.

        Returns:
            A CgQuestMap object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_map = await self.service_request_to_dict("findQuestMap", [codingamer_id])
        return CgQuestMap.from_dict(raw_map)

    async def count_lootable_quests(
                self,
                codingamer_id: int | None = None,
            ) -> int:
        """Count a codingamer's completed-but-unclaimed quests (i.e. quests where
           `CgCodingamerQuest.completion_time` is set but `loot_time` is still None).

        Args:
            codingamer_id: The codingamer to count lootable quests for. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            The number of lootable (completed, reward not yet claimed) quests.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not an int.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        result = await self.service_request("countLootableQuests", [codingamer_id])
        return cast(int, result)
