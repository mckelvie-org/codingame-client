"""
Async CodingamerPuzzleTopic service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ....common.protocol.codingamer_puzzle_topic import CgCodingamerPuzzleTopic
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncCodingamerPuzzleTopicService(CgAsyncService):
    """Async CodingamerPuzzleTopic service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "CodingamerPuzzleTopic")

    async def find_topics_by_codingamer_id(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgCodingamerPuzzleTopic]:
        """Find the puzzle topics a codingamer has made progress on (e.g. "Arrays", "BFS"),
           along with a per-topic puzzle count and last-progress timestamp.

        Args:
            codingamer_id: The codingamer whose puzzle topic progress to list. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgCodingamerPuzzleTopic objects.

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
        raw_topics = await self.service_request_to_list(
                "findTopicsByCodingamerId", [codingamer_id])
        return CgCodingamerPuzzleTopic.from_list(cast(list[JsonDict], raw_topics))
