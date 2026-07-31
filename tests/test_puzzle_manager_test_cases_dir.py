"""Unit tests for codingame_client.puzzle_manager.test_cases_dir: the `.meta/tests/` download/
   layout algorithm (slug normalization, per-index directories, duplicate-index detection).

These are pure/local tests--no real network--so they run under the default `pdm run test`
invocation; the "download" is a fake, duck-typed client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codingame_client.client.common.protocol.test_session import CgTestSessionTestCase
from codingame_client.client.common.raw_client import CgDownloadFileResult
from codingame_client.puzzle_manager.test_cases_dir import (
    TEST_META_FILE_NAME,
    CgPuzzleTestCaseMeta,
    CgPuzzleTestCasesDownloadError,
    download_test_cases,
    normalize_test_label,
)


class _FakeFileServletServlet:
    def __init__(self) -> None:
        self.download_calls: list[int] = []

    async def __call__(self, id: int) -> CgDownloadFileResult:  # noqa: A002
        self.download_calls.append(id)
        return CgDownloadFileResult.create(
                id=id, content=f"binary-{id}".encode(), content_type="text/plain")


class _FakeServlets:
    def __init__(self, file_servlet: _FakeFileServletServlet) -> None:
        self.file_servlet = file_servlet


class _FakeClient:
    def __init__(self, file_servlet: _FakeFileServletServlet) -> None:
        self.servlets = _FakeServlets(file_servlet)


def _tc(index: int, input_binary_id: int, output_binary_id: int, label: str) -> CgTestSessionTestCase:
    return CgTestSessionTestCase(
            index=index, input_binary_id=input_binary_id, output_binary_id=output_binary_id, label=label)


# --- normalize_test_label -----------------------------------------------------------------


def test_normalize_test_label_replaces_punctuation_and_spaces() -> None:
    assert normalize_test_label("Large grid test case!") == "Large-grid-test-case"


def test_normalize_test_label_collapses_runs_and_strips_edges() -> None:
    assert normalize_test_label("  Foo   Bar--Baz!! ") == "Foo-Bar-Baz"


def test_normalize_test_label_falls_back_when_nothing_alphanumeric_remains() -> None:
    assert normalize_test_label("!!!") == "test"


# --- download_test_cases --------------------------------------------------------------------


async def test_download_writes_one_dir_per_index(tmp_path: Path) -> None:
    file_servlet = _FakeFileServletServlet()
    client: Any = _FakeClient(file_servlet)
    tests_dir = tmp_path / "tests"
    test_cases = [_tc(1, 10, 20, "Test 1"), _tc(2, 30, 40, "Test 2")]

    await download_test_cases(client, test_cases, tests_dir)

    assert sorted(file_servlet.download_calls) == [10, 20, 30, 40]
    d1 = tests_dir / "01" / "Test-1"
    assert (d1 / "input.txt").read_bytes() == b"binary-10"
    assert (d1 / "output.txt").read_bytes() == b"binary-20"
    assert CgPuzzleTestCaseMeta.load(d1 / TEST_META_FILE_NAME).label == "Test 1"
    d2 = tests_dir / "02" / "Test-2"
    assert (d2 / "input.txt").read_bytes() == b"binary-30"
    assert (d2 / "output.txt").read_bytes() == b"binary-40"


async def test_download_zero_pads_ordinal_width_to_max_index(tmp_path: Path) -> None:
    file_servlet = _FakeFileServletServlet()
    client: Any = _FakeClient(file_servlet)
    tests_dir = tmp_path / "tests"
    test_cases = [_tc(i, i * 10, i * 10 + 1, f"Test {i}") for i in range(1, 11)]

    await download_test_cases(client, test_cases, tests_dir)

    assert (tests_dir / "01" / "Test-1").is_dir()
    assert (tests_dir / "10" / "Test-10").is_dir()


async def test_download_empty_list_is_noop_but_clears_existing_dir(tmp_path: Path) -> None:
    file_servlet = _FakeFileServletServlet()
    client: Any = _FakeClient(file_servlet)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "stale.txt").write_text("stale")

    await download_test_cases(client, [], tests_dir)

    assert not tests_dir.exists()
    assert file_servlet.download_calls == []


async def test_download_replaces_existing_dir_entirely(tmp_path: Path) -> None:
    file_servlet = _FakeFileServletServlet()
    client: Any = _FakeClient(file_servlet)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    stale_dir = tests_dir / "01" / "Old-Test"
    stale_dir.mkdir(parents=True)
    (stale_dir / "input.txt").write_text("stale")

    await download_test_cases(client, [_tc(1, 10, 20, "New Test")], tests_dir)

    assert not (tests_dir / "01" / "Old-Test").exists()
    assert (tests_dir / "01" / "New-Test" / "input.txt").read_bytes() == b"binary-10"


async def test_download_refuses_duplicate_indices(tmp_path: Path) -> None:
    file_servlet = _FakeFileServletServlet()
    client: Any = _FakeClient(file_servlet)
    tests_dir = tmp_path / "tests"

    with pytest.raises(CgPuzzleTestCasesDownloadError):
        await download_test_cases(client, [_tc(1, 10, 20, "A"), _tc(1, 30, 40, "B")], tests_dir)
