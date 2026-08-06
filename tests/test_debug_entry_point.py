"""Unit tests for codingame_tools.debug: the kind-agnostic debug entry point.

This is the piece that makes a VS Code launch configuration static. The per-kind entry points it
wraps must be told which kind they are and which test to run, so a configuration using them had to
carry a `pickString` list of that directory's test cases -- which is what forced `launch.json` to be
regenerated for every working directory, import, and language change. Here both are discovered at
launch time from `${file}` alone.

Pure/local tests -- no network -- so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_tools.client.common.protocol.contribution import CgContributionData, CgTestCase
from codingame_tools.contribution_manager import CgContributionManager
from codingame_tools.contribution_manager.schema import (
    CONTRIBUTION_SCHEMA_VERSION,
    CgContributionIdentity,
    CgContributionView,
)
from codingame_tools.contribution_manager.test_cases_dir import import_test_cases
from codingame_tools.debug import main as debug_main
from codingame_tools.workdir import CgWorkingDirError


def _contribution(root: Path) -> CgContributionManager:
    root.mkdir(parents=True, exist_ok=True)
    CgContributionIdentity(schema_version=CONTRIBUTION_SCHEMA_VERSION).save(root / "contribution.json")
    manager = CgContributionManager(root, None)  # type: ignore[arg-type]
    manager.save(CgContributionView(data=CgContributionData(title="T", solution_language="Python3")))
    manager.solution_file.parent.mkdir(parents=True, exist_ok=True)
    manager.solution_file.write_text("n = int(input())\nprint(n * 2)\n")
    import_test_cases([
            CgTestCase(title="A", test_in="21", test_out="42",
                       is_test=True, is_validator=False, need_validation=True),
            CgTestCase(title="B", test_in="10", test_out="20",
                       is_test=True, is_validator=False, need_validation=True),
        ], manager.tests_dir)
    return manager


def test_kind_and_test_are_discovered_from_the_file_alone(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    """The whole point: `args: ["${file}"]` and nothing else, for every working directory."""
    manager = _contribution(tmp_path / "contribution")

    debug_main([str(manager.solution_file)])

    assert capsys.readouterr().out == "42\n"


def test_it_works_through_a_symlink_outside_the_working_directory(
            tmp_path: Path, capsys: pytest.CaptureFixture[str],
        ) -> None:
    """VS Code passes the path of the focused tab, which is where breakpoints bind -- and that may
       be a `solution.<ext>` symlink living elsewhere in the workspace entirely."""
    manager = _contribution(tmp_path / "contribution")
    link = tmp_path / "open-in-editor.py"
    link.symlink_to(manager.solution_file)

    debug_main([str(link)])

    assert capsys.readouterr().out == "42\n"


def test_the_selected_test_is_honoured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manager = _contribution(tmp_path / "contribution")
    manager.select_test("02", "local")

    debug_main([str(manager.solution_file)])

    assert capsys.readouterr().out == "20\n"


def test_a_file_outside_any_working_directory_is_refused(tmp_path: Path) -> None:
    stray = tmp_path / "stray.py"
    stray.write_text("print(1)\n")

    with pytest.raises(CgWorkingDirError, match="not inside a puzzle or contribution"):
        debug_main([str(stray)])


def test_update_expected_is_refused_for_puzzles(tmp_path: Path) -> None:
    """A puzzle's `.meta/tests/` holds byte-exact downloads of CodinGame's own test data. Letting a
       local run rewrite them would silently destroy the thing local runs are checked against."""
    root = tmp_path / "puzzle"
    (root / "data").mkdir(parents=True)
    (root / "puzzle.json").write_text("{}")
    (root / "data" / "solution.src").write_text("print(1)\n")

    with pytest.raises(SystemExit, match="not supported for puzzles"):
        debug_main([str(root / "data" / "solution.src"), "--update-expected"])
