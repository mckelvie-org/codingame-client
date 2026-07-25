"""
Async ClashOfCode service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.clash_of_code import CgClash, CgClashRank
from ....common.raw_client import CgAuthenticationError
from ...raw_client import CgAsyncClientHttpError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncClashOfCodeService(CgAsyncService):
    """Async ClashOfCode service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "ClashOfCode")

    async def get_clash_rank_by_codingamer_id(
                self,
                codingamer_id: int | None = None,
            ) -> CgClashRank | None:
        """Get a codingamer's global Clash of Code ranking.

           Returns None if the codingamer has never played Clash of Code--the server responds
           with a genuine (not an error) JSON `null` in that case, rather than 404 or an empty
           dict. This uses `service_request` (untyped `JsonData`) rather than
           `service_request_to_dict`, since the latter would reject a `null` response as an
           error--there would be no way to distinguish "no rank" from an actual failure.

        Args:
            codingamer_id: The codingamer's numeric ID. If not provided, defaults to the
                           logged-in codingamer's ID.

        Returns:
            A CgClashRank object, or None if the codingamer has never played Clash of Code.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is neither a dict nor null.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_rank = await self.service_request(
                "getClashRankByCodinGamerId", [codingamer_id])
        if raw_rank is None:
            return None
        if not isinstance(raw_rank, dict):
            raise CgAsyncClientHttpError(
                    f"Invalid response type: expected a JSON dictionary or null, got {type(raw_rank).__name__}",
                    content=raw_rank,
                )
        return CgClashRank.from_dict(raw_rank)

    async def find_clash_by_handle(
                self,
                handle: str,
            ) -> CgClash:
        """Find a Clash of Code session by its handle.

           `handle` must be a clash-instance handle (e.g. a `CgClashSlot.clash_handle` from
           FeaturedEvent/findClashSlots)--confirmed empirically, neither a codingamer's public
           handle nor the parent `CgFeaturedEvent.handle` are accepted here (both rejected with
           a 422).

        Args:
            handle: The opaque clash-instance handle string.

        Returns:
            A CgClash object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_clash = await self.service_request_to_dict("findClashByHandle", [handle])
        return CgClash.from_dict(raw_clash)
