"""
Async Notification service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ...common.protocol.notification import CgNotification
from ...common.raw_client import CgAuthenticationError
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient


class CgNotificationServiceHelper(CgServiceHelper["CgNotificationService"]):
    """Helper methods for CgNotificationService. Currently empty."""


class CgNotificationService(CgService):
    """Async Notification service endpoint."""
    
    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "Notification")
        self.helper = CgNotificationServiceHelper(self)

    async def find_unread_notifications(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgNotification]:
        """Find unread notifications for a codingamer.

           This endpoint always requires a valid login, regardless of whose notifications are
           being queried.

        Args:
            codingamer_id: The codingamer to find unread notifications for. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgNotification objects, most recent first.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        await self.require_authenticate()
        if codingamer_id is None:
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_notifications = await self.service_request_to_list(
                "findUnreadNotifications", [codingamer_id])
        return CgNotification.from_list(cast(list[JsonDict], raw_notifications))
