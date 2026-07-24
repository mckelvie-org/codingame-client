"""
Async well-typed (dataclass-based) client for the CodinGame API.
"""

from __future__ import annotations

from typing import cast

from json_data_types import JsonDict

from ....client.common.protocol.codingamer import CgCodingamePointsStats
from ....client.common.protocol.contribution import CgContribution
from ....client.common.protocol.notification import CgNotification
from ....client.common.raw_client import CgAuthenticationError
from ..raw_client import CgAsyncRawClient

__all__ = [
    "CgAsyncClient",
]

class CgAsyncClient(CgAsyncRawClient):
    """Async client with well-typed (dataclass-based) methods for specific CodinGame API endpoints,
       layered on top of the generic, schema-agnostic `CgAsyncRawClient`."""

    async def notification_find_unread_notifications(
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
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        await self.require_authenticate()
        if codingamer_id is None:
            codingamer_id = self.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_notifications = await self.service_request_to_list(
                "Notification", "findUnreadNotifications", [codingamer_id])
        return CgNotification.from_list(cast(list[JsonDict], raw_notifications))

    async def contribution_find_contribution(
                self,
                contribution_id: str,
                arg2: bool = True,
            ) -> CgContribution:
        """Find a contribution by its opaque contribution ID.

        Args:
            contribution_id: The opaque contribution ID string (see `CgContributionId`).
            arg2:            Second positional argument to the underlying findContribution API
                              call. Purpose unknown; defaults to True.

        Returns:
            A CgContribution object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_contribution = await self.service_request_to_dict(
                "Contribution", "findContribution", [contribution_id, arg2])
        return CgContribution.from_dict(raw_contribution)

    async def codingamer_find_codingame_points_stats_by_handle(
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
                "CodinGamer", "findCodingamePointsStatsByHandle", [handle])
        return CgCodingamePointsStats.from_dict(raw_stats)
