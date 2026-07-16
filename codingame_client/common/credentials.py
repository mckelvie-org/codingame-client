"""Management of cached persistent credentials for the CodinGame client."""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Final

from private_files import PrivateFilesManager, get_private_files

from .dataclass_wizard_x import CatchAll, JSONWizardX
from .typedefs import CG_SESSION_TOKEN_ENV_VAR, CLIENT_APP_NAME, REMEMBER_ME_TOKEN_ENV_VAR

__all__ = [
    "CREDENTIALS_FILENAME",
    "CgCredentials",
    "get_credentials",
    "set_credentials",
    "get_remember_me_token",
    "set_remember_me_token",
    "require_remember_me_token",
    "set_cg_session_token",
    "get_cg_session_token",
    "require_cg_session_token",
    "set_cg_session_token",
] 

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

    extra_data: CatchAll = field(default_factory=dict)
    """Unrecognized fields encountered when loading a credentials file, preserved so that
       round-tripping through `saves()`/`loads()` does not silently drop data."""

def _prv(app_name: str | None = None) -> PrivateFilesManager:
    """Get a PrivateFiles instance for the given app name, or the default app name if None."""
    return get_private_files(app_name=CLIENT_APP_NAME if app_name is None else app_name)

_credentials_lock = threading.Lock()
_credentials: dict[str, CgCredentials] = {}
"""In-process cache of credentials, keyed by app name, shared across all callers in the process."""


def set_credentials(credentials: CgCredentials | None, *, save: bool = True, app_name: str | None = None) -> CgCredentials | None:
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
        _credentials[app_name] = credentials
        return credentials
    
def get_credentials(*, app_name: str | None = None) -> CgCredentials:
    """Return the current credentials for an app.

       Resolution order: the in-process cache, then the per-app private credentials file
       (which populates the cache on success), then an empty `CgCredentials()` if neither
       is available. Note that this does not consider the `REMEMBER_ME_TOKEN_ENV_VAR` /
       `CG_SESSION_TOKEN_ENV_VAR` environment variables; use `get_remember_me_token()` /
       `get_cg_session_token()` for that.

       Args:
           app_name: The app namespace to read credentials from; defaults to `CLIENT_APP_NAME`.

       Returns:
           A deep copy of the resolved credentials; never `None`.
    """
    if app_name is None:
        app_name = CLIENT_APP_NAME
        
    with _credentials_lock:
        credentials = _credentials.get(app_name)
        if credentials is None:
            # Try to read from the file if the environment variable is not set
            try:
                with _prv(app_name=app_name).open(CREDENTIALS_FILENAME, "r") as f:
                    credentials_json = f.read()
                    credentials = CgCredentials.loads(credentials_json)
                    _credentials[app_name] = credentials
            except FileNotFoundError:
                credentials = CgCredentials()  # If the file does not exist, return empty credentials
                _credentials[app_name] = credentials
        return deepcopy(credentials)
    
def set_remember_me_token(token: str | None, *, save: bool = True, app_name: str | None = None) -> str | None:
    """Set (or clear, with `token=None`) the `rememberMe` cookie value in the cached credentials.

       Args:
           token: The new `rememberMe` cookie value, or `None` to clear it.
           save: If True (the default), also persist the updated credentials to disk.
           app_name: The app namespace to update; defaults to `CLIENT_APP_NAME`.

       Returns:
           `token`, unchanged, for convenience.
    """
    credentials = get_credentials(app_name=app_name)
    credentials.remember_me_cookie = token
    set_credentials(credentials, save=save, app_name=app_name)
    return token

def get_remember_me_token(*, app_name: str | None = None) -> str | None:
    """Return the current `rememberMe` cookie value, or `None` if not set.

       The `REMEMBER_ME_TOKEN_ENV_VAR` environment variable takes precedence over stored
       credentials when set to a non-blank value; this allows overriding persisted
       credentials for a single process without modifying the credentials file.

       Args:
           app_name: The app namespace to fall back to when the environment variable is
               unset; defaults to `CLIENT_APP_NAME`.
    """
    remember_me_token = os.getenv(REMEMBER_ME_TOKEN_ENV_VAR)
    if remember_me_token is not None:
        remember_me_token = remember_me_token.strip()
        if remember_me_token == "":
            remember_me_token = None  # Treat empty string as None
    if remember_me_token is None:
        # Try to read from the credentials if the environment variable is not set
        credentials = get_credentials(app_name=app_name)
        remember_me_token = credentials.remember_me_cookie
    return remember_me_token

def require_remember_me_token(*, app_name: str | None = None) -> str:
    """Like `get_remember_me_token()`, but raises `ValueError` instead of returning `None`.

       Args:
           app_name: The app namespace to check; defaults to `CLIENT_APP_NAME`.

       Raises:
           ValueError: If no `rememberMe` token is set via environment variable or credentials.
    """
    token = get_remember_me_token(app_name=app_name)
    if token is None:
        raise ValueError(
            f"Remember me token not set. Please set the {REMEMBER_ME_TOKEN_ENV_VAR} environment " +
            f"variable or set credentials at {_prv(app_name=app_name).get_private_file(filename=CREDENTIALS_FILENAME)}."
        )
    return token

def set_cg_session_token(token: str | None, *, save: bool = True, app_name: str | None = None) -> str | None:
    """Set (or clear, with `token=None`) the `cgSession` cookie value in the cached credentials.

       Args:
           token: The new `cgSession` cookie value, or `None` to clear it.
           save: If True (the default), also persist the updated credentials to disk.
           app_name: The app namespace to update; defaults to `CLIENT_APP_NAME`.

       Returns:
           `token`, unchanged, for convenience.
    """
    credentials = get_credentials(app_name=app_name)
    credentials.cg_session_cookie = token
    set_credentials(credentials, save=save, app_name=app_name)
    return token

def get_cg_session_token(*, app_name: str | None = None) -> str | None:
    """Return the current `cgSession` cookie value, or `None` if not set.

       The `CG_SESSION_TOKEN_ENV_VAR` environment variable takes precedence over stored
       credentials when set to a non-blank value; this allows overriding persisted
       credentials for a single process without modifying the credentials file.

       Args:
           app_name: The app namespace to fall back to when the environment variable is
               unset; defaults to `CLIENT_APP_NAME`.
    """
    cg_session_token = os.getenv(CG_SESSION_TOKEN_ENV_VAR)
    if cg_session_token is not None:
        cg_session_token = cg_session_token.strip()
        if cg_session_token == "":
            cg_session_token = None  # Treat empty string as None
    if cg_session_token is None:
        # Try to read from the credentials if the environment variable is not set
        credentials = get_credentials(app_name=app_name)
        cg_session_token = credentials.cg_session_cookie
    return cg_session_token

def require_cg_session_token(*, app_name: str | None = None) -> str:
    """Like `get_cg_session_token()`, but raises `ValueError` instead of returning `None`.

       Args:
           app_name: The app namespace to check; defaults to `CLIENT_APP_NAME`.

       Raises:
           ValueError: If no `cgSession` token is set via environment variable or credentials.
    """
    token = get_cg_session_token(app_name=app_name)
    if token is None:
        raise ValueError(
            f"CG session token not set. Please set the {CG_SESSION_TOKEN_ENV_VAR} environment " +
            f"variable or set credentials at {_prv(app_name=app_name).get_private_file(filename=CREDENTIALS_FILENAME)}."
        )
    return token

