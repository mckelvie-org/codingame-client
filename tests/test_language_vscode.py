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
    MANAGED_PREFIX,
    CgVsCodeMergeError,
    CgVsCodeProvisioning,
    entry_name,
    find_workspace_root,
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


def test_entry_names_have_three_levels(tmp_path: Path) -> None:
    """Managed prefix, language, action--each doing a distinct job. Not per working directory any
       more: one entry per (language, action) serves the whole workspace."""
    assert entry_name("C++", "Debug solution") == "CG C++: Debug solution"
    assert entry_name("Python3", "Debug solution").startswith(MANAGED_PREFIX)


# --- merge behavior -----------------------------------------------------------------------------


def test_write_creates_launch_json_from_nothing(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    provisioning = CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")])

    written = write_provisioning(provisioning, root=root, workspace_root=tmp_path, language="Python3")

    assert written == [tmp_path / ".vscode" / "launch.json"]
    data = _launch(tmp_path)
    assert data["version"] == "0.2.0"
    assert [c["name"] for c in data["configurations"]] == ["CG Python3: Debug solution"]


def test_rewriting_replaces_its_own_entry_in_place_and_leaves_everything_else(tmp_path: Path) -> None:
    """The core safety property: nothing is touched except the entry being written.

       Note position is preserved rather than the entry being moved to the end. Re-provisioning a
       multi-language workspace would otherwise reshuffle the file on every run, showing up as a
       diff in something the user version-controls for no semantic change."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "version": "0.2.0",
            "configurations": [
                    _config("My Own Thing"),
                    {"name": "CG Python3: Debug solution", "type": "stale", "request": "launch"},
                    _config("Another Of Mine"),
                ],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    configs = _launch(tmp_path)["configurations"]
    assert [c["name"] for c in configs] == ["My Own Thing", "CG Python3: Debug solution", "Another Of Mine"]
    assert configs[1]["type"] == "debugpy"  # replaced, not left stale


def test_provisioning_one_language_does_not_remove_anothers_entry(tmp_path: Path) -> None:
    """A provisioning run only ever generates for one language, so "remove everything named CG:"
       would make whichever language you provisioned last the only one you keep--in a workspace
       with both a C++ puzzle and a Python contribution, that silently breaks one of them."""
    python_dir = tmp_path / "py-puzzle"
    python_dir.mkdir()
    cpp_dir = tmp_path / "cpp-puzzle"
    cpp_dir.mkdir()

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=python_dir, workspace_root=tmp_path, language="Python3")
    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG C++: Debug solution")]),
            root=cpp_dir, workspace_root=tmp_path, language="C++")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "CG Python3: Debug solution", "CG C++: Debug solution",
        ]


def test_an_unrecognized_name_in_this_languages_namespace_is_cleaned_up(tmp_path: Path) -> None:
    """The property the per-language namespace buys, and the reason it beats a declared list: an
       entry written by a *previous version* under a name this one has never heard of is still
       recognisably ours, so it goes--with nothing to remember and nothing to declare."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "configurations": [
                    _config("CG Python3: Some Name From The Future"),
                    _config("Mine"),
                ],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "Mine", "CG Python3: Debug solution",
        ]


def test_retired_names_reach_outside_this_languages_namespace(tmp_path: Path) -> None:
    """What `retired_names` is actually for, now that same-language renames need no declaration: an
       entry stranded under a *different, still-known* language, which neither the namespace rule
       nor the unknown-segment rule can see."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "configurations": [_config("CG C++: Debug solution"), _config("Mine")],
        }))

    write_provisioning(
            CgVsCodeProvisioning(
                    configurations=[_config("CG Python3: Debug solution")],
                    retired_names=["CG C++: Debug solution"]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "Mine", "CG Python3: Debug solution",
        ]


def test_a_users_own_cg_shaped_name_is_never_touched(tmp_path: Path) -> None:
    """`CG ` marks cg's namespace, but only in the full `CG <segment>: ` shape. Anything else that
       merely starts with those characters is the user's."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "configurations": [_config("CG is my favourite tool"), _config("CGI: render")],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "CG is my favourite tool", "CGI: render", "CG Python3: Debug solution",
        ]


def test_per_directory_entries_from_earlier_versions_are_cleaned_out(tmp_path: Path) -> None:
    """Through 1.0.x every working directory added its own named configuration and its own
       `pickString` inputs. Matching only the current spelling would leave one stale entry per
       directory ever provisioned, each prompting for a test case nothing reads."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "inputs": [{"id": "cg_contribution_testCase"}, {"id": "myOwnInput"}],
            "configurations": [
                    _config("CG puzzle: Debug solution against test case"),
                    _config("CG my-contribution: Debug solution against test case"),
                    _config("My Own Thing"),
                ],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    data = _launch(tmp_path)
    assert [c["name"] for c in data["configurations"]] == ["My Own Thing", "CG Python3: Debug solution"]
    # The user's own input survives; ours goes. An empty list would be a puzzling relic, so the
    # key is dropped entirely when nothing is left of cg's.
    assert [i["id"] for i in data["inputs"]] == ["myOwnInput"]


def test_the_inputs_key_disappears_when_nothing_owns_it(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "inputs": [{"id": "cg_puzzle_testCase"}], "configurations": [],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert "inputs" not in _launch(tmp_path)


def test_rewriting_is_idempotent(tmp_path: Path) -> None:
    """Now across working directories too, not just repeated runs on one: two directories in a
       workspace produce the same entry, so provisioning both leaves exactly one."""
    root = tmp_path / "puzzle"
    root.mkdir()
    other = tmp_path / "contribution"
    other.mkdir()
    provisioning = CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")])

    write_provisioning(provisioning, root=root, workspace_root=tmp_path, language="Python3")
    write_provisioning(provisioning, root=other, workspace_root=tmp_path, language="Python3")
    write_provisioning(provisioning, root=root, workspace_root=tmp_path, language="Python3")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == ["CG Python3: Debug solution"]


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
                CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
                root=root, workspace_root=tmp_path, language="Python3")

    assert (vscode / "launch.json").read_text() == original  # untouched


def test_force_overwrites_a_jsonc_file(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text('{\n  // drop me\n  "configurations": []\n}\n')

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3", force=True)

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == ["CG Python3: Debug solution"]


def test_recommended_extensions_are_unioned_never_removed(tmp_path: Path) -> None:
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "extensions.json").write_text(json.dumps({"recommendations": ["some.user-extension"]}))

    write_provisioning(
            CgVsCodeProvisioning(recommended_extensions=["ms-python.python", "some.user-extension"]),
            root=root, workspace_root=tmp_path, language="Python3")

    data = json.loads((vscode / "extensions.json").read_text())
    assert data["recommendations"] == ["some.user-extension", "ms-python.python"]


def test_files_are_written_relative_to_the_working_dir_not_the_workspace(tmp_path: Path) -> None:
    """These files describe *this* working directory's toolchain, so they belong inside it--not at
       the workspace root where `.vscode/` goes.

       And within it, under `.meta/`: they're generated rather than hand-maintained, and `.meta/` is
       the only part of a working directory that's gitignored, so anywhere else they'd be committed
       into whatever repository tracks the directory."""
    root = tmp_path / "puzzle"
    root.mkdir()
    relative = ".meta/.devcontainer/devcontainer.json"

    written = write_provisioning(
            CgVsCodeProvisioning(files={relative: '{"image": "x"}\n'}),
            root=root, workspace_root=tmp_path, language="Python3")

    assert written == [root / relative]
    assert (root / relative).read_text() == '{"image": "x"}\n'
    assert not (tmp_path / ".meta").exists()


# --- obsolete files -----------------------------------------------------------------------------


def test_obsolete_files_from_earlier_versions_are_removed(tmp_path: Path) -> None:
    """C++ wrote `devcontainer.json` at the working directory root through 1.0.x. Left behind it is
       untracked clutter offering VS Code a stale "Reopen in Container"."""
    root = tmp_path / "puzzle"
    old = root / ".devcontainer"
    old.mkdir(parents=True)
    (old / "devcontainer.json").write_text("{}")

    write_provisioning(
            CgVsCodeProvisioning(
                    files={".meta/.devcontainer/devcontainer.json": "{}"},
                    obsolete_files=[".devcontainer/devcontainer.json"]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert (root / ".meta" / ".devcontainer" / "devcontainer.json").is_file()
    assert not old.exists()  # emptied, so the directory goes too


def test_removing_an_obsolete_file_leaves_a_non_empty_directory_alone(tmp_path: Path) -> None:
    """The user may have put something of their own beside it. Deleting the file is cg cleaning up
       after itself; deleting their directory is not."""
    root = tmp_path / "puzzle"
    old = root / ".devcontainer"
    old.mkdir(parents=True)
    (old / "devcontainer.json").write_text("{}")
    (old / "Dockerfile").write_text("FROM scratch\n")

    write_provisioning(
            CgVsCodeProvisioning(obsolete_files=[".devcontainer/devcontainer.json"]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert not (old / "devcontainer.json").exists()
    assert (old / "Dockerfile").is_file()


def test_removing_an_already_absent_obsolete_file_is_a_no_op(tmp_path: Path) -> None:
    """The normal case, on every run after the first."""
    root = tmp_path / "puzzle"
    root.mkdir()

    write_provisioning(
            CgVsCodeProvisioning(obsolete_files=[".devcontainer/devcontainer.json"]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert not (root / ".devcontainer").exists()


def test_every_naming_scheme_cg_has_ever_used_is_recognized(tmp_path: Path) -> None:
    """A managed entry only stays recoverable if the rule that recognizes it is broader than the
       rule that writes it. Miss a shape and those entries are stranded in the user's file forever,
       still wired to a debug module or task that may no longer exist."""
    root = tmp_path / "puzzle"
    root.mkdir()
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "launch.json").write_text(json.dumps({
            "configurations": [
                    _config("CG puzzle: Debug solution against test case"),      # 1.0.x
                    _config("CG my-contribution: Debug solution against test case"),
                    _config("CG: Debug C++ solution (selected test)"),           # intermediate
                    _config("Mine"),
                ],
        }))

    write_provisioning(
            CgVsCodeProvisioning(configurations=[_config("CG Python3: Debug solution")]),
            root=root, workspace_root=tmp_path, language="Python3")

    assert [c["name"] for c in _launch(tmp_path)["configurations"]] == [
            "Mine", "CG Python3: Debug solution",
        ]
