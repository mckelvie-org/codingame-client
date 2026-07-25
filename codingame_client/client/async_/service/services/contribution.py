"""
Async Contribution service endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ....common.protocol.contribution import CgContribution, CgPendingContribution
from ....common.raw_client import CgAuthenticationError
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

    async def find_new_contribution_count(
                self,
                codingamer_id: int | None = None,
                since: datetime | None = None,
            ) -> int:
        """Count new contributions (e.g. community puzzles) published since a given point in
           time, for a given codingamer.

           `since` is sent to the server as a bare epoch-millis integer, like every other
           epoch-millis argument in this API (including FeaturedEvent/findNewFeaturedEventCount,
           where CodinGame's own web client sends a quoted string but a bare int was confirmed
           to work equally well--see `CgAsyncFeaturedEventService.find_new_featured_event_count`).

        Args:
            codingamer_id: The codingamer to count new contributions for. If not provided,
                           defaults to the logged-in codingamer's ID.
            since:         Count contributions published after this point in time. If not
                           provided, defaults to now (which will always yield 0--callers
                           interested in a nonzero count should track their own reference
                           point, e.g. the last time they called this). Naive datetimes are
                           interpreted as local time (matching Python's own
                           `datetime.timestamp()` behavior).

        Returns:
            The number of new contributions published since `since`.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not an int.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        if since is None:
            since = datetime.now(timezone.utc)
        since_ms = int(since.timestamp() * 1000)
        result = await self.service_request("findNewContributionCount", [codingamer_id, since_ms])
        return cast(int, result)

    async def get_all_pending_contributions(
                self,
                contribution_type_filter: str = "ALL",
                codingamer_id: int | None = None,
                page: int = 1,
            ) -> list[CgPendingContribution]:
        """Get pending (community-review-queue) contributions.

           Raw argument order is `[page, contribution_type_filter, codingamer_id]`; this method
           reorders them to put the more commonly-varied `contribution_type_filter` first.

           `codingamer_id` must equal the logged-in codingamer's own ID--the server rejects any
           other value with a 403 (`UserRequired: Only a logged user is authorized to perform
           this operation`), confirmed empirically. It does NOT filter results to contributions
           authored by that codingamer (a single call returned contributions from 30 different
           authors)--it's presumably used to compute per-item context (e.g.
           `CgPendingContribution.user_moderation_status`) relative to the viewer, similar to
           `current_codingamer_id` on `CgAsyncCodingamerService.find_followers`.

           `contribution_type_filter` accepts coarse category values, confirmed empirically:
           "ALL" (every type), "CLASHOFCODE" (only Clash of Code), "PUZZLE" (every puzzle
           subtype--"PUZZLE_INOUT", "PUZZLE_OPTI", "PUZZLE_SOLO", "PUZZLE_MULTI--but not
           "CLASHOFCODE"). An unrecognized value (e.g. one of the specific `type` values itself,
           like "PUZZLE_INOUT") does not filter or error--it behaves like "ALL".

           `page` is assumed to be a 1-indexed page number, but this is not fully confirmed:
           `page=1` returned all 57 currently-pending contributions in one call; `page=0` caused
           a 500 Internal Server Error; every `page >= 2` tried returned an empty list. That's
           consistent with simple pagination where all current matches fit on page 1, but true
           multi-page behavior (page size, etc.) has never been observed.

        Args:
            contribution_type_filter: Category filter; see above. Defaults to "ALL".
            codingamer_id: Must equal the logged-in codingamer's own ID (server-enforced; see
                           above). If not provided, defaults to the logged-in codingamer's ID.
            page:          Assumed 1-indexed page number; see above. Defaults to 1.

        Returns:
            A list of CgPendingContribution objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx (e.g. 403 if `codingamer_id` is not your own, or
                500 if `page` is 0), or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_contributions = await self.service_request_to_list(
                "getAllPendingContributions", [page, contribution_type_filter, codingamer_id])
        return CgPendingContribution.from_list(cast(list[JsonDict], raw_contributions))
