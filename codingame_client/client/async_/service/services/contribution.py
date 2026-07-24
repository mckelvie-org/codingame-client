"""
Async Contribution service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.contribution import CgContribution
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncContributionService(CgAsyncService):
    """Async Contribution service endpoint."""
    
    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Contribution")

    async def find_contribution(
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
                "findContribution", [contribution_id, arg2])
        return CgContribution.from_dict(raw_contribution)
