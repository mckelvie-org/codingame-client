"""Unit tests for CgContributionServiceHelper.update_contribution's HTTP-524 retry/polling
   logic (`_poll_until_committed`), including its `on_poll` callback--parallel to
   test_report_service_helper.py's coverage of the Report service's own polling helper.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

import pytest

from codingame_tools.client.common.protocol.contribution import (
    CgContribution,
    CgContributionData,
    CgContributionVersion,
    CgTestCase,
)
from codingame_tools.client.common.raw_client import CgClientHttpError
from codingame_tools.client.service.services.contribution import CgContributionServiceHelper


def _make_data() -> CgContributionData:
    return CgContributionData(
            title="My Puzzle", statement="The statement", input_description="Input desc",
            output_description="Output desc", constraints="1 <= N <= 100", difficulty="easy",
            stub_generator="read int N;", topics=[],
            test_cases=[CgTestCase(title="Case A", test_in="1", test_out="2", is_test=True,
                                    is_validator=False, need_validation=True)],
            solution_language="Python3", solution="print('hi')", cover_binary_id=555,
        )


def _make_contribution(data: CgContributionData, *, version: int) -> CgContribution:
    return CgContribution(
            id=1, active_version=version, score=0, votable_id=2, codingamer_id=7412395,
            views=0, commentable_id=3, title=data.title, status="PENDING", nickname="tester",
            public_handle="handle-1", codingamer_handle="cg-handle",
            last_version=CgContributionVersion(
                    version=version, data=data, statement_html="<p>rendered</p>",
                    draft=True, ready_for_moderation=False,
                ),
            avatar=0, comment_count=0, up_votes=0, down_votes=0, editable=True,
            draft=True, ready_for_moderation=False, contribution_type="PUZZLE_INOUT",
        )


class _FakeService:
    def __init__(self, find_results: list[CgContribution]) -> None:
        self._find_results = list(find_results)
        self.update_calls = 0
        self.find_calls: list[str] = []

    async def update_contribution(self, *args: object, **kwargs: object) -> CgContribution:
        self.update_calls += 1
        raise CgClientHttpError("Timeout", status_code=524)

    async def find_contribution(self, contribution_id: str) -> CgContribution:
        self.find_calls.append(contribution_id)
        if len(self._find_results) > 1:
            return self._find_results.pop(0)
        return self._find_results[0]


async def test_returns_once_version_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.service.services.contribution.asyncio.sleep", fake_sleep)
    data = _make_data()
    stale = _make_contribution(data, version=3)
    committed = _make_contribution(data, version=4)
    service = _FakeService([stale, stale, committed])
    helper = CgContributionServiceHelper(service)  # type: ignore[arg-type]

    result = await helper.update_contribution(
            "handle-1", "PUZZLE_INOUT", data, True, False, prev_version=3)

    assert result is committed
    assert len(service.find_calls) == 3


async def test_raises_timeout_error_if_never_committed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.service.services.contribution.asyncio.sleep", fake_sleep)
    data = _make_data()
    stale = _make_contribution(data, version=3)
    service = _FakeService([stale])
    helper = CgContributionServiceHelper(service)  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        await helper.update_contribution(
                "handle-1", "PUZZLE_INOUT", data, True, False, prev_version=3,
                max_wait_seconds=0.01)


async def test_on_poll_called_with_each_stale_contribution_but_not_the_final_one(
            monkeypatch: pytest.MonkeyPatch,
        ) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.service.services.contribution.asyncio.sleep", fake_sleep)
    data = _make_data()
    stale = _make_contribution(data, version=3)
    committed = _make_contribution(data, version=4)
    service = _FakeService([stale, stale, committed])
    helper = CgContributionServiceHelper(service)  # type: ignore[arg-type]
    seen: list[CgContribution] = []

    async def record(contribution: CgContribution) -> None:
        seen.append(contribution)

    result = await helper.update_contribution(
            "handle-1", "PUZZLE_INOUT", data, True, False, prev_version=3, on_poll=record)

    assert result is committed
    assert seen == [stale, stale]


async def test_on_poll_not_called_when_no_524_occurs() -> None:
    class _NoErrorService(_FakeService):
        async def update_contribution(self, *args: object, **kwargs: object) -> CgContribution:
            self.update_calls += 1
            return committed

    data = _make_data()
    committed = _make_contribution(data, version=4)
    service = _NoErrorService([])
    helper = CgContributionServiceHelper(service)  # type: ignore[arg-type]
    seen: list[CgContribution] = []

    async def record(contribution: CgContribution) -> None:
        seen.append(contribution)

    result = await helper.update_contribution(
            "handle-1", "PUZZLE_INOUT", data, True, False, prev_version=3, on_poll=record)

    assert result is committed
    assert seen == []


async def test_on_poll_exception_aborts_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr(
            "codingame_tools.client.service.services.contribution.asyncio.sleep", fake_sleep)
    data = _make_data()
    stale = _make_contribution(data, version=3)
    committed = _make_contribution(data, version=4)
    service = _FakeService([stale, committed])
    helper = CgContributionServiceHelper(service)  # type: ignore[arg-type]

    async def cancel(contribution: CgContribution) -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        await helper.update_contribution(
                "handle-1", "PUZZLE_INOUT", data, True, False, prev_version=3, on_poll=cancel)

    # aborted after the first stale poll--never reached the committed contribution
    assert len(service.find_calls) == 1
