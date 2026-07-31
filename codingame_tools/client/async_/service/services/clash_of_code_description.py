"""
Async ClashOfCodeDescription service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.clash_of_code_description import CgClashDescription
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncClashOfCodeDescriptionServiceHelper(CgAsyncServiceHelper["CgAsyncClashOfCodeDescriptionService"]):
    """Helper methods for CgAsyncClashOfCodeDescriptionService. Currently empty."""


class CgAsyncClashOfCodeDescriptionService(CgAsyncService):
    """Async ClashOfCodeDescription service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "ClashOfCodeDescription")
        self.helper = CgAsyncClashOfCodeDescriptionServiceHelper(self)

    async def get_clash_description(self) -> CgClashDescription:
        """Get localized help/explainer content for Clash of Code.

        Returns:
            A CgClashDescription object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_description = await self.service_request_to_dict("getClashDescription")
        return CgClashDescription.from_dict(raw_description)
