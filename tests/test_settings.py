"""Unit tests for codingame_client.settings.cg_settings: CgSettingsData/CgSettings resolution and
   the defaultProfile fallback chain (settings.json -> config.yaml -> hardcoded "default").

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

from codingame_client.config.cg_config import CgConfigData
from codingame_client.config.resolver import CgConfig
from codingame_client.settings.cg_settings import (
    SETTINGS_FILE_NAME,
    CgSettings,
    CgSettingsData,
    resolve_settings,
    write_settings,
)


def _make_config(tmp_path: Path, *, default_profile: str | None = None) -> CgConfig:
    config_file = tmp_path / ".cg" / "config" / "config.yaml"
    config_file.parent.mkdir(parents=True)
    raw_data = CgConfigData(default_profile=default_profile)
    raw_data.save_yaml(config_file)
    return CgConfig(config_file=config_file, raw_data=raw_data)


def test_resolve_settings_defaults_when_file_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    settings = resolve_settings(config)
    assert settings.raw_data == CgSettingsData()
    assert settings.settings_file == config.data_dir / SETTINGS_FILE_NAME
    assert not settings.settings_file.exists()


def test_default_profile_falls_back_to_hardcoded_default(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    settings = resolve_settings(config)
    assert settings.default_profile == "default"


def test_default_profile_falls_back_to_config_when_settings_unset(tmp_path: Path) -> None:
    config = _make_config(tmp_path, default_profile="from-config")
    settings = resolve_settings(config)
    assert settings.default_profile == "from-config"


def test_default_profile_settings_override_wins_over_config(tmp_path: Path) -> None:
    config = _make_config(tmp_path, default_profile="from-config")
    settings = CgSettings(
        settings_file=config.data_dir / SETTINGS_FILE_NAME,
        raw_data=CgSettingsData(default_profile="from-settings"),
        config=config,
    )
    assert settings.default_profile == "from-settings"


def test_settings_save_and_resolve_round_trip(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    settings = resolve_settings(config)
    settings.raw_data.default_profile = "work"
    settings.save()
    assert settings.settings_file.is_file()

    reloaded = resolve_settings(config)
    assert reloaded.raw_data.default_profile == "work"
    assert reloaded.default_profile == "work"


def test_write_settings_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "settings.json"
    write_settings(CgSettingsData(default_profile="x"), target)
    assert target.is_file()
    assert CgSettingsData.load(target).default_profile == "x"


def test_to_dump_dict_has_resolved_and_raw(tmp_path: Path) -> None:
    config = _make_config(tmp_path, default_profile="from-config")
    settings = resolve_settings(config)
    d = settings.to_dump_dict()
    assert d["settingsFile"] == str(settings.settings_file)
    assert d["defaultProfile"] == "from-config"
    assert d["rawSettings"] == {}  # nothing set in settings.json itself
