"""
Code that is common to both sync and async clients of the CodinGame API.
"""

from __future__ import annotations

from .credentials import (
    CG_SESSION_TOKEN_ENV_VAR,
    REMEMBER_ME_TOKEN_ENV_VAR,
    CgCredentials,
    get_credentials,
    get_credentials_with_override,
    set_credentials,
)
from .logging import logger
from .typedefs import (
    BROWSER_LOGIN_SUBDIR,
    CLIENT_APP_NAME,
    DEFAULT_PROFILE_NAME,
    PROFILES_SUBDIR,
    JsonData,
    JsonDict,
    JsonList,
    JsonScalar,
    override,
)

__all__ = [
    "BROWSER_LOGIN_SUBDIR",
    "CgCredentials",
    "get_credentials",
    "set_credentials",
    "get_credentials_with_override",
    "CG_SESSION_TOKEN_ENV_VAR",
    "CLIENT_APP_NAME",
    "DEFAULT_PROFILE_NAME",
    "PROFILES_SUBDIR",
    "REMEMBER_ME_TOKEN_ENV_VAR",
    "JsonDict",
    "JsonList",
    "JsonScalar",
    "JsonData",
    "logger",
    "override",
]
