"""
Async User service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.user import CgUserProperties
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncUserServiceHelper(CgAsyncServiceHelper["CgAsyncUserService"]):
    """Helper methods for CgAsyncUserService. Currently empty."""


class CgAsyncUserService(CgAsyncService):
    """Async User service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "User")
        self.helper = CgAsyncUserServiceHelper(self)

    async def update_user_properties(
                self,
                properties: CgUserProperties,
                codingamer_id: int | None = None,
            ) -> None:
        """Update a subset of a codingamer's account properties.

           Only fields explicitly set on `properties` (i.e. not left as None) are sent to the
           server and updated--all other properties are left unchanged. The server returns an
           empty string on success, which is discarded.

           Only one property (`contributions_list_last_visit`) is known and modeled on
           `CgUserProperties` so far; this will need to grow incrementally as more properties
           are discovered.

        Args:
            properties:    The properties to update; unset (None) fields are left unchanged.
            codingamer_id: The codingamer to update. If not provided, defaults to the logged-in
                           codingamer's ID.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, or if the status code is not 2xx.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        await self.service_request("updateUserProperties", [codingamer_id, properties.to_dict()])
