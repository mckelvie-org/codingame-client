"""
Async Report service endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ...common.protocol.report import CgSubmissionReport
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient

logger = logging.getLogger(__name__)


class CgReportServiceHelper(CgServiceHelper["CgReportService"]):
    """Helper methods for CgReportService."""

    _POLL_INTERVAL_SECONDS = 3.0
    """How often to re-check `find_report_by_submission` while waiting for grading to finish in
       `find_report_by_submission_when_ready`."""

    async def find_report_by_submission_when_ready(
                self, submission_id: int, *, max_wait_seconds: float = 60.0,
                on_poll: Callable[[CgSubmissionReport], Awaitable[None]] | None = None,
            ) -> CgSubmissionReport:
        """Poll `find_report_by_submission` until grading has finished, adding retry/polling on
           top of the plain `CgReportService.find_report_by_submission`.

           Calling `findReportBySubmission` immediately after `TestSession/submit` can race
           server-side grading--see `CgSubmissionReport`'s class docstring for a confirmed-live
           example (every field but `best_score`/`validator_shareable` entirely absent). This
           polls every `_POLL_INTERVAL_SECONDS` until `CgSubmissionReport.is_ready()` is true.

        Args:
            submission_id: Numeric ID of the submission (e.g.
                           `CgTestSessionQuestion.last_submission_id`).
            max_wait_seconds: How long to keep polling before giving up, in seconds. 0 means wait
                               indefinitely.
            on_poll: If given, awaited with each not-yet-ready `CgSubmissionReport` observed
                     (i.e. every poll except the final, ready one). Currently these carry no real
                     progress info (see the class docstring)--the main use is as a cancellation
                     hook: raise from `on_poll` (or let an `await` inside it raise, e.g.
                     `asyncio.CancelledError`) to abort the wait immediately, instead of only
                     being able to give up via `max_wait_seconds`. Any exception it raises
                     propagates out of this method uncaught.

        Returns:
            The first `CgSubmissionReport` observed with `is_ready()` true.

        Raises:
            CgAuthenticationError, CgClientHttpError: see `find_report_by_submission`.
            TimeoutError: if grading hasn't finished before `max_wait_seconds` elapses.
        """
        deadline = None if max_wait_seconds <= 0 else time.monotonic() + max_wait_seconds
        while True:
            report = await self.service.find_report_by_submission(submission_id)
            if report.is_ready():
                return report
            if on_poll is not None:
                await on_poll(report)
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for the report for submission {submission_id} to "
                    "finish grading; it may still complete server-side.")
            logger.info("find_report_by_submission_when_ready: submission %s not graded yet, "
                        "polling again in %.0fs...", submission_id, self._POLL_INTERVAL_SECONDS)
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)


class CgReportService(CgService):
    """Async Report service endpoint."""

    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "Report")
        self.helper = CgReportServiceHelper(self)

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
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_report = await self.service_request_to_dict("findReportBySubmission", [submission_id])
        return CgSubmissionReport.from_dict(raw_report)
