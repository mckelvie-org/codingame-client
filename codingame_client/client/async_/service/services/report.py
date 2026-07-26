"""
Async Report service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....common.protocol.report import CgSubmissionReport
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncReportServiceHelper(CgAsyncServiceHelper["CgAsyncReportService"]):
    """Helper methods for CgAsyncReportService. Currently empty."""


class CgAsyncReportService(CgAsyncService):
    """Async Report service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Report")
        self.helper = CgAsyncReportServiceHelper(self)

    async def find_report_by_submission(self, submission_id: int) -> CgSubmissionReport:
        """Find the results report for a single puzzle submission.

        Args:
            submission_id: Numeric ID of the submission (e.g.
                           `CgTestSessionQuestion.last_submission_id`).

        Returns:
            A CgSubmissionReport object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_report = await self.service_request_to_dict("findReportBySubmission", [submission_id])
        return CgSubmissionReport.from_dict(raw_report)
