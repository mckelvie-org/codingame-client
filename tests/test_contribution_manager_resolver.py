"""Unit tests for codingame_client.contribution_manager.resolver: contribution working directory
   discovery precedence (explicit > CG_CONTRIBUTION_DIR > settings > cwd > ./contribution).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_client.config.cg_config import CgConfigData
from codingame_client.config.resolver import CgConfig
from codingame_client.contribution_manager.resolver import (
    CG_CONTRIBUTION_DIR_ENV_VAR,
    CgContributionDirNotFoundError,
    find_contribution_dir,
    resolve_contribution_dir,
)
from codingame_client.contribution_manager.schema import CONTRIBUTION_FILE_NAME
from codingame_client.settings import CgSettings, CgSettingsData


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CG_CONTRIBUTION_DIR_ENV_VAR, raising=False)


def _settings_with_contribution_dir(value: str | None, tmp_path: Path) -> CgSettings:
    config = CgConfig(config_file=tmp_path / "config.yaml", raw_data=CgConfigData())
    return CgSettings(
            settings_file=tmp_path / "settings.json",
            raw_data=CgSettingsData(contribution_dir=value),
            config=config,
        )


def test_explicit_wins_even_without_a_manifest_file(tmp_path: Path) -> None:
    target = tmp_path / "fresh-empty-dir"
    assert find_contribution_dir(target) == target.resolve()


def test_env_var_used_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CG_CONTRIBUTION_DIR_ENV_VAR, str(tmp_path / "from-env"))
    assert find_contribution_dir() == (tmp_path / "from-env").resolve()


def test_explicit_overrides_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CG_CONTRIBUTION_DIR_ENV_VAR, str(tmp_path / "from-env"))
    explicit = tmp_path / "explicit"
    assert find_contribution_dir(explicit) == explicit.resolve()


def test_settings_used_when_no_explicit_or_env(tmp_path: Path) -> None:
    settings = _settings_with_contribution_dir(str(tmp_path / "from-settings"), tmp_path)
    assert find_contribution_dir(settings=settings) == (tmp_path / "from-settings").resolve()


def test_env_overrides_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CG_CONTRIBUTION_DIR_ENV_VAR, str(tmp_path / "from-env"))
    settings = _settings_with_contribution_dir(str(tmp_path / "from-settings"), tmp_path)
    assert find_contribution_dir(settings=settings) == (tmp_path / "from-env").resolve()


def test_cwd_used_when_it_contains_manifest(tmp_path: Path) -> None:
    (tmp_path / CONTRIBUTION_FILE_NAME).write_text("{}")
    assert find_contribution_dir(start_dir=tmp_path) == tmp_path


def test_contribution_subdir_used_when_it_contains_manifest(tmp_path: Path) -> None:
    sub = tmp_path / "contribution"
    sub.mkdir()
    (sub / CONTRIBUTION_FILE_NAME).write_text("{}")
    assert find_contribution_dir(start_dir=tmp_path) == sub


def test_cwd_preferred_over_contribution_subdir(tmp_path: Path) -> None:
    (tmp_path / CONTRIBUTION_FILE_NAME).write_text("{}")
    sub = tmp_path / "contribution"
    sub.mkdir()
    (sub / CONTRIBUTION_FILE_NAME).write_text("{}")
    assert find_contribution_dir(start_dir=tmp_path) == tmp_path


def test_returns_none_when_nothing_found(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert find_contribution_dir(start_dir=empty) is None


def test_settings_with_no_override_falls_through_to_cwd_check(tmp_path: Path) -> None:
    (tmp_path / CONTRIBUTION_FILE_NAME).write_text("{}")
    settings = _settings_with_contribution_dir(None, tmp_path)
    assert find_contribution_dir(settings=settings, start_dir=tmp_path) == tmp_path


# --- resolve_contribution_dir -----------------------------------------------------------------


def test_resolve_raises_not_found_without_allow_default(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CgContributionDirNotFoundError):
        resolve_contribution_dir(start_dir=empty)


def test_resolve_allow_default_falls_back_to_start_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert resolve_contribution_dir(start_dir=empty, allow_default=True) == empty.resolve()


def test_resolve_allow_default_still_prefers_a_real_match(tmp_path: Path) -> None:
    (tmp_path / CONTRIBUTION_FILE_NAME).write_text("{}")
    assert resolve_contribution_dir(start_dir=tmp_path, allow_default=True) == tmp_path
