"""
Management of persistent Codingame client credentials, including
support for browser-based login.
"""

from __future__ import annotations

from .cg_credentials import (
    CG_SESSION_TOKEN_ENV_VAR,
    CLIENT_APP_NAME,
    CREDENTIALS_FILENAME,
    DEFAULT_PROFILE_NAME,
    PROFILES_SUBDIR,
    REMEMBER_ME_TOKEN_ENV_VAR,
    CgCredentials,
    CgCredentialsProfileStore,
    CgCredentialsProfileStorer,
    CgCredentialsStore,
    CgCredentialsStorer,
    CgInMemoryCredentialsProfileStorer,
    CgInMemoryCredentialsStorer,
    CgPrivateFileCredentialsProfileStorer,
    CgPrivateFileCredentialsStorer,
    get_credentials,
    get_credentials_store,
    get_credentials_with_override,
    get_in_memory_credentials_store,
    is_valid_profile_name,
    set_credentials,
    validate_profile_name,
)

__all__ = [
    # Constants
    "REMEMBER_ME_TOKEN_ENV_VAR",
    "CG_SESSION_TOKEN_ENV_VAR",
    "CREDENTIALS_FILENAME",
    "CLIENT_APP_NAME",
    "DEFAULT_PROFILE_NAME",
    "PROFILES_SUBDIR",
    # Profile name validation
    "is_valid_profile_name",
    "validate_profile_name",
    # Credentials data
    "CgCredentials",
    # Single-profile storers
    "CgCredentialsStorer",
    "CgInMemoryCredentialsStorer",
    "CgPrivateFileCredentialsStorer",
    # Multi-profile storers
    "CgCredentialsProfileStorer",
    "CgInMemoryCredentialsProfileStorer",
    "CgPrivateFileCredentialsProfileStorer",
    # Caching stores built on top of the storers
    "CgCredentialsStore",
    "CgCredentialsProfileStore",
    "get_credentials_store",
    "get_in_memory_credentials_store",
    # Simplified module-level convenience functions
    "get_credentials",
    "set_credentials",
    "get_credentials_with_override",
]
