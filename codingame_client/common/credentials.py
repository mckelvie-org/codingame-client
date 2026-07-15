"""Management of cached credentials."""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Final

from private_files import private_files

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

@dataclass
class CgCredentials(JSONWizardX):
    remember_me_cookie: str | None = None
    cg_session_cookie: str | None = None
    
    extra_data: CatchAll = field(default_factory=dict)
    
def _prv(app_name: str | None = None) -> private_files.PrivateFiles:
    """Get a PrivateFiles instance for the given app name, or the default app name if None."""
    return private_files(app_name=CLIENT_APP_NAME if app_name is None else app_name)

_credentials_lock = threading.Lock()
_credentials: dict[str, CgCredentials] = {}
def set_credentials(credentials: CgCredentials | None, *, save: bool = True, app_name: str | None = None) -> CgCredentials | None:
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
    credentials = get_credentials(app_name=app_name)
    credentials.remember_me_cookie = token
    set_credentials(credentials, save=save, app_name=app_name)
    return token

def get_remember_me_token(*, app_name: str | None = None) -> str | None:
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
    token = get_remember_me_token(app_name=app_name)
    if token is None:
        raise ValueError(
            f"Remember me token not set. Please set the {REMEMBER_ME_TOKEN_ENV_VAR} environment " +
            f"variable or set credentials at {_prv(app_name=app_name).get_private_file(filename=CREDENTIALS_FILENAME)}."
        )
    return token

def set_cg_session_token(token: str | None, *, save: bool = True, app_name: str | None = None) -> str | None:
    credentials = get_credentials(app_name=app_name)
    credentials.cg_session_cookie = token
    set_credentials(credentials, save=save, app_name=app_name)
    return token

def get_cg_session_token(*, app_name: str | None = None) -> str | None:
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
    token = get_cg_session_token(app_name=app_name)
    if token is None:
        raise ValueError(
            f"CG session token not set. Please set the {CG_SESSION_TOKEN_ENV_VAR} environment " +
            f"variable or set credentials at {_prv(app_name=app_name).get_private_file(filename=CREDENTIALS_FILENAME)}."
        )
    return token

