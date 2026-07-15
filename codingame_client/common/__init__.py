"""
Code that is common to both sync and async clients of the CodinGame API.
"""

from __future__ import annotations

from .logging import logger
from .typedefs import (
    BROWSER_PROFILE_SUBDIR,
    CG_SESSION_TOKEN_ENV_VAR,
    CLIENT_APP_NAME,
    REMEMBER_ME_TOKEN_ENV_VAR,
    JsonData,
    JsonDict,
    JsonList,
    JsonScalar,
    override,
)

__all__ = [
    "BROWSER_PROFILE_SUBDIR",
    "BROWSER_PROFILE_SUBDIR",
    "CG_SESSION_TOKEN_ENV_VAR",
    "CLIENT_APP_NAME",
    "REMEMBER_ME_TOKEN_ENV_VAR",
    "JsonDict",
    "JsonList",
    "JsonScalar",
    "JsonData",
    "logger",
    "override",
]
