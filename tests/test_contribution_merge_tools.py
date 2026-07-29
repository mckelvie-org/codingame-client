"""Unit tests for codingame_client.contribution_manager.merge_tools: the external 3-way
   diff/merge tool registry/launcher.

These are pure/local tests--no network, and no real external tool is actually launched (the
"tool found" happy path is stubbed via monkeypatching subprocess.run)--so they run under the
default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codingame_client.contribution_manager.merge_tools import (
    MERGE_TOOL_COMMANDS,
    CgMergeToolNotFoundError,
    launch_merge_tool,
)


def test_unknown_tool_name_raises() -> None:
    with pytest.raises(CgMergeToolNotFoundError):
        launch_merge_tool("not-a-real-tool", base_dir=Path("/b"), local_dir=Path("/l"), remote_dir=Path("/r"))


def test_known_tool_not_on_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("codingame_client.contribution_manager.merge_tools.shutil.which", lambda name: None)
    with pytest.raises(CgMergeToolNotFoundError):
        launch_merge_tool("meld", base_dir=Path("/b"), local_dir=Path("/l"), remote_dir=Path("/r"))


def test_launches_with_substituted_directory_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeResult:
        returncode = 0

    def fake_run(args: list[str], **kwargs: Any) -> _FakeResult:
        captured["args"] = args
        return _FakeResult()

    monkeypatch.setattr("codingame_client.contribution_manager.merge_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("codingame_client.contribution_manager.merge_tools.subprocess.run", fake_run)

    exit_code = launch_merge_tool("meld", base_dir=Path("/base"), local_dir=Path("/local"), remote_dir=Path("/remote"))

    assert exit_code == 0
    assert captured["args"] == ["meld", "/base", "/local", "/remote"]


def test_all_registered_tools_have_nonempty_templates() -> None:
    for name, template in MERGE_TOOL_COMMANDS.items():
        assert template, f"{name} has an empty command template"
        assert "{base}" in template and "{local}" in template and "{remote}" in template, (
                f"{name}'s template must reference all three directory placeholders")
