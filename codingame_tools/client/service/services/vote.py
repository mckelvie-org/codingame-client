"""
Async Vote service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ...common.protocol.vote import CgVotableValue
from ...common.raw_client import CgAuthenticationError
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient


class CgVoteServiceHelper(CgServiceHelper["CgVoteService"]):
    """Helper methods for CgVoteService. Currently empty."""


class CgVoteService(CgService):
    """Async Vote service endpoint."""

    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "Vote")
        self.helper = CgVoteServiceHelper(self)

    async def find_votable_values_by_id(
                self,
                votable_id: int,
                codingamer_id: int | None = None,
            ) -> list[CgVotableValue]:
        """Find a votable's current up/down-vote tally (and the querying codingamer's own vote,
           if any). Despite the response being a bare JSON array, only a single-`votable_id`
           call has been confirmed so far (returning a single-element list)--passing a JSON
           array of IDs for `votable_id` was tried and rejected by the server with a 422, so
           there is no known batch form.

        Args:
            votable_id:    The votable entity's ID (e.g. `CgContribution.votable_id`).
            codingamer_id: The codingamer whose own vote to report (`CgVotableValue.
                           user_vote_value`). If not provided, defaults to the logged-in
                           codingamer's ID. Confirmed required by the server--omitting it
                           entirely (rather than defaulting it here) is rejected with a 422.

        Returns:
            A list of CgVotableValue objects (one element, for `votable_id`, in every case
            confirmed so far).

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_values = await self.service_request_to_list(
                "findVotableValuesById", [votable_id, codingamer_id])
        return CgVotableValue.from_list(cast(list[JsonDict], raw_values))
