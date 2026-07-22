"""
Definitions common to both the sync and async raw (JsonData) clients.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from pathlib import Path
from typing import Final, NamedTuple

from json_data_types import JsonData

from ...common.dataclass_wizard_x import CatchAll, JSONWizardX
from ...common.typedefs import DEFAULT_PROFILE_NAME, Self
from ...version import __version__
from .credentials import CgCredentials, get_credentials_store, get_credentials_with_override

__all__ = [
    "compute_content_hash",
    "CgDownloadFileResult",
    "DEFAULT_HEADERS",
    "MISSING",
    "CgAuthenticationError",
    "CgClientErrorResponse",
    "CgClientHttpError",
    "CgRawClient",
]

logger = logging.getLogger(__name__)

def compute_content_hash(content: bytes) -> str:
    """Compute the SHA256 hash of the given content and return it as a hex string."""
    sha256 = hashlib.sha256()
    sha256.update(content)
    return sha256.hexdigest()


class CgDownloadFileResult(NamedTuple):
    """The result of a successful file download"""

    id: int
    """The globally unique ID of the file, as provided by the server at upload time."""

    content: bytes
    """The content of the downloaded file."""

    content_type: str
    """The content type of the downloaded file, as provided by the server. Normalized to lowercase."""

    hash: str
    """The SHA256 hash of the downloaded file content, as a hex string.
       This can be used to verify the integrity of the downloaded file or to detect changes in local copies.
    """

    filename: str | None = None
    """The filename of the downloaded file, if provided by the server in the
       Content-Disposition header. Does not include a path. This is typically the
       original filename of the uploaded file."""

    @classmethod
    def create(
                cls,
                id: int,
                content: bytes,
                content_type: str,
                filename: str | Path | None = None,
                hash: str | None = None
            ) -> Self:
        """Create a CgDownloadFileResult instance with the given content, content type, and optional filename."""
        file_tail_name = Path(filename).name if filename is not None else None
        if hash is None:
            hash = compute_content_hash(content)
        return cls(
            id=id,
            content=content,
            content_type=content_type,
            hash=hash,
            filename=file_tail_name,
        )


DEFAULT_HEADERS: dict[str, str] = {
        "User-Agent": (
            f"codingame-client/{__version__} (+https://github.com/mckelvie-org/codingame-client)"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }

class _Missing(Enum):
    """Sentinel value for missing parameters."""
    TOKEN = object()

MISSING = _Missing.TOKEN
"""Sentinel value for missing parameters."""

class CgAuthenticationError(Exception):
    """Raised when the client is not authenticated and an operation requires authentication."""

    def __init__(self, message: str | None = None):
        super().__init__(message or "Codingame client is not authenticated. Please login first.")

@dataclass
class CgClientErrorResponse(JSONWizardX):
    """Represents a well-formed JSON error response from the CodinGame API."""

    code: str
    """The error code string returned by the API; e.g., 'BODY_MUST_BE_JSON_ARRAY'.
       This property is always present in a well-formed error response, and must not be present
       in any non-error response."""

    message: str | None = None
    """The error message returned by the API."""

    # kw_only=True is mandatory if this field follows a field with defaults
    extra_data: CatchAll = field(default_factory=dict, kw_only=True)
    """Unrecognized fields encountered when loading the error response, preserved."""


class CgClientHttpError(Exception):
    """Base class for client HTTP errors. Common to both sync and async clients.
       Contains the status code and content of the response, if available."""
    status_code: int
    """The HTTP status code of the response; e.g., 400."""

    raw_message: str
    """The unadorned error message provided at construction time. If none was
       provided, this will be the default phrase for the HTTP status code; e.g., "Bad Request".
    """

    content: JsonData | bytes | None
    """The decoded content of the response, if available. If the response was valid JSON, this will be the
       decoded JsonData value (which may be a dict, list, str, int, float, bool, or None). If the response
       could not be decoded as JSON or text, this may be raw bytes. If None, the content was not available.
    """

    api_error_response: CgClientErrorResponse | None = None
    """If the response content was a well-formed JSON error response, this will be a CgClientErrorResponse instance."""

    def __init__(
                self,
                message: str | None = None,
                *,
                status_code: int=200,
                content: JsonData | bytes | None=None
            ):
        """Create a CgClientHttpError, providing available context.

        Args:
            message:      Optional error message. If not provided, will use the status code's default phrase
            status_code:  Optional status code. If not provided, will default to 200
            content:            Optional decoded content of the response. If not provided, will be None.
        """
        if isinstance(content, dict) and "code" in content:
            with contextlib.suppress(Exception):
                self.api_error_response = CgClientErrorResponse.from_dict(content)
        self.status_code = status_code
        self.raw_message = message or HTTPStatus(status_code).phrase
        self.content = content
        if self.api_error_response is None:
            message = f"CodingGame HTTP Error: {status_code} {self.raw_message}"
        else:
            if self.api_error_response.message is not None:
                message = (
                        f"CodingGame API Error: {status_code} {self.raw_message}: "
                        f"{self.api_error_response.code}: {self.api_error_response.message}"
                    )
            else:
                message = f"CodingGame API Error: {status_code} {self.raw_message}: {self.api_error_response.code}"
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.status_code}, {self.raw_message!r})"

class CgRawClient:
    """Base class common to both sync and async clients."""

    CODINGAME_BASE_URL: Final[str] = "https://www.codingame.com"
    """Base URL for the CodinGame website. Used for most API requests, except the "static" endpoint."""

    CODINGAME_SERVLET_URL: Final[str]  = CODINGAME_BASE_URL + "/servlet"
    """Base URL for the CodinGame servlet endpoint. Used for file uploads and downloads."""

    CODINGAME_SERVICES_URL: Final[str] = CODINGAME_BASE_URL + "/services/"
    """Base URL for the CodinGame "services" requests. Used for most API requests."""

    CODINGAME_STATIC_BASE_URL: Final[str] = "https://static.codingame.com"
    """Base URL for the CodinGame static content endpoint. Used for file downloads."""

    CODINGAME_STATIC_SERVLET_URL: Final[str] = CODINGAME_STATIC_BASE_URL + "/servlet"
    """Base URL for the CodinGame static servlet endpoint. Used for file downloads."""

    credentials: CgCredentials | None = None
    """If the client is logged in, this will hold the credentials used for authentication."""

    saved_credentials: CgCredentials | None = None
    """Known contents of the saved credentials, if any. This is used to determine whether
       the credentials have changed and need to be saved."""

    login_attempted: bool = False
    """Whether a login attempt has been made. If True, further implicit login attempts will not be made."""

    app_name: str | None = None
    """The name of the application using the client. Used to allow different applications to have different
       cached credentials in the same environment. If None, a default application name is used."""

    default_http_headers: dict[str, str]
    """The HTTP headers used for requests."""

    codingamer_id: int | None = None
    """The codingamer ID of the currently logged-in user, if available. This is derived from the first part of the rememberMe cookie."""


    def __init__(
                self,
                *,
                default_http_headers: dict[str, str] | None = None,
                app_name: str | None = None,
            ):
        """Create a CgRawClient.

        Args:
            app_name: Optional name of the application using the client. Used to allow different applications to have different
                      cached credentials in the same environment. If None, a default application name is used.
        """
        self.app_name = app_name
        self.default_http_headers = default_http_headers or DEFAULT_HEADERS

    def set_credentials(
                self,
                credentials: CgCredentials | None,
                *,
                cache: bool = True,
                save: bool = True
            ) -> CgCredentials:
        """Set the credentials for the client session.

           If credentials are provided, they will be used to authenticate/reauthenticate the client session.
           If not provided, empty credentials are used, effectively logging out the client session.

           The client is only considered logged in if both a rememberMe and a cgSession cookie are present;
           credentials with only one (or neither) are treated the same as no credentials at all. This is
           because enough CodinGame endpoints require cgSession specifically (not just rememberMe) that a
           partial session isn't useful in practice.

           If cache is True (the default), the credentials will be cached process-widefor the app_name associated with the
           client session. Ignored and trated as True if save is True.

           If save is True, the credentials will be written to the per-app private credentials file.

           Returns:
                The (deep-copied) credentials that are now cached.
        """
        if credentials is None:
            credentials = CgCredentials()
        cache = cache or save
        if cache:
            profile_store = get_credentials_store(app_name=self.app_name)
            profile_store.set_credentials(DEFAULT_PROFILE_NAME, credentials)
            if save:
                profile_store.commit()
            credentials = profile_store.get_credentials(DEFAULT_PROFILE_NAME) or CgCredentials()
        if credentials is None or credentials.remember_me_cookie is None or credentials.cg_session_cookie is None:
            # Both cookies are required for the client to be considered logged in--enough CodinGame
            # endpoints require cgSession specifically that a rememberMe-only session isn't useful.
            self.credentials = None
            self.login_attempted = False
            self.codingamer_id = None
        else:
            # The codingamer ID is derived from the first 7 characters of the rememberMe cookie
            try:
                self.codingamer_id = int(credentials.remember_me_cookie[:7])
            except (ValueError, TypeError) as e:
                raise ValueError("Invalid rememberMe cookie format; cannot derive codingamer ID.") from e
            self.credentials = credentials
            self.login_attempted = True
        return credentials

    def clear_credentials(self, *, cache: bool = True, save: bool = True) -> None:
        """Clear the credentials for the client session, effectively logging out the client session.

           If cache is True (the default), the cached credentials will be cleared process-wide for the app_name associated with the
           client session. Ignored and treated as True if save is True.

           If save is True, the credentials will be cleared from the per-app private credentials file.

        """
        self.set_credentials(None, cache=cache, save=save)
        self.login_attempted = False

    def resolve_credentials(
                self,
                *,
                remember_me_token: str | None = None,
                cg_session_token: str | None = None,
                credentials: CgCredentials | None = None,
                force: bool = False,
            ) -> CgCredentials:
        """Resolve the current credentials for the client, with parameter and environment variable overrides.

        Resolution order:
            1. If force is False and credentials are already cached in the client, use those values.
            2. If non-null `remember_me_token` / `cg_session_token` are provided, use those values.
            3. If `credentials` is provided, use non-null token values from that object.
            4. check the `REMEMBER_ME_TOKEN_ENV_VAR` / `CG_SESSION_TOKEN_ENV_VAR` environment variables for overrides.
            5. If neither is provided and force is False, check the in-process cache for the app's credentials.
            6. If not in the cache, check the per-app private credentials file (which populates the cache on success).
            7. If none of the above are available, return an empty `CgCredentials()`

        The result of this function is not cached in the client; it is up to the caller to call `set_credentials()`
        if they want to cache the result.

        Args:
            remember_me_token: Optional override for the `rememberMe` cookie value.
            cg_session_token: Optional override for the `cgSession` cookie value.
            credentials: Optional `CgCredentials` object to use as the base for resolution.
            force: If True, ignore the in-process cache and reload from the credentials file.

        Returns:
            Resolved `CgCredentials` object, with parameter and environment variable overrides applied.
        """
        if not force and self.credentials is not None:
            credentials = self.credentials
        else:
            profile_store = get_credentials_store(app_name=self.app_name)
            if force:
                # Bypass the profile store's in-memory cache and re-read from persistent storage.
                profile_store.get_profile_store(DEFAULT_PROFILE_NAME).fetch(force=True)
            credentials = get_credentials_with_override(
                credentials=credentials,
                remember_me_token=remember_me_token,
                cg_session_token=cg_session_token,
                store=profile_store,
            )
        return credentials

    def is_logged_in(self) -> bool:
        """Return True if the client is logged in (i.e., has valid credentials), False otherwise."""
        return self.credentials is not None
