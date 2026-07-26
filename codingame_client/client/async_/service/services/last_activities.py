"""
Async LastActivities service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ....common.protocol.last_activities import CgLastActivity
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncLastActivitiesServiceHelper(CgAsyncServiceHelper["CgAsyncLastActivitiesService"]):
    """Helper methods for CgAsyncLastActivitiesService. Currently empty."""


class CgAsyncLastActivitiesService(CgAsyncService):
    """Async LastActivities service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "LastActivities")
        self.helper = CgAsyncLastActivitiesServiceHelper(self)

    async def get_last_activities(
                self,
                codingamer_id: int | None = None,
                limit: int = 4,
            ) -> list[CgLastActivity]:
        """Get a codingamer's most recent activity feed entries.

        Args:
            codingamer_id: The codingamer whose recent activity to list. If not provided,
                           defaults to the logged-in codingamer's ID.
            limit:         Maximum number of activity entries to return. Defaults to 4 (the only
                           value observed in practice, believed to be the max entry count).

        Returns:
            A list of CgLastActivity objects, most recent first.

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
        raw_activities = await self.service_request_to_list(
                "getLastActivities", [codingamer_id, limit])
        return CgLastActivity.from_list(cast(list[JsonDict], raw_activities))
