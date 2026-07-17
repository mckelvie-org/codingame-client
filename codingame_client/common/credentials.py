"""Management of cached persistent credentials for the CodinGame client."""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Final

from private_files import PrivateFilesManager, get_private_files

from .dataclass_wizard_x import CatchAll, JSONWizardX
from .typedefs import CLIENT_APP_NAME

__all__ = [
    "CREDENTIALS_FILENAME",
    "CgCredentials",
    "get_credentials",
    "set_credentials",
    "get_credentials_with_override",
    "CG_SESSION_TOKEN_ENV_VAR",
    "REMEMBER_ME_TOKEN_ENV_VAR",
    "CREDENTIALS_FILENAME",
] 

REMEMBER_ME_TOKEN_ENV_VAR: Final[str] = "CODINGAME_REMEMBER_ME"
"""The name of the environment variable that can be set to provide the CodinGame remember_me cookie for authentication."""

CG_SESSION_TOKEN_ENV_VAR: Final[str] = "CODINGAME_SESSION"
"""The name of the environment variable that can be set to provide the CodinGame cg_session cookie for authentication."""


CREDENTIALS_FILENAME: Final[str] = "credentials.json"
"""Name of the JSON file, within a per-app private directory, that persisted credentials are stored in."""

@dataclass
class CgCredentials(JSONWizardX):
    """Persistable CodinGame session credentials.

       Both cookies are optional since a partially-completed browser login may capture
       only the `rememberMe` cookie before the `cgSession` cookie becomes available.
    """

    remember_me_cookie: str | None = None
    """Value of the CodinGame `rememberMe` cookie, used to establish a new session."""

    cg_session_cookie: str | None = None
    """Value of the CodinGame `cgSession` cookie for an active session. Required for some
       operations (e.g., file upload) that are not supported via `rememberMe` alone."""

    # kw_only=True is mandatory if this field follows a field with defaults
    extra_data: CatchAll = field(default_factory=dict, kw_only=True)
    """Unrecognized fields encountered when loading a credentials file, preserved so that
       round-tripping through `saves()`/`loads()` does not silently drop data."""

def _prv(app_name: str | None = None) -> PrivateFilesManager:
    """Get a PrivateFiles instance for the given app name, or the default app name if None."""
    return get_private_files(app_name=CLIENT_APP_NAME if app_name is None else app_name)

_credentials_lock = threading.Lock()
"""Mutex to protect access to the in-process credentials cache and saved credentials cache."""

_credentials: dict[str, CgCredentials] = {}
"""In-process cache of credentials, keyed by app name, shared across all callers in the process."""

_saved_credentials: dict[str, CgCredentials] = {}
"""Persistently saved credentials, keyed by app name, shared across all callers in the process.
   This is used to determine whether the credentials have changed and need to be saved."""

def set_credentials(credentials: CgCredentials | None, *, save: bool = True, app_name: str | None = None) -> CgCredentials:
    """Replace the cached (and optionally persisted) credentials for an app.

       A deep copy of `credentials` is stored/returned so that later mutation of the caller's
       object does not affect the cache. Passing `None` resets the credentials to an empty
       `CgCredentials()` instance.

       Args:
           credentials: The new credentials, or `None` to clear them.
           save: If True (the default), also write the credentials to the per-app private
               credentials file. If False, only the in-process cache is updated.
           app_name: The app namespace to store credentials under; defaults to `CLIENT_APP_NAME`.

       Returns:
           The (deep-copied) credentials that are now cached.
    """
    if app_name is None:
        app_name = CLIENT_APP_NAME
    
    credentials = CgCredentials() if credentials is None else deepcopy(credentials)
    
    with _credentials_lock:
        if save:
            # Save to file
            with _prv(app_name=app_name).open(CREDENTIALS_FILENAME, "w") as f:
                f.write(credentials.saves())
            _saved_credentials[app_name] = deepcopy(credentials)
        _credentials[app_name] = deepcopy(credentials)
        return credentials
    
def get_credentials(*, app_name: str | None = None, force: bool = False) -> CgCredentials:
    """Return the current credentials for an app.

       Resolution order: the in-process cache, then the per-app private credentials file
       (which populates the cache on success), then an empty `CgCredentials()` if neither
       is available. Note that this does not consider the `REMEMBER_ME_TOKEN_ENV_VAR` /
       `CG_SESSION_TOKEN_ENV_VAR` environment variables; use `get_remember_me_token()` /
       `get_cg_session_token()` for that.

       Args:
           app_name: The app namespace to read credentials from; defaults to `CLIENT_APP_NAME`.
           force: If True, ignore the in-process cache and reload from the credentials file.

       Returns:
           A deep copy of the resolved credentials; never `None`.
    """
    if app_name is None:
        app_name = CLIENT_APP_NAME
        
    with _credentials_lock:
        credentials = None if force else _credentials.get(app_name)
        if credentials is None:
            try:
                with _prv(app_name=app_name).open(CREDENTIALS_FILENAME, "r") as f:
                    credentials_json = f.read()
                    credentials = CgCredentials.loads(credentials_json)
            except FileNotFoundError:
                credentials = CgCredentials()  # If the file does not exist, return empty credentials
            _saved_credentials[app_name] = deepcopy(credentials)
        _credentials[app_name] = deepcopy(credentials)
        return deepcopy(credentials)
    
def get_credentials_with_override(
            *,
            credentials: CgCredentials | None = None,
            remember_me_token: str | None = None,
            cg_session_token: str | None = None,
            app_name: str | None = None,
            force: bool = False
        ) -> CgCredentials:
    """Return the current credentials for an app, with environment variable overrides.

       Resolution order:
          1. If non-null `remember_me_token` / `cg_session_token` are provided, use those values.
          2. If `credentials` is provided, use non-null token values from that object.
          3. check the `REMEMBER_ME_TOKEN_ENV_VAR` / `CG_SESSION_TOKEN_ENV_VAR` environment variables for overrides.
          4. If neither is provided and force is False, check the in-process cache for the app's credentials.
          5. If not in the cache, check the per-app private credentials file (which populates the cache on success).
          6. If none of the above are available, return an empty `CgCredentials()`
       
       Note that the overrides, if any, are not persisted to the credentials file or in-process cache;
       they only affect the returned object. If you want them persisted, call `set_credentials()` after this function returns.

       Args:
           remember_me_token: Optional override for the `rememberMe` cookie value.
           cg_session_token: Optional override for the `cgSession` cookie value.
           app_name: The app namespace to read credentials from; defaults to `CLIENT_APP_NAME`.
           force: If True, ignore the in-process cache and reload from the credentials file.

       Returns:
           Resolved `CgCredentials` object, with parameter and environment variable overrides applied.
    """
    new_credentials = get_credentials(app_name=app_name, force=force)
    if credentials is not None:
        if remember_me_token is None:
            remember_me_token = credentials.remember_me_cookie
        if cg_session_token is None:
            cg_session_token = credentials.cg_session_cookie
    if remember_me_token is None:        
        remember_me_token = os.getenv(REMEMBER_ME_TOKEN_ENV_VAR)
        if remember_me_token is not None:
            remember_me_token = remember_me_token.strip()
            if remember_me_token == "":
                remember_me_token = None  # Treat empty string as None
    if cg_session_token is None:
        cg_session_token = os.getenv(CG_SESSION_TOKEN_ENV_VAR)
        if cg_session_token is not None:
            cg_session_token = cg_session_token.strip()
            if cg_session_token == "":
                cg_session_token = None  # Treat empty string as None
    if remember_me_token is not None:
        new_credentials.remember_me_cookie = remember_me_token
    if cg_session_token is not None:
        new_credentials.cg_session_cookie = cg_session_token

    return new_credentials
    

