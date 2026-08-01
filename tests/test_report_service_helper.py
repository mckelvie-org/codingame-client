"""Unit tests for CgAsyncReportServiceHelper.find_report_by_submission_when_ready--the polling
   wrapper around Report/findReportBySubmission added after live confirmation that calling it
   immediately after TestSession/submit can race server-side grading (every field but
   best_score/validator_shareable entirely absent).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from datetime import timezone

import pytest

from codingame_tools.client.async_.service.services.report import CgAsyncReportServiceHelper
from codingame_tools.client.common.protocol.report import (
    CgReportPuzzleProgress,
    CgSubmissionReport,
    CgValidatorResult,
)
from codingame_tools.common.dataclass_wizard_x import CgEpochMillis

_NOT_READY_REPORT = CgSubmissionReport(best_score=100.0, validator_shareable=False)

_READY_REPORT = CgSubmissionReport(
        best_score=100.0, validator_shareable=True, codingamer_id=1, submission_id=424242,
        score=100.0, achievements_completed=True, shared=False,
        puzzle_progress=CgReportPuzzleProgress(
                id=10075, achievement_count=1, done_achievement_count=1, validator_score=0,
            ),
        validators=[CgValidatorResult(method_name="Validator_1", name="Test 1", difficulty=100, success=True)],
        achievements=[], _completed_time=CgEpochMillis.fromtimestamp(0, tz=timezone.utc),
    )


class _FakeService:
    def __init__(self, reports: list[CgSubmissionReport]) -> None:
        self._reports = list(reports)
        self.find_calls: list[int] = []

    async def find_report_by_submission(self, submission_id: int) -> CgSubmissionReport:
        self.find_calls.append(submission_id)
        if len(self._reports) > 1:
            return self._reports.pop(0)
        return self._reports[0]


def test_not_ready_report_lacks_all_but_two_fields() -> None:
    assert not _NOT_READY_REPORT.is_ready()
    assert _NOT_READY_REPORT.submission_id is None
    assert _NOT_READY_REPORT.score is None


def test_ready_report_is_ready() -> None:
    assert _READY_REPORT.is_ready()


async def test_returns_immediately_when_already_ready() -> None:
    service = _FakeService([_READY_REPORT])
    helper = CgAsyncReportServiceHelper(service)  # type: ignore[arg-type]

    result = await helper.find_report_by_submission_when_ready(424242)

    assert result is _READY_REPORT
    assert service.find_calls == [424242]


async def test_polls_until_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(
            "codingame_tools.client.async_.service.services.report.asyncio.sleep", fake_sleep)
    service = _FakeService([_NOT_READY_REPORT, _NOT_READY_REPORT, _READY_REPORT])
    helper = CgAsyncReportServiceHelper(service)  # type: ignore[arg-type]

    result = await helper.find_report_by_submission_when_ready(424242)

    assert result is _READY_REPORT
    assert len(service.find_calls) == 3
    assert len(sleep_calls) == 2


async def test_raises_timeout_error_if_never_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.async_.service.services.report.asyncio.sleep", fake_sleep)
    service = _FakeService([_NOT_READY_REPORT])
    helper = CgAsyncReportServiceHelper(service)  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        await helper.find_report_by_submission_when_ready(424242, max_wait_seconds=0.01)


async def test_on_poll_called_for_each_not_ready_report_but_not_the_final_one(
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.async_.service.services.report.asyncio.sleep", fake_sleep)
    service = _FakeService([_NOT_READY_REPORT, _NOT_READY_REPORT, _READY_REPORT])
    helper = CgAsyncReportServiceHelper(service)  # type: ignore[arg-type]
    seen: list[CgSubmissionReport] = []

    async def record(report: CgSubmissionReport) -> None:
        seen.append(report)

    result = await helper.find_report_by_submission_when_ready(424242, on_poll=record)

    assert result is _READY_REPORT
    assert seen == [_NOT_READY_REPORT, _NOT_READY_REPORT]


async def test_on_poll_exception_aborts_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.async_.service.services.report.asyncio.sleep", fake_sleep)
    service = _FakeService([_NOT_READY_REPORT, _READY_REPORT])
    helper = CgAsyncReportServiceHelper(service)  # type: ignore[arg-type]

    async def cancel(report: CgSubmissionReport) -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        await helper.find_report_by_submission_when_ready(424242, on_poll=cancel)

    # aborted after the first not-ready poll--never reached the ready report
    assert len(service.find_calls) == 1
