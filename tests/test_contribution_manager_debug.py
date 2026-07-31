"""Unit tests for codingame_client.contribution_manager.debug: the VS Code debugger launcher CLI
   (`python -m codingame_client.contribution_manager.debug`).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
`main()` runs the "solution" in-process (that's the whole point of the module it wraps), so stdout
is captured via pytest's capsys rather than a subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_client.client.common.protocol.contribution import CgTestCase
from codingame_client.contribution_manager.debug import main
from codingame_client.contribution_manager.layout import DATA_SUBDIR_NAME, SOLUTION_FILE_NAME
from codingame_client.contribution_manager.resolver import CgContributionDirInferenceError
from codingame_client.contribution_manager.schema import CONTRIBUTION_IDENTITY_FILE_NAME
from codingame_client.contribution_manager.test_cases_dir import TESTS_SUBDIR_NAME, import_test_cases
from codingame_client.test_runner.debug_stdin import CgDebugStdinOutputMismatchError


def _tc(title: str, i: str, o: str, *, is_test: bool, is_validator: bool) -> CgTestCase:
    return CgTestCase(
            title=title, test_in=i, test_out=o, is_test=is_test, is_validator=is_validator, need_validation=True)


def _make_contribution_dir(root: Path, test_cases: list[CgTestCase]) -> Path:
    data_dir = root / DATA_SUBDIR_NAME
    data_dir.mkdir(parents=True)
    (root / CONTRIBUTION_IDENTITY_FILE_NAME).write_text("{}")
    (data_dir / SOLUTION_FILE_NAME).write_text("n = int(input())\nprint(n * 2)\n")
    import_test_cases(test_cases, data_dir / TESTS_SUBDIR_NAME)
    return root


def test_main_runs_against_matching_ordinal_and_side(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "42\n", is_test=True, is_validator=False),
        ])
    target_file = contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME

    main([str(target_file), "1", "local"])

    assert capsys.readouterr().out == "42\n"


def test_main_distinguishes_local_and_validator_side(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "42\n", is_test=True, is_validator=False),
            _tc("Case A", "10\n", "20\n", is_test=False, is_validator=True),
        ])
    target_file = contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME

    main([str(target_file), "1", "validator"])

    assert capsys.readouterr().out == "20\n"


def test_main_raises_on_mismatch(tmp_path: Path) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "999\n", is_test=True, is_validator=False),
        ])
    target_file = contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME

    with pytest.raises(CgDebugStdinOutputMismatchError):
        main([str(target_file), "1", "local"])


def test_main_unknown_ordinal_exits(tmp_path: Path) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "42\n", is_test=True, is_validator=False),
        ])
    target_file = contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME

    with pytest.raises(SystemExit):
        main([str(target_file), "99", "local"])


def test_main_update_expected_overwrites_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "stale\n", is_test=True, is_validator=False),
        ])
    target_file = contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME
    output_file = contribution_dir / DATA_SUBDIR_NAME / TESTS_SUBDIR_NAME / "01" / "Case-A" / "local" / "output.txt"

    main([str(target_file), "1", "local", "--update-expected"])

    assert capsys.readouterr().out == "42\n"
    assert output_file.read_text() == "42\n"


def test_main_explicit_contribution_dir_overrides_inference(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "42\n", is_test=True, is_validator=False),
        ])
    elsewhere = tmp_path / "elsewhere.py"
    elsewhere.write_text("n = int(input())\nprint(n * 2)\n")

    main([str(elsewhere), "1", "local", "--contribution-dir", str(contribution_dir)])

    assert capsys.readouterr().out == "42\n"


def test_main_infers_contribution_dir_from_symlink_elsewhere(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    contribution_dir = _make_contribution_dir(tmp_path / "contribution", [
            _tc("Case A", "21\n", "42\n", is_test=True, is_validator=False),
        ])
    elsewhere = tmp_path / "somewhere" / "solution.py"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.symlink_to(contribution_dir / DATA_SUBDIR_NAME / SOLUTION_FILE_NAME)

    main([str(elsewhere), "1", "local"])

    assert capsys.readouterr().out == "42\n"


def test_main_inference_failure_propagates(tmp_path: Path) -> None:
    not_a_contribution = tmp_path / "random.py"
    not_a_contribution.write_text("print('hi')\n")

    with pytest.raises(CgContributionDirInferenceError):
        main([str(not_a_contribution), "1", "local"])
