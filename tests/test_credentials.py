"""Unit tests for codingame_client.common.credentials.

These are pure/local tests--no network, no live CodinGame API--so they run under the
default `pdm run test` invocation alongside the mock/cassette tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from private_files import PrivateDirManager

from codingame_client.credentials.cg_credentials import (
    CG_SESSION_TOKEN_ENV_VAR,
    REMEMBER_ME_TOKEN_ENV_VAR,
    CgCredentials,
    CgCredentialsProfileStore,
    CgInMemoryCredentialsProfileStorer,
    CgInMemoryCredentialsStorer,
    CgPrivateFileCredentialsProfileStorer,
    CgPrivateFileCredentialsStorer,
    get_credentials,
    get_credentials_with_override,
    get_in_memory_credentials_store,
    is_valid_profile_name,
    set_credentials,
    validate_profile_name,
)


@pytest.fixture
def private_dir_manager(tmp_path: Path) -> PrivateDirManager:
    return PrivateDirManager(tmp_path)


@pytest.fixture
def fresh_store() -> CgCredentialsProfileStore:
    """A brand-new, fully isolated in-memory profile store (unlike the process-wide
       get_in_memory_credentials_store() singleton, which is shared/cached across callers)."""
    return CgCredentialsProfileStore(CgInMemoryCredentialsProfileStorer())


def test_get_in_memory_credentials_store_is_a_cached_singleton() -> None:
    assert get_in_memory_credentials_store() is get_in_memory_credentials_store()


# --- profile name validation -------------------------------------------------------------


def test_is_valid_profile_name() -> None:
    assert is_valid_profile_name("default")
    assert is_valid_profile_name("work_account")
    assert not is_valid_profile_name("_private")
    assert not is_valid_profile_name("has space")
    assert not is_valid_profile_name("1starts_with_digit")


def test_validate_profile_name_raises_on_invalid() -> None:
    validate_profile_name("default")  # does not raise
    with pytest.raises(ValueError, match="Invalid profile name"):
        validate_profile_name("_private")


# --- CgCredentials round-trip -------------------------------------------------------------


def test_credentials_saves_loads_round_trip() -> None:
    original = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    restored = CgCredentials.loads(original.saves())
    assert restored == original


def test_credentials_catch_all_preserves_unknown_fields() -> None:
    restored = CgCredentials.loads('{"rememberMeCookie": "rm", "futureField": 42}')
    assert restored.remember_me_cookie == "rm"
    assert restored.extra_data == {"futureField": 42}
    # Round-tripping again should not silently drop the unknown field.
    assert CgCredentials.loads(restored.saves()).extra_data == {"futureField": 42}


# --- CgInMemoryCredentialsStorer -----------------------------------------------------------


def test_in_memory_storer_lifecycle() -> None:
    storer = CgInMemoryCredentialsStorer()
    assert not storer.persistent_credentials_exist()
    assert storer.read_persistent_credentials() == CgCredentials()

    creds = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    storer.write_persistent_credentials(creds)
    assert storer.persistent_credentials_exist()
    assert storer.read_persistent_credentials() == creds

    storer.delete_persistent_credentials()
    assert not storer.persistent_credentials_exist()
    assert storer.read_persistent_credentials() == CgCredentials()


def test_in_memory_storer_write_is_deep_copied() -> None:
    """Mutating the caller's object after writing must not affect the stored value."""
    storer = CgInMemoryCredentialsStorer()
    creds = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    storer.write_persistent_credentials(creds)
    creds.remember_me_cookie = "mutated"
    assert storer.read_persistent_credentials().remember_me_cookie == "rm"


# --- CgPrivateFileCredentialsStorer --------------------------------------------------------


def test_private_file_storer_lifecycle(private_dir_manager: PrivateDirManager, tmp_path: Path) -> None:
    file_path = tmp_path / "nested" / "credentials.json"
    storer = CgPrivateFileCredentialsStorer(private_dir_manager, file_path)
    assert not storer.persistent_credentials_exist()
    assert storer.read_persistent_credentials() == CgCredentials()

    creds = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    storer.write_persistent_credentials(creds)
    assert file_path.is_file()
    assert storer.persistent_credentials_exist()
    assert storer.read_persistent_credentials() == creds

    storer.delete_persistent_credentials()
    assert not file_path.exists()
    assert not storer.persistent_credentials_exist()


# --- Profile storers: covers the _profiles/_profile_storers attribute-name bug -------------


def test_in_memory_profile_storer_isolates_profiles() -> None:
    profile_storer = CgInMemoryCredentialsProfileStorer()
    assert profile_storer.list_persistent_profile_names() == []

    default_storer = profile_storer.create_single_profile_storer("default")
    alt_storer = profile_storer.create_single_profile_storer("alt")
    assert default_storer is not alt_storer

    default_storer.write_persistent_credentials(CgCredentials(remember_me_cookie="a", cg_session_cookie="a"))
    assert profile_storer.list_persistent_profile_names() == ["default"]

    alt_storer.write_persistent_credentials(CgCredentials(remember_me_cookie="b", cg_session_cookie="b"))
    assert profile_storer.list_persistent_profile_names() == ["alt", "default"]

    # Re-requesting the same profile name must return the same underlying storer instance.
    assert profile_storer.create_single_profile_storer("default") is default_storer


def test_private_file_profile_storer_creates_expected_layout(
    private_dir_manager: PrivateDirManager, tmp_path: Path
) -> None:
    """Covers the real ~/.private/<app>/profiles/<profile>/credentials.json layout, including
       the create_parent bug that previously made this raise FileNotFoundError."""
    profile_storer = CgPrivateFileCredentialsProfileStorer(private_dir_manager)
    assert profile_storer.list_persistent_profile_names() == []

    storer = profile_storer.create_single_profile_storer("work")
    storer.write_persistent_credentials(CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs"))

    expected_file = tmp_path / "profiles" / "work" / "credentials.json"
    assert expected_file.is_file()
    assert profile_storer.list_persistent_profile_names() == ["work"]


# --- CgCredentialsProfileStore: dirty tracking, commit/cancel ------------------------------


def test_profile_store_set_get_roundtrip(fresh_store: CgCredentialsProfileStore) -> None:
    creds = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    fresh_store.set_credentials("default", creds)
    assert fresh_store.get_credentials("default") == creds
    # Different profile names must not see each other's values.
    assert fresh_store.get_credentials("other") is None


def test_profile_store_dirty_and_commit_semantics() -> None:
    profile_storer = CgInMemoryCredentialsProfileStorer()
    profile_store = CgCredentialsProfileStore(profile_storer)
    single_store = profile_store.get_profile_store("default")

    assert not single_store.dirty
    single_store.set_credentials(CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs"))
    assert single_store.dirty

    profile_store.commit()
    assert not single_store.dirty
    # The underlying storer must now actually have the value.
    underlying = profile_storer.create_single_profile_storer("default")
    assert underlying.read_persistent_credentials().remember_me_cookie == "rm"


def test_profile_store_cancel_discards_uncommitted_changes() -> None:
    profile_storer = CgInMemoryCredentialsProfileStorer()
    profile_store = CgCredentialsProfileStore(profile_storer)
    single_store = profile_store.get_profile_store("default")

    single_store.set_credentials(CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs"))
    assert single_store.dirty
    single_store.cancel()
    assert not single_store.dirty
    assert single_store.get_credentials() is None


def test_profile_store_prune_deleted_profiles() -> None:
    profile_storer = CgInMemoryCredentialsProfileStorer()
    profile_store = CgCredentialsProfileStore(profile_storer)

    profile_store.set_credentials("ghost", None)
    profile_store.commit()
    assert "ghost" in profile_store.list_profile_names()

    profile_store.prune_deleted_profiles()
    assert "ghost" not in profile_store.list_profile_names()


# --- Module-level convenience functions ----------------------------------------------------


def test_get_set_credentials_with_explicit_store(fresh_store: CgCredentialsProfileStore) -> None:
    assert get_credentials(store=fresh_store).remember_me_cookie is None

    creds = CgCredentials(remember_me_cookie="rm", cg_session_cookie="cs")
    set_credentials(creds, store=fresh_store)
    assert get_credentials(store=fresh_store) == creds


def test_get_credentials_treats_partial_credentials_as_empty(fresh_store: CgCredentialsProfileStore) -> None:
    """A profile with only one of the two cookies must resolve as if it had none at all."""
    partial = CgCredentials(remember_me_cookie="rm", cg_session_cookie=None)
    set_credentials(partial, store=fresh_store)
    resolved = get_credentials(store=fresh_store)
    assert resolved == CgCredentials()


class TestGetCredentialsWithOverride:
    """Covers the documented resolution order: explicit tokens > credentials object > env vars > store."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REMEMBER_ME_TOKEN_ENV_VAR, raising=False)
        monkeypatch.delenv(CG_SESSION_TOKEN_ENV_VAR, raising=False)

    def test_falls_back_to_empty_when_nothing_available(self, fresh_store: CgCredentialsProfileStore) -> None:
        result = get_credentials_with_override(store=fresh_store)
        assert result == CgCredentials()

    def test_uses_store_when_nothing_else_overrides(self, fresh_store: CgCredentialsProfileStore) -> None:
        stored = CgCredentials(remember_me_cookie="stored-rm", cg_session_cookie="stored-cs")
        set_credentials(stored, store=fresh_store)
        result = get_credentials_with_override(store=fresh_store)
        assert result == stored

    def test_env_vars_override_store(
        self, fresh_store: CgCredentialsProfileStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_credentials(
            CgCredentials(remember_me_cookie="stored-rm", cg_session_cookie="stored-cs"),
            store=fresh_store,
        )
        monkeypatch.setenv(REMEMBER_ME_TOKEN_ENV_VAR, "env-rm")
        monkeypatch.setenv(CG_SESSION_TOKEN_ENV_VAR, "env-cs")
        result = get_credentials_with_override(store=fresh_store)
        assert result.remember_me_cookie == "env-rm"
        assert result.cg_session_cookie == "env-cs"

    def test_credentials_object_overrides_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REMEMBER_ME_TOKEN_ENV_VAR, "env-rm")
        monkeypatch.setenv(CG_SESSION_TOKEN_ENV_VAR, "env-cs")
        override = CgCredentials(remember_me_cookie="obj-rm", cg_session_cookie="obj-cs")
        result = get_credentials_with_override(credentials=override)
        assert result == override

    def test_explicit_tokens_override_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(REMEMBER_ME_TOKEN_ENV_VAR, "env-rm")
        monkeypatch.setenv(CG_SESSION_TOKEN_ENV_VAR, "env-cs")
        override = CgCredentials(remember_me_cookie="obj-rm", cg_session_cookie="obj-cs")
        result = get_credentials_with_override(
            credentials=override, remember_me_token="explicit-rm", cg_session_token="explicit-cs",
        )
        assert result.remember_me_cookie == "explicit-rm"
        assert result.cg_session_cookie == "explicit-cs"
