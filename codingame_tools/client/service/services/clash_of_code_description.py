"""
Async ClashOfCodeDescription service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...common.protocol.clash_of_code_description import CgClashDescription
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient


class CgClashOfCodeDescriptionServiceHelper(CgServiceHelper["CgClashOfCodeDescriptionService"]):
    """Helper methods for CgClashOfCodeDescriptionService. Currently empty."""


class CgClashOfCodeDescriptionService(CgService):
    """Async ClashOfCodeDescription service endpoint."""

    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "ClashOfCodeDescription")
        self.helper = CgClashOfCodeDescriptionServiceHelper(self)

    async def get_clash_description(self) -> CgClashDescription:
        """Get localized help/explainer content for Clash of Code.

        Returns:
            A CgClashDescription object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_description = await self.service_request_to_dict("getClashDescription")
        return CgClashDescription.from_dict(raw_description)
