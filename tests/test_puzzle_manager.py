"""Unit tests for codingame_tools.puzzle_manager.manager.CgPuzzleManager (`import_`/`repair`/
   `diff`/`discard_local`/`push`/`play`), against a fake, duck-typed client (services.puzzle,
   services.test_session)--no real CgAsyncClient/network involved.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

import shutil
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest

from codingame_tools.client.common.protocol.last_activities import CgLastActivityPuzzle, CgPuzzleFeedback
from codingame_tools.client.common.protocol.test_session import (
    CgLastActivityContributor,
    CgPlayComparison,
    CgPlayRequest,
    CgPlayResult,
    CgSubmitRequest,
    CgTestSession,
    CgTestSessionAnswer,
    CgTestSessionContribution,
    CgTestSessionPuzzle,
    CgTestSessionQuestion,
    CgTestSessionQuestionDetails,
    CgTestSessionTestCase,
)
from codingame_tools.client.common.raw_client import CgDownloadFileResult
from codingame_tools.common.dataclass_wizard_x import CgEpochMillis
from codingame_tools.puzzle_manager.manager import (
    CgPuzzleLocalTestFailedError,
    CgPuzzleManager,
    CgPuzzleManagerError,
)
from codingame_tools.puzzle_manager.schema import CgPuzzleServerData
from codingame_tools.puzzle_manager.test_cases_dir import (
    TEST_META_FILE_NAME,
    CgPuzzleTestCaseMeta,
    normalize_test_label,
)


def _make_test_session(
            *,
            answer: CgTestSessionAnswer | None = None,
            contribution_type: str = "PUZZLE_INOUT",
            title: str = "Literary Alfabet Soupe",
            pretty_id: str = "literary-alfabet-soupe",
            puzzle_id: int = 10075,
            puzzle_handle: str = "puzzle-handle-1",
            test_session_handle: str = "session-handle-1",
            statement: str = "<p>statement</p>",
            stub_generator: str = "read a:int",
        ) -> CgTestSession:
    contributor = CgLastActivityContributor(user_id=1, pseudo="someone", public_handle="contributor-handle")
    contribution = CgTestSessionContribution(
            id=1, public_handle="contribution-handle", status="ACCEPTED", moderators=[],
            contribution_type=contribution_type,
        )
    question = CgTestSessionQuestionDetails(
            id=1094622, title=title, statement=statement, stub_generator=stub_generator,
            duration=1000, index=0, initial_id=1094622, user_id=1, available_languages=[],
            contributor=contributor, contribution=contribution,
            test_cases=[
                    CgTestSessionTestCase(index=1, input_binary_id=1, output_binary_id=2, label="Test 1"),
                    CgTestSessionTestCase(index=2, input_binary_id=3, output_binary_id=4, label="Test 2"),
                ],
            question_type="MULTIPLE_LANGUAGES",
        )
    current_question = CgTestSessionQuestion(last_submission_id=1, question=question, answer=answer)
    puzzle = CgTestSessionPuzzle(
            id=puzzle_id, handle=puzzle_handle, pretty_id=pretty_id, title=title, level="medium",
            details_page_url="/training/medium/literary-alfabet-soupe",
            forum_post_id="community-puzzle-literary-alfabet-soupe-puzzle-discussion/1",
        )
    return CgTestSession(
            test_session_handle=test_session_handle, test_session_id=1, user_id=1, test_type="PUZZLE",
            direct=False, need_account=True, shareable=True, show_replay_prompt=False,
            current_question=current_question, puzzle=puzzle, questions=[],
        )


def _make_progress(
            *,
            puzzle_id: int = 10075,
            pretty_id: str = "literary-alfabet-soupe",
            title: str = "Literary Alfabet Soupe",
            test_session_handle: str | None = "session-handle-1",
        ) -> CgLastActivityPuzzle:
    contributor = CgLastActivityContributor(user_id=1, pseudo="someone", public_handle="contributor-handle")
    progress = CgLastActivityPuzzle(
            id=puzzle_id, title=title, pretty_id=pretty_id, level="medium",
            details_page_url="/training/medium/literary-alfabet-soupe",
            forum_link="/community-puzzle-literary-alfabet-soupe-puzzle-discussion/1",
            contributor=contributor, feedback=CgPuzzleFeedback(feedback_id=1, feedbacks=[0, 0, 0, 0, 1]),
            topics=[], community_creation=True, cover_binary_id=1, achievement_count=0,
            done_achievement_count=0, attempt_count=1, solved_count=1, rank=0, validator_score=100,
            xp_points=10, puzzle_type="CODE", _creation_time=CgEpochMillis.fromtimestamp(0, tz=timezone.utc),
            test_session_handle=test_session_handle,
        )
    return progress


class _FakePuzzleService:
    def __init__(self, handle: str = "session-handle-1") -> None:
        self.handle = handle
        self.generate_calls: list[dict[str, Any]] = []
        self.progress_results: list[CgLastActivityPuzzle] = []
        self.find_progress_calls: list[list[int]] = []

    async def generate_session_from_puzzle_pretty_id(
                self, puzzle_pretty_id: str, codingamer_id: int | None = None,
            ) -> str:
        self.generate_calls.append({"puzzle_pretty_id": puzzle_pretty_id, "codingamer_id": codingamer_id})
        return self.handle

    async def find_progress_by_ids(
                self, puzzle_ids: list[int], codingamer_id: int | None = None, arg3: int = 2,
            ) -> list[CgLastActivityPuzzle]:
        self.find_progress_calls.append(puzzle_ids)
        return self.progress_results


class _FakeTestSessionService:
    def __init__(
                self, session: CgTestSession, *, play_result: CgPlayResult | None = None,
                submit_result: int = 424242,
            ) -> None:
        self.session = session
        self.play_result = play_result
        self.submit_result = submit_result
        self.start_calls: list[str] = []
        self.play_calls: list[dict[str, Any]] = []
        self.submit_calls: list[dict[str, Any]] = []

    async def start_test_session(self, test_session_handle: str) -> CgTestSession:
        self.start_calls.append(test_session_handle)
        return self.session

    async def play(self, test_session_handle: str, request: CgPlayRequest) -> CgPlayResult:
        self.play_calls.append({"test_session_handle": test_session_handle, "request": request})
        assert self.play_result is not None
        return self.play_result

    async def submit(
                self, test_session_handle: str, request: CgSubmitRequest, arg3: Any = None,
            ) -> int:
        self.submit_calls.append({"test_session_handle": test_session_handle, "request": request})
        return self.submit_result


class _FakeServices:
    def __init__(self, puzzle: _FakePuzzleService, test_session: _FakeTestSessionService) -> None:
        self.puzzle = puzzle
        self.test_session = test_session


class _FakeFileServletServlet:
    def __init__(self) -> None:
        self.download_calls: list[int] = []

    async def __call__(self, id: int) -> CgDownloadFileResult:  # noqa: A002
        self.download_calls.append(id)
        content = f"content-for-binary-{id}\n".encode()
        return CgDownloadFileResult.create(id=id, content=content, content_type="text/plain")


class _FakeServlets:
    def __init__(self, file_servlet: _FakeFileServletServlet) -> None:
        self.file_servlet = file_servlet


class _FakeClient:
    def __init__(
                self, puzzle: _FakePuzzleService, test_session: _FakeTestSessionService,
                file_servlet: _FakeFileServletServlet,
            ) -> None:
        self.services = _FakeServices(puzzle, test_session)
        self.servlets = _FakeServlets(file_servlet)


def _make_fake_client(
            session: CgTestSession, *, play_result: CgPlayResult | None = None,
        ) -> tuple[_FakeClient, _FakePuzzleService, _FakeTestSessionService, _FakeFileServletServlet]:
    puzzle_service = _FakePuzzleService(session.test_session_handle)
    test_session_service = _FakeTestSessionService(session, play_result=play_result)
    file_servlet = _FakeFileServletServlet()
    client = _FakeClient(puzzle_service, test_session_service, file_servlet)
    return client, puzzle_service, test_session_service, file_servlet


# --- import_ -----------------------------------------------------------------------------


async def test_import_with_existing_answer_uses_it(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('existing answer')\n", programming_language_id="Java")
    session = _make_test_session(answer=answer)
    client, puzzle_service, test_session_service, file_servlet = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]

    puzzle_data = await manager.import_("literary-alfabet-soupe")

    assert puzzle_service.generate_calls == [{"puzzle_pretty_id": "literary-alfabet-soupe", "codingamer_id": None}]
    assert test_session_service.start_calls == ["session-handle-1"]

    assert (tmp_path / "data" / "solution.src").read_text() == "print('existing answer')\n"
    assert (tmp_path / ".meta" / "statement.html").read_text() == "<p>statement</p>"
    assert (tmp_path / ".meta" / "stub_generator.cgstub").read_text() == "read a:int\n"
    assert (tmp_path / ".gitignore").read_text() == ".meta/\n"

    identity = manager.load_identity()
    assert identity is not None
    assert identity.puzzle_id == 10075
    assert identity.puzzle_handle == "puzzle-handle-1"

    server_data = manager.load_server_data()
    assert server_data is not None
    assert server_data.puzzle_pretty_id == "literary-alfabet-soupe"
    assert server_data.test_session_handle == "session-handle-1"
    assert server_data.title == "Literary Alfabet Soupe"
    assert server_data.puzzle_type == "PUZZLE_INOUT"
    assert server_data.difficulty == "medium"

    assert puzzle_data.solution_language == "Java"  # from the existing answer, not the --language default
    assert manager.load_puzzle_data() == puzzle_data

    # test_cases=[index=1, input=1, output=2, label="Test 1"], [index=2, input=3, output=4, label="Test 2"]
    assert sorted(file_servlet.download_calls) == [1, 2, 3, 4]
    test1_dir = tmp_path / ".meta" / "tests" / "01" / "Test-1"
    assert (test1_dir / "input.txt").read_bytes() == b"content-for-binary-1\n"
    assert (test1_dir / "output.txt").read_bytes() == b"content-for-binary-2\n"
    assert (test1_dir / "test.json").read_text()
    test2_dir = tmp_path / ".meta" / "tests" / "02" / "Test-2"
    assert (test2_dir / "input.txt").read_bytes() == b"content-for-binary-3\n"
    assert (test2_dir / "output.txt").read_bytes() == b"content-for-binary-4\n"


async def test_import_without_existing_answer_uses_placeholder_and_language_flag(tmp_path: Path) -> None:
    session = _make_test_session(answer=None)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]

    puzzle_data = await manager.import_("literary-alfabet-soupe", language="Rust")

    assert puzzle_data.solution_language == "Rust"
    content = (tmp_path / "data" / "solution.src").read_text()
    assert "TODO" in content
    assert "Literary Alfabet Soupe" in content


async def test_import_refuses_unsupported_contribution_type(tmp_path: Path) -> None:
    session = _make_test_session(contribution_type="PUZZLE_OPTI")
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]

    with pytest.raises(CgPuzzleManagerError):
        await manager.import_("literary-alfabet-soupe")

    assert manager.load_identity() is None
    assert not (tmp_path / "data" / "solution.src").exists()


async def test_import_refuses_if_already_imported(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    with pytest.raises(CgPuzzleManagerError):
        await manager.import_("literary-alfabet-soupe")


# --- repair ----------------------------------------------------------------------------------


async def test_repair_requires_prior_import(tmp_path: Path) -> None:
    manager = CgPuzzleManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        await manager.repair()


async def test_repair_refuses_if_meta_already_present(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    with pytest.raises(CgPuzzleManagerError):
        await manager.repair()


async def test_repair_reconstructs_meta_reusing_cached_test_session_handle(tmp_path: Path) -> None:
    session = _make_test_session()
    client, puzzle_service, test_session_service, file_servlet = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    # Simulate a fresh clone: .meta/ (gitignored) is gone, data/ survives.
    shutil.rmtree(tmp_path / ".meta")
    (tmp_path / ".gitignore").unlink()
    file_servlet.download_calls.clear()

    puzzle_service.progress_results = [_make_progress(test_session_handle="session-handle-1")]
    puzzle_service.generate_calls.clear()

    server_data = await manager.repair()

    assert puzzle_service.find_progress_calls == [[10075]]
    assert puzzle_service.generate_calls == []  # reused the cached-affinity handle, no re-generation
    assert server_data.test_session_handle == "session-handle-1"
    assert server_data.puzzle_type == "PUZZLE_INOUT"
    assert server_data.difficulty == "medium"
    assert (tmp_path / ".meta" / "statement.html").is_file()
    assert (tmp_path / ".gitignore").read_text() == ".meta/\n"
    assert manager.load_server_data() == server_data
    assert sorted(file_servlet.download_calls) == [1, 2, 3, 4]  # tests/ re-downloaded too
    assert (tmp_path / ".meta" / "tests" / "01" / "Test-1" / "input.txt").read_bytes() == b"content-for-binary-1\n"


async def test_repair_falls_back_to_generate_when_no_cached_test_session_handle(tmp_path: Path) -> None:
    session = _make_test_session()
    client, puzzle_service, test_session_service, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    shutil.rmtree(tmp_path / ".meta")

    puzzle_service.progress_results = [_make_progress(test_session_handle=None)]
    puzzle_service.generate_calls.clear()

    server_data = await manager.repair()

    assert len(puzzle_service.generate_calls) == 1
    assert server_data.test_session_handle == "session-handle-1"


async def test_repair_refuses_on_puzzle_id_mismatch(tmp_path: Path) -> None:
    session = _make_test_session()
    client, puzzle_service, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    shutil.rmtree(tmp_path / ".meta")

    puzzle_service.progress_results = [_make_progress(puzzle_id=99999)]

    with pytest.raises(CgPuzzleManagerError):
        await manager.repair()

    assert manager.load_server_data() is None


async def test_repair_refuses_if_no_local_solution(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    shutil.rmtree(tmp_path / ".meta")
    (tmp_path / "data" / "solution.src").unlink()

    with pytest.raises(FileNotFoundError):
        await manager.repair()


# --- push ----------------------------------------------------------------------------------


async def test_push_submits_current_local_content(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('old')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, _, test_session_service, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    (tmp_path / "data" / "solution.src").write_text("print('new solution')\n")

    submission_id = await manager.push()

    assert submission_id == 424242
    assert len(test_session_service.submit_calls) == 1
    call = test_session_service.submit_calls[0]
    assert call["test_session_handle"] == "session-handle-1"
    assert call["request"].code == "print('new solution')\n"
    assert call["request"].programming_language_id == "Python3"


async def test_push_requires_prior_import(tmp_path: Path) -> None:
    manager = CgPuzzleManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        await manager.push()


async def test_push_requires_meta_present(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    shutil.rmtree(tmp_path / ".meta")

    with pytest.raises(CgPuzzleManagerError):
        await manager.push()


# --- play ------------------------------------------------------------------------------------


async def test_play_defaults_to_test_index_1(tmp_path: Path) -> None:
    session = _make_test_session()
    play_result = CgPlayResult(output="1\n", comparison=CgPlayComparison(success=True))
    client, _, test_session_service, _ = _make_fake_client(session, play_result=play_result)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    result = await manager.play()

    assert result.comparison.success is True
    assert len(test_session_service.play_calls) == 1
    request = test_session_service.play_calls[0]["request"]
    assert request.multiple_languages is not None
    assert request.multiple_languages.test_index == 1


async def test_play_with_explicit_index(tmp_path: Path) -> None:
    session = _make_test_session()
    play_result = CgPlayResult(output="", comparison=CgPlayComparison(success=False, expected="x", found="y"))
    client, _, test_session_service, _ = _make_fake_client(session, play_result=play_result)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    await manager.play(3)

    request = test_session_service.play_calls[0]["request"]
    assert request.multiple_languages is not None
    assert request.multiple_languages.test_index == 3


# --- diff ------------------------------------------------------------------------------------


async def test_diff_empty_when_matching(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('same')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    assert await manager.diff() == ""


async def test_diff_shows_local_vs_server_differences(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('server version')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    (tmp_path / "data" / "solution.src").write_text("print('local version')\n")

    diff_text = await manager.diff()

    assert "server version" in diff_text
    assert "local version" in diff_text


# --- discard_local ---------------------------------------------------------------------------


async def test_discard_local_overwrites_with_server_answer(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('server version')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    (tmp_path / "data" / "solution.src").write_text("print('local edit')\n")

    result = await manager.discard_local()

    assert result.code == "print('server version')\n"
    assert (tmp_path / "data" / "solution.src").read_text() == "print('server version')\n"


async def test_discard_local_updates_recorded_language_if_it_changed(tmp_path: Path) -> None:
    original_answer = CgTestSessionAnswer(code="print('py')\n", programming_language_id="Python3")
    session = _make_test_session(answer=original_answer)
    client, _, test_session_service, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    puzzle_data = manager.load_puzzle_data()
    assert puzzle_data is not None
    assert puzzle_data.solution_language == "Python3"

    new_answer = CgTestSessionAnswer(code="System.out.println(1);\n", programming_language_id="Java")
    test_session_service.session = _make_test_session(answer=new_answer)

    result = await manager.discard_local()

    assert result.solution_language == "Java"
    puzzle_data = manager.load_puzzle_data()
    assert puzzle_data is not None
    assert puzzle_data.solution_language == "Java"


async def test_discard_local_refuses_without_server_answer(tmp_path: Path) -> None:
    session = _make_test_session(answer=None)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    with pytest.raises(CgPuzzleManagerError):
        await manager.discard_local()


# --- load_solution -----------------------------------------------------------------------------


async def test_load_solution_requires_prior_import(tmp_path: Path) -> None:
    manager = CgPuzzleManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        manager.load_solution()


async def test_load_solution_returns_current_content(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    (tmp_path / "data" / "solution.src").write_text("print('hi')\n")

    assert manager.load_solution() == "print('hi')\n"


# --- play_local ------------------------------------------------------------------------------


def _write_downloaded_test_case(tests_dir: Path, index: int, label: str, input_text: str, output_text: str) -> None:
    named_dir = tests_dir / str(index).zfill(2) / normalize_test_label(label)
    named_dir.mkdir(parents=True, exist_ok=True)
    CgPuzzleTestCaseMeta(label=label).save(named_dir / TEST_META_FILE_NAME)
    (named_dir / "input.txt").write_text(input_text)
    (named_dir / "output.txt").write_text(output_text)


async def _import_with_doubling_solution(tmp_path: Path) -> CgPuzzleManager:
    """A manager whose `data/solution.src` doubles an integer read from stdin, with a fresh
       `.meta/tests/` (real files, not the fake client's placeholder content--`play_local` never
       touches the network, so there's no need to route this through the fake client)."""
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    (tmp_path / "data" / "solution.src").write_text("n = int(input())\nprint(n * 2)\n")
    shutil.rmtree(manager.tests_dir)
    _write_downloaded_test_case(manager.tests_dir, 1, "Doubles", "21\n", "42\n")
    _write_downloaded_test_case(manager.tests_dir, 2, "Doubles Again", "10\n", "20\n")
    return manager


async def test_play_local_all_pass(tmp_path: Path) -> None:
    manager = await _import_with_doubling_solution(tmp_path)

    results = manager.play_local()

    assert [r.index for r in results] == [1, 2]
    assert all(r.passed for r in results)
    assert results[0].actual_output == "42\n"


async def test_play_local_with_explicit_test_index_runs_only_that_one(tmp_path: Path) -> None:
    manager = await _import_with_doubling_solution(tmp_path)

    results = manager.play_local(2)

    assert [r.index for r in results] == [2]
    assert results[0].passed


async def test_play_local_unknown_test_index_raises(tmp_path: Path) -> None:
    manager = await _import_with_doubling_solution(tmp_path)

    with pytest.raises(CgPuzzleManagerError):
        manager.play_local(99)


async def test_play_local_raises_and_reports_mismatch(tmp_path: Path) -> None:
    manager = await _import_with_doubling_solution(tmp_path)
    (tmp_path / "data" / "solution.src").write_text("n = int(input())\nprint(n * 3)\n")  # wrong

    with pytest.raises(CgPuzzleLocalTestFailedError) as exc_info:
        manager.play_local()

    results = exc_info.value.results
    assert [r.index for r in results] == [1, 2]
    assert all(not r.passed for r in results)
    assert results[0].actual_output == "63\n"
    assert results[0].expected_output == "42\n"


async def test_play_local_requires_prior_import(tmp_path: Path) -> None:
    manager = CgPuzzleManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        manager.play_local()


async def test_play_local_requires_downloaded_tests(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    shutil.rmtree(manager.tests_dir)

    with pytest.raises(FileNotFoundError):
        manager.play_local()


# --- status ------------------------------------------------------------------------------------


async def test_status_default_is_local_only(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('same')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, puzzle_service, test_session_service, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    start_calls_after_import = len(test_session_service.start_calls)
    find_progress_calls_after_import = len(puzzle_service.find_progress_calls)

    status = await manager.status()

    assert status.puzzle_id == 10075
    assert status.puzzle_handle == "puzzle-handle-1"
    assert status.title == "Literary Alfabet Soupe"
    assert status.puzzle_pretty_id == "literary-alfabet-soupe"
    assert status.puzzle_type == "PUZZLE_INOUT"
    assert status.difficulty == "medium"
    assert status.solution_language == "Python3"
    assert status.local_dirty is None
    assert status.progress is None
    # no network calls beyond whatever import_() itself already made
    assert len(test_session_service.start_calls) == start_calls_after_import
    assert len(puzzle_service.find_progress_calls) == find_progress_calls_after_import


async def test_status_puzzle_type_and_difficulty_none_for_pre_existing_cache(tmp_path: Path) -> None:
    """A `.meta/puzzle-server-data.json` written before `puzzle_type`/`difficulty` existed should
       still load fine, with those two fields simply absent (None), not raise/crash."""
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    server_data = manager.load_server_data()
    assert server_data is not None
    CgPuzzleServerData(
            test_session_handle=server_data.test_session_handle, title=server_data.title,
            puzzle_pretty_id=server_data.puzzle_pretty_id,
        ).save(manager.server_data_file)

    status = await manager.status()

    assert status.puzzle_type is None
    assert status.difficulty is None


async def test_status_refresh_detects_matching_and_diverging_local_edits(tmp_path: Path) -> None:
    answer = CgTestSessionAnswer(code="print('same')\n", programming_language_id="Python3")
    session = _make_test_session(answer=answer)
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    status = await manager.status(refresh=True)
    assert status.local_dirty is False

    (tmp_path / "data" / "solution.src").write_text("print('local edit')\n")
    status2 = await manager.status(refresh=True)
    assert status2.local_dirty is True


async def test_status_refresh_fetches_progress(tmp_path: Path) -> None:
    session = _make_test_session()
    client, puzzle_service, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    progress = _make_progress()
    puzzle_service.progress_results = [progress]

    status = await manager.status(refresh=True)

    assert status.progress == progress
    assert puzzle_service.find_progress_calls[-1] == [10075]


async def test_status_refresh_progress_none_when_no_matching_result(tmp_path: Path) -> None:
    session = _make_test_session()
    client, puzzle_service, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")
    puzzle_service.progress_results = []  # no match at all

    status = await manager.status(refresh=True)

    assert status.progress is None


async def test_status_requires_prior_import(tmp_path: Path) -> None:
    manager = CgPuzzleManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        await manager.status()


async def test_status_requires_meta_present(tmp_path: Path) -> None:
    session = _make_test_session()
    client, _, _, _ = _make_fake_client(session)
    manager = CgPuzzleManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("literary-alfabet-soupe")

    shutil.rmtree(tmp_path / ".meta")

    with pytest.raises(CgPuzzleManagerError):
        await manager.status()
