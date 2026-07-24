"""
Async CodinGamer service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.codingamer import CgCodingamePointsStats
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncCodingamerService(CgAsyncService):
    """Async Codingamer service endpoint."""
    
    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "CodinGamer")

    async def find_codingame_points_stats_by_handle(
                self,
                handle: str,
            ) -> CgCodingamePointsStats:
        """Find a codingamer's points/ranking stats by their opaque public handle.

        Args:
            handle: The codingamer's opaque public handle string (not their numeric ID).

        Returns:
            A CgCodingamePointsStats object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_stats = await self.service_request_to_dict(
                "findCodingamePointsStatsByHandle", [handle])
        return CgCodingamePointsStats.from_dict(raw_stats)
