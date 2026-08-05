"""Unit tests for codingame_tools.workdir: resolving a working directory from any file inside it.

This is what lets one VS Code task and one debug configuration per language serve every working
directory in a workspace: the editor hands over `${file}` and nothing else, so the kind has to be
discovered rather than assumed.

Pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_tools.workdir import (
    CgWorkingDirError,
    find_working_dir,
    resolve_working_dir,
    working_dir_kind,
)


def _make(root: Path, kind: str) -> Path:
    """A minimal working directory of the given kind."""
    (root / "data").mkdir(parents=True)
    (root / ("puzzle.json" if kind == "puzzle" else "contribution.json")).write_text("{}")
    (root / "data" / "solution.src").write_text("print(1)\n")
    return root


@pytest.mark.parametrize("kind", ["puzzle", "contribution"])
def test_kind_is_discovered_from_the_identity_file(tmp_path: Path, kind: str) -> None:
    root = _make(tmp_path / "wd", kind)

    assert working_dir_kind(root) == kind

    found = resolve_working_dir(root / "data" / "solution.src")
    assert found.root == root.resolve()
    assert found.kind == kind


def test_any_file_inside_resolves_not_just_the_solution(tmp_path: Path) -> None:
    """Deliberately looser than `infer_puzzle_dir`, which demands `data/solution.src` exactly.

       "Run the tests for whatever I'm looking at" is reasonable with a test input or the statement
       open, and the editor hands over whichever tab was focused."""
    root = _make(tmp_path / "wd", "puzzle")
    (root / "data" / "tests" / "01" / "T").mkdir(parents=True)
    (root / "data" / "tests" / "01" / "T" / "input.txt").write_text("1\n")

    for candidate in (root, root / "data", root / "data" / "tests" / "01" / "T" / "input.txt"):
        assert resolve_working_dir(candidate).root == root.resolve(), candidate


def test_a_symlink_outside_the_working_directory_resolves(tmp_path: Path) -> None:
    """The case the debugger actually hits: VS Code passes the path of the tab you had open, which
       may be a `solution.<ext>` symlink living elsewhere in the workspace. Walking up from the
       symlink's own location finds nothing, so the resolved target has to be tried first."""
    root = _make(tmp_path / "wd", "contribution")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = elsewhere / "solution.py"
    link.symlink_to(root / "data" / "solution.src")

    found = resolve_working_dir(link)

    assert found.root == root.resolve()
    assert found.kind == "contribution"


def test_the_nearest_working_directory_wins(tmp_path: Path) -> None:
    outer = _make(tmp_path / "outer", "contribution")
    inner = _make(outer / "nested" / "inner", "puzzle")

    assert resolve_working_dir(inner / "data" / "solution.src").kind == "puzzle"
    assert resolve_working_dir(outer / "data" / "solution.src").kind == "contribution"


def test_a_directory_with_data_but_no_identity_file_is_not_a_working_directory(tmp_path: Path) -> None:
    """Checking for the identity file rather than `data/` keeps an ordinary project that happens to
       have a `data/` directory from being mistaken for one."""
    decoy = tmp_path / "decoy"
    (decoy / "data").mkdir(parents=True)

    assert working_dir_kind(decoy) is None
    assert find_working_dir(decoy / "data") is None


def test_resolve_raises_with_an_actionable_message(tmp_path: Path) -> None:
    with pytest.raises(CgWorkingDirError, match="not inside a puzzle or contribution"):
        resolve_working_dir(tmp_path / "nowhere.txt")


# --- test selection ------------------------------------------------------------------------------
#
# Debugging gets one stdin, so it needs exactly one test. This used to be a `pickString` baked into
# launch.json, which is what forced launch.json to be regenerated per working directory. Recording
# the choice in `.meta/` is what lets the launch configuration be static.


def test_puzzle_selection_defaults_to_the_first_test(tmp_path: Path) -> None:
    """Defaulting rather than refusing means debugging works straight after an import, with no
       selection step -- the common case."""
    from codingame_tools.puzzle_manager import CgPuzzleManager

    manager = CgPuzzleManager(tmp_path, None)  # type: ignore[arg-type]
    for index in (1, 2):
        case = manager.tests_dir / f"0{index}" / "T"
        case.mkdir(parents=True)
        (case / "input.txt").write_bytes(b"x")
        (case / "output.txt").write_bytes(b"y")

    assert manager.load_selected_test() is None
    assert manager.resolve_debug_test_index() == 1

    manager.select_test(2)
    assert manager.resolve_debug_test_index() == 2

    manager.clear_selected_test()
    assert manager.resolve_debug_test_index() == 1


def test_puzzle_selection_rejects_an_unknown_index(tmp_path: Path) -> None:
    """Caught when selecting, not when a debug session mysteriously fails to start."""
    from codingame_tools.puzzle_manager import CgPuzzleManager, CgPuzzleManagerError

    manager = CgPuzzleManager(tmp_path, None)  # type: ignore[arg-type]
    case = manager.tests_dir / "01" / "T"
    case.mkdir(parents=True)
    (case / "input.txt").write_bytes(b"x")
    (case / "output.txt").write_bytes(b"y")

    with pytest.raises(CgPuzzleManagerError, match="No downloaded test case with index 7"):
        manager.select_test(7)


def test_a_stale_selection_falls_back_rather_than_failing(tmp_path: Path) -> None:
    """`.meta/` is disposable and test cases are re-downloaded by `repair()`, so a selection can
       outlive the test it names. Falling back beats refusing to debug."""
    from codingame_tools.puzzle_manager import CgPuzzleManager
    from codingame_tools.puzzle_manager.schema import CgPuzzleSelectedTest

    manager = CgPuzzleManager(tmp_path, None)  # type: ignore[arg-type]
    case = manager.tests_dir / "01" / "T"
    case.mkdir(parents=True)
    (case / "input.txt").write_bytes(b"x")
    (case / "output.txt").write_bytes(b"y")
    manager.meta_dir.mkdir(parents=True, exist_ok=True)
    CgPuzzleSelectedTest(test_index=99).save(manager.selected_test_file)

    assert manager.resolve_debug_test_index() == 1
