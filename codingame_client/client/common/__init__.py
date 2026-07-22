"""
Code that is common to both sync and async clients of the CodinGame API.
"""

from __future__ import annotations

from ...common.logging import logger
from ...common.typedefs import (
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
from .credentials import (
    CG_SESSION_TOKEN_ENV_VAR,
    REMEMBER_ME_TOKEN_ENV_VAR,
    CgCredentials,
    get_credentials,
    get_credentials_with_override,
    set_credentials,
)
from .raw_client import (
    DEFAULT_HEADERS,
    MISSING,
    CgAuthenticationError,
    CgClientErrorResponse,
    CgClientHttpError,
    CgDownloadFileResult,
    CgRawClient,
    compute_content_hash,
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
    "compute_content_hash",
    "CgDownloadFileResult",
    "DEFAULT_HEADERS",
    "MISSING",
    "CgAuthenticationError",
    "CgClientErrorResponse",
    "CgClientHttpError",
    "CgRawClient",
]
