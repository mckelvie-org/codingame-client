"""
Async Survey service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.survey import CgSurvey
from ....common.raw_client import CgAuthenticationError
from ...raw_client import CgAsyncClientHttpError
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncSurveyServiceHelper(CgAsyncServiceHelper["CgAsyncSurveyService"]):
    """Helper methods for CgAsyncSurveyService. Currently empty."""


class CgAsyncSurveyService(CgAsyncService):
    """Async Survey service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Survey")
        self.helper = CgAsyncSurveyServiceHelper(self)

    async def find_survey(
                self,
                codingamer_id: int | None = None,
                limit: int = 2,
            ) -> CgSurvey | None:
        """Find a survey to potentially show a codingamer.

           UNVERIFIED: every account tested (including a couple of different real accounts)
           returned a bare `null`, so the real response shape (`CgSurvey`) is an empty
           placeholder pending a real example. `limit`'s purpose is unconfirmed too--assumed
           (per the observed default value of 2) to cap the number of surveys returned, but this
           couldn't be verified empirically since no non-null response was ever observed.

           Uses `service_request` (untyped `JsonData`) rather than `service_request_to_dict`,
           since the latter would reject the (apparently common) `null` response as an error.

        Args:
            codingamer_id: The codingamer to find a survey for. If not provided, defaults to
                           the logged-in codingamer's ID.
            limit:         Assumed maximum number of results; unconfirmed. Defaults to 2 (the
                           only value observed in practice).

        Returns:
            A CgSurvey object, or None if no survey is currently applicable.

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
        raw_survey = await self.service_request("findSurvey", [codingamer_id, limit])
        if raw_survey is None:
            return None
        if not isinstance(raw_survey, dict):
            raise CgAsyncClientHttpError(
                    f"Invalid response type: expected a JSON dictionary or null, got {type(raw_survey).__name__}",
                    content=raw_survey,
                )
        return CgSurvey.from_dict(raw_survey)
