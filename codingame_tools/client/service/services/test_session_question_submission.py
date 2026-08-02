"""
Async TestSessionQuestionSubmission service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ...common.protocol.test_session_question_submission import CgTestSessionQuestionSubmission
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient


class CgTestSessionQuestionSubmissionServiceHelper(CgServiceHelper["CgTestSessionQuestionSubmissionService"]):
    """Helper methods for CgTestSessionQuestionSubmissionService. Currently empty."""


class CgTestSessionQuestionSubmissionService(CgService):
    """Async TestSessionQuestionSubmission service endpoint."""

    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "TestSessionQuestionSubmission")
        self.helper = CgTestSessionQuestionSubmissionServiceHelper(self)

    async def find_all_submissions(
                self,
                test_session_handle: str,
            ) -> list[CgTestSessionQuestionSubmission]:
        """Find all past submissions for a puzzle, most recent first.

        Args:
            test_session_handle: The puzzle's test session handle (see
                                  `CgTestSessionService.start_test_session`).

        Returns:
            A list of CgTestSessionQuestionSubmission objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        raw_submissions = await self.service_request_to_list("findAllSubmissions", [test_session_handle])
        return CgTestSessionQuestionSubmission.from_list(cast(list[JsonDict], raw_submissions))
