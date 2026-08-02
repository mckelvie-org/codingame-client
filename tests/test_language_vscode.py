"""Tests for `codingame_tools.language.vscode`: workspace-root resolution, ownership scoping, and
   the merge rules that keep a user's hand-edited VS Code config safe.

Pure/local--no network, no subprocesses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codingame_tools.language.vscode import (
    CgVsCodeMergeError,
    CgVsCodeProvisioning,
    find_workspace_root,
    owner_name,
    owner_slug,
    write_provisioning,
)


def _config(name: str) -> dict[str, Any]:
    return {"name": name, "type": "debugpy", "request": "launch"}


def _launch(workspace_root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((workspace_root / ".vscode" / "launch.json").read_text())
    return data


# --- workspace root resolution ------------------------------------------------------------------


def test_find_workspace_root_prefers_an_existing_vscode_dir(tmp_path: Path) -> None:
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".git").mkdir()
    root = tmp_path / "puzzle"
    root.mkdir()

    assert find_workspace_root(root) == tmp_path.resolve()


def test_find_workspace_root_falls_back_to_a_vcs_marker(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    root = tmp_path / "nested" / "puzzle"
    root.mkdir(parents=True)

    assert find_workspace_root(root) == tmp_path.resolve()


def test_find_workspace_root_falls_back_to_the_working_dir_itself(tmp_path: Path) -> None:
    """The case where the user opens the puzzle directory directly as their folder--no marker
       anywhere above it."""
    root = tmp_path / "puzzle"
    root.mkdir()

    assert find_workspace_root(root) == root.resolve()


def test_find_workspace_root_prefers_a_nearer_vscode_dir_over_a_farther_one(tmp_path: Path) -> None:
    (tmp_path / ".vscode").mkdir()
    nearer = tmp_path / "sub"
    (nearer / ".vscode").mkdir(parents=True)
    root = nearer / "puzzle"
    root.mkdir()

    assert find_workspace_root(root) == nearer.resolve()


# --- ownership naming ---------------------------------------------------------------------------


def test_owner_names_derive_from_the_working_directory_name(tmp_path: Path) -> None:
    assert owner_name(tmp_path / "puzzle") == "CG puzzle: "
    assert owner_slug(tmp_path / "puzzle") == "puzzle"


def test_owner_slug_sanitizes_punctuation(tmp_path: Path) -> None:
    assert owner_slug(tmp_path / "my-cool.puzzle") == "my_cool_puzzle"


# --- merge behavior -----------------------------------------------------------------------------


def test_write_creates_launch_json_from_nothing(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    provisioning = CgVsCodeProvisioning(configurations=[_config("CG puzzle: Debug")])

    written = write_provisioning(provisioning, root=root, workspace_root=tmp_path)

    assert written == [tmp_path / ".vscode" / "launch.json"]
    data = _launch(tmp_path)
    assert data["version"] == "0.2.0"
    assert [c["name"] for c in data["configurations"]] == ["CG puzzle: Debug"]


def test_rewriting_replaces_only_this_working_directorys_entries(tmp_path: Path) -> None:
    """The core safety property: a user's own configurations, and other working directories'
       configurations, must survive re-provisioning."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "version": "0.2.0",
            "configurations": [
                    _config("My Own Thing"),
                    _config("CG contribution: Debug"),
                    _config("CG puzzle: Stale Entry"),
                ],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG puzzle: Debug")]),
            root=root, workspace_root=tmp_path)

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "My Own Thing", "CG contribution: Debug", "CG puzzle: Debug",
        ]


def test_rewriting_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    provisioning = CgVsCodeProvisioning(configurations=[_config("CG puzzle: Debug")])

    write_provisioning(provisioning, root=root, workspace_root=tmp_path)
    write_provisioning(provisioning, root=root, workspace_root=tmp_path)

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == ["CG puzzle: Debug"]


def test_inputs_are_scoped_by_owner_slug(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "inputs": [{"id": "cg_contribution_testCase"}, {"id": "myOwnInput"}],
            "configurations": [],
        }))

    write_provisioning(
            CgVsCodeProvisioning(
                    configurations=[_config("CG puzzle: Debug")],
                    inputs=[{"id": "cg_puzzle_testCase", "type": "pickString", "options": []}]),
            root=root, workspace_root=tmp_path)

    assert [i["id"] for i in _launch(tmp_path)["inputs"]] == [
            "cg_contribution_testCase", "myOwnInput", "cg_puzzle_testCase",
        ]


def test_refuses_to_merge_into_a_jsonc_file(tmp_path: Path) -> None:
    """launch.json is JSONC in practice--VS Code allows comments. Rewriting such a file would
       silently drop them, so this refuses rather than corrupting it."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    original = '{\n  // keep me\n  "configurations": []\n}\n'
    (vscode / "launch.json").write_text(original)

    with pytest.raises(CgVsCodeMergeError):
        write_provisioning(
                CgVsCodeProvisioning(configurations=[_config("CG puzzle: Debug")]),
                root=root, workspace_root=tmp_path)

    assert (vscode / "launch.json").read_text() == original  # untouched


def test_force_overwrites_a_jsonc_file(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text('{\n  // drop me\n  "configurations": []\n}\n')

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG puzzle: Debug")]),
            root=root, workspace_root=tmp_path, force=True)

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == ["CG puzzle: Debug"]


def test_recommended_extensions_are_unioned_never_removed(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "extensions.json").write_text(json.dumps({"recommendations": ["some.user-extension"]}))

    write_provisioning(
            CgVsCodeProvisioning(recommended_extensions=["ms-python.python", "some.user-extension"]),
            root=root, workspace_root=tmp_path)

    data = json.loads((vscode / "extensions.json").read_text())
    assert data["recommendations"] == ["some.user-extension", "ms-python.python"]


def test_files_are_written_relative_to_the_working_dir_not_the_workspace(tmp_path: Path) -> None:
    """`.devcontainer/` describes *this puzzle's* toolchain, so it belongs next to the solution--
       not at the workspace root where .vscode/ goes."""
    root = tmp_path / "puzzle"
    root.mkdir()

    written = write_provisioning(
            CgVsCodeProvisioning(files={".devcontainer/devcontainer.json": '{"image": "x"}\n'}),
            root=root, workspace_root=tmp_path)

    assert written == [root / ".devcontainer" / "devcontainer.json"]
    assert (root / ".devcontainer" / "devcontainer.json").read_text() == '{"image": "x"}\n'
    assert not (tmp_path / ".devcontainer").exists()
