"""Unit tests for CgContributionManager's local test-running additions: `list_local_tests`,
   `run_local_test`, `run_local_tests`--entirely local (no network, no git), so these construct a
   manager directly against a plain `data/` directory rather than going through `import_()`.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
They spawn real `sys.executable` subprocesses (via `run_solution_locally`), same as `test_test_
runner_runner.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_tools.client.common.protocol.contribution import CgContributionData, CgTestCase
from codingame_tools.contribution_manager.manager import (
    CgContributionLocalTestFailedError,
    CgContributionManager,
)
from codingame_tools.contribution_manager.schema import CgContributionView
from codingame_tools.contribution_manager.test_cases_dir import import_test_cases
from codingame_tools.test_runner import CgLocalRunUnsupportedLanguageError


def _tc(title: str, test_in: str, test_out: str, *, is_test: bool, is_validator: bool) -> CgTestCase:
    return CgTestCase(
            title=title, test_in=test_in, test_out=test_out,
            is_test=is_test, is_validator=is_validator, need_validation=True,
        )


def _setup(
            tmp_path: Path, test_cases: list[CgTestCase], *,
            solution_code: str = "n = int(input())\nprint(n * 2)\n",
            solution_language: str | None = "Python3",
        ) -> CgContributionManager:
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(CgContributionView(data=CgContributionData(title="T", solution_language=solution_language)))
    manager.solution_file.parent.mkdir(parents=True, exist_ok=True)
    manager.solution_file.write_text(solution_code)
    import_test_cases(test_cases, manager.tests_dir)
    return manager


# --- list_local_tests --------------------------------------------------------------------------


def test_list_local_tests_no_filter_returns_both_sides_both_ordinals(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [
            _tc("A", "1\n", "2\n", is_test=True, is_validator=False),
            _tc("A", "3\n", "4\n", is_test=False, is_validator=True),
            _tc("B", "5\n", "6\n", is_test=True, is_validator=False),
            _tc("B", "7\n", "8\n", is_test=False, is_validator=True),
        ])

    tests = manager.list_local_tests()

    assert [(t.ordinal, t.side) for t in tests] == [
            ("01", "local"), ("01", "validator"), ("02", "local"), ("02", "validator"),
        ]


def test_list_local_tests_filters_by_ordinal_numeric_equivalence(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [
            _tc("A", "1\n", "2\n", is_test=True, is_validator=False),
            _tc("B", "3\n", "4\n", is_test=True, is_validator=False),
        ])

    tests = manager.list_local_tests(["2"])

    assert [t.ordinal for t in tests] == ["02"]


def test_list_local_tests_filters_by_side(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [
            _tc("A", "1\n", "2\n", is_test=True, is_validator=False),
            _tc("A", "3\n", "4\n", is_test=False, is_validator=True),
        ])

    local_only = manager.list_local_tests(local=True, validator=False)
    validator_only = manager.list_local_tests(local=False, validator=True)

    assert [t.side for t in local_only] == ["local"]
    assert [t.side for t in validator_only] == ["validator"]


# --- run_local_test: compare mode ---------------------------------------------------------------


def test_run_local_test_compare_mode_pass(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [_tc("A", "21\n", "42\n", is_test=True, is_validator=False)])
    test_case = manager.list_local_tests()[0]

    result = manager.run_local_test(test_case, "Python3")

    assert result.passed
    assert not result.updated
    assert result.actual_output == "42\n"
    assert test_case.output_file.read_text() == "42\n"  # untouched


def test_run_local_test_compare_mode_mismatch(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [_tc("A", "21\n", "999\n", is_test=True, is_validator=False)])
    test_case = manager.list_local_tests()[0]

    result = manager.run_local_test(test_case, "Python3")

    assert not result.passed
    assert result.returncode == 0
    assert result.actual_output == "42\n"
    assert result.expected_output == "999\n"


def test_run_local_test_compare_mode_crash_fails(tmp_path: Path) -> None:
    manager = _setup(
            tmp_path, [_tc("A", "", "anything\n", is_test=True, is_validator=False)],
            solution_code="raise ValueError('boom')\n",
        )
    test_case = manager.list_local_tests()[0]

    result = manager.run_local_test(test_case, "Python3")

    assert not result.passed
    assert result.returncode != 0
    assert "ValueError" in result.stderr


# --- run_local_test: update mode -----------------------------------------------------------------


def test_run_local_test_update_mode_overwrites_output_file(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [_tc("A", "21\n", "stale\n", is_test=True, is_validator=False)])
    test_case = manager.list_local_tests()[0]

    result = manager.run_local_test(test_case, "Python3", update_expected=True)

    assert result.passed
    assert result.updated
    assert test_case.output_file.read_text() == "42\n"


def test_run_local_test_update_mode_does_not_overwrite_on_crash(tmp_path: Path) -> None:
    manager = _setup(
            tmp_path, [_tc("A", "", "stale\n", is_test=True, is_validator=False)],
            solution_code="raise ValueError('boom')\n",
        )
    test_case = manager.list_local_tests()[0]

    result = manager.run_local_test(test_case, "Python3", update_expected=True)

    assert not result.passed
    assert not result.updated
    assert test_case.output_file.read_text() == "stale\n"


def test_run_local_test_unsupported_language_raises(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [_tc("A", "1\n", "2\n", is_test=True, is_validator=False)])
    test_case = manager.list_local_tests()[0]

    with pytest.raises(CgLocalRunUnsupportedLanguageError):
        manager.run_local_test(test_case, "Java")


# --- run_local_tests (batch) ---------------------------------------------------------------------


def test_run_local_tests_raises_with_all_results_if_any_failed(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [
            _tc("A", "21\n", "42\n", is_test=True, is_validator=False),
            _tc("B", "10\n", "wrong\n", is_test=True, is_validator=False),
        ])
    test_cases = manager.list_local_tests()

    with pytest.raises(CgContributionLocalTestFailedError) as exc_info:
        manager.run_local_tests(test_cases, "Python3")

    results = exc_info.value.results
    assert len(results) == 2
    assert results[0].passed
    assert not results[1].passed


def test_run_local_tests_returns_results_when_all_pass(tmp_path: Path) -> None:
    manager = _setup(tmp_path, [_tc("A", "21\n", "42\n", is_test=True, is_validator=False)])
    test_cases = manager.list_local_tests()

    results = manager.run_local_tests(test_cases, "Python3")

    assert len(results) == 1
    assert results[0].passed
