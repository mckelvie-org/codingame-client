"""
Definitions common to both the sync and async raw (JsonData) clients.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from pathlib import Path
from typing import Final, NamedTuple, cast

from json_data_types import JsonData, JsonDict

from ...common.dataclass_wizard_x import CatchAll, JSONWizardX
from ...common.typedefs import Self
from ...credentials.cg_credentials import CgCredentials, get_credentials_with_override
from ...version import __version__

__all__ = [
    "compute_content_hash",
    "CgDownloadFileResult",
    "CgUploadFileResult",
    "CgServletError",
    "CgFileUploadError",
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


class CgUploadFileResult(NamedTuple):
    """The well-typed result of a successful file upload--parsed from the raw `fileupload`
       servlet response, e.g. `{"result": [{"fieldName": "file", "name": "cover.png",
       "size": 250401, "id": 163935944975958}]}`."""

    id: int
    """The globally unique ID assigned to the uploaded file. Used to download the file later
       (see `CgDownloadFileResult.id`) or to reference it from other APIs that accept file IDs."""

    name: str
    """The filename as echoed back by the server; normally matches the `filename` provided at
       upload time."""

    size: int
    """The size of the uploaded file content, in bytes."""

    field_name: str
    """The multipart form field name the file was uploaded under. Always "file" in current usage."""

    @classmethod
    def from_dict(cls, d: JsonDict) -> Self:
        """Parse a `CgUploadFileResult` from a successful entry of a raw `fileupload` servlet
           response's `"result"` list. Assumes `d` is already known to be a successful entry
           (not an embedded per-file error--see `CgFileUploadError`); callers must check for that
           themselves before calling this."""
        return cls(
            id=cast(int, d["id"]),
            name=cast(str, d["name"]),
            size=cast(int, d["size"]),
            field_name=cast(str, d["fieldName"]),
        )


class CgServletError(Exception):
    """Base class for an embedded per-entry error returned by a servlet in an otherwise-successful
       (200 OK) response--i.e. an application-level error signaled inside the JSON body rather
       than via HTTP status, so it can't be caught as a `CgClientHttpError`.

       This is *not* a claim that all servlets share one common error response shape--currently
       only `fileupload` is known to work this way (see `CgFileUploadError`)--just the common
       subset of fields (`error_type`, `error_message`, `field_name`) that make sense to factor
       out if/when a second servlet turns out to follow the same pattern.
    """

    error_type: str
    """The server's error type code, e.g. "UNSUPPORT_FILE_ERROR"."""

    error_message: str
    """The server's human-readable error message, e.g. "Unsupported file: Format not supported"."""

    field_name: str
    """The form field name the error applies to, if applicable. Defaults to "" when not
       applicable or not provided by the server."""

    def __init__(self, error_type: str, error_message: str, *, field_name: str = "") -> None:
        self.error_type = error_type
        self.error_message = error_message
        self.field_name = field_name
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Build the exception's string message. Subclasses adding fields relevant to the error
           should override this to include them, rather than overriding `__init__` message
           construction directly."""
        return f"{self.error_type}: {self.error_message}"


class CgFileUploadError(CgServletError):
    """Raised when the `fileupload` servlet accepts the HTTP request itself (a 200 OK) but
       rejects the uploaded file's content--e.g. an unsupported format--returning an embedded
       error object in its response instead of a successful upload entry. Confirmed live (2026-07-27):
       uploading a plain-text file returns
       `{"result": [{"error": {"type": "UNSUPPORT_FILE_ERROR", "message": "Unsupported file: "
       "Format not supported"}, "fieldName": "file", "name": "...", "size": ...}]}`."""

    name: str
    """The filename that was rejected, as echoed back by the server."""

    size: int
    """The size of the rejected file content, in bytes."""

    def __init__(
                self,
                error_type: str,
                error_message: str,
                *,
                field_name: str = "",
                name: str,
                size: int,
            ) -> None:
        self.name = name
        self.size = size
        super().__init__(error_type, error_message, field_name=field_name)

    def _format_message(self) -> str:
        return f"{super()._format_message()} (file={self.name!r}, size={self.size})"


DEFAULT_HEADERS: dict[str, str] = {
        "User-Agent": (
            f"codingame-tools/{__version__} (+https://github.com/mckelvie-org/codingame-tools)"
        ),
        "Accept": "application/json, text/plain, */*",
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

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)
    """Unrecognized fields encountered when loading the error response, preserved."""

    message: str | None = None
    """The error message returned by the API."""


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

class CgRawClient(ABC):
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
    
    profile_name: str | None = None
    """The name of the profile to use for persistent credentials. Allows for multiple independent session profiles;
       e.g., if multiple CodinGame accounts are used. If None, defaults to the default profile. May
       be provided at construction or at authenticate() time."""

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
                profile_name: str | None = None,
                default_http_headers: dict[str, str] | None = None,
                app_name: str | None = None,
            ):
        """Create a CgRawClient.

        Args:
            profile_name: Optional name of the profile to use for persistent credentials. Allows
                          for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                          If None, defaults to the default profile. This parameter may be overridden at authenticate() time.
            app_name: Optional name of the application using the client. Used to allow different applications to have different
                      cached credentials in the same environment. If None, a default application name is used.
        """
        self.profile_name = profile_name
        self.app_name = app_name
        self.default_http_headers = default_http_headers or DEFAULT_HEADERS
        
    @abstractmethod
    def set_cookie(
                self,
                name: str,
                value: str | None = None,
                *,
                domain: str = "www.codingame.com",
            ) -> None:
        """Set a cookie for the client session.
           If value is None, the cookie will be deleted.
           
           This method must be implemented by subclasses, since the sync and async clients use different HTTP libraries.
        """
        ...
        

    def set_credentials(
                self,
                credentials: CgCredentials | None,
            ) -> CgCredentials:
        """Set the credentials for the client session.

           If credentials are provided, they will be used to authenticate/reauthenticate the client session.
           If not provided, empty credentials are used, effectively logging out the client session.

           The client is only considered logged in if both a rememberMe and a cgSession cookie are present;
           credentials with only one (or neither) are treated the same as no credentials at all. This is
           because enough CodinGame endpoints require cgSession specifically (not just rememberMe) that a
           partial session isn't useful in practice.
           
           The rememberMe and cgSession cookies are updated to match the credentials.
           
           Persistent credentials are not affected.

           Returns:
                The (deep-copied) credentials that are now cached. If there are no credentials, returns an empty CgCredentials() object.
        """
        if credentials is not None and (credentials.remember_me_cookie is None or credentials.cg_session_cookie is None):
            credentials = None
        if credentials is None:
            credentials = CgCredentials()
            # Both cookies are required for the client to be considered logged in--enough CodinGame
            # endpoints require cgSession specifically that a rememberMe-only session isn't useful.
            self.credentials = None
            self.login_attempted = False
            self.codingamer_id = None
            self.set_cookie("rememberMe", None)
            self.set_cookie("cgSession", None)
        else:
            # The codingamer ID is derived from the first 7 characters of the rememberMe cookie
            remember_me_cookie = credentials.remember_me_cookie
            cg_session_cookie = credentials.cg_session_cookie
            assert remember_me_cookie is not None and cg_session_cookie is not None
            try:
                self.codingamer_id = int(remember_me_cookie[:7])
            except (ValueError, TypeError) as e:
                raise ValueError("Invalid rememberMe cookie format; cannot derive codingamer ID.") from e
            self.credentials = credentials
            self.set_cookie("rememberMe", remember_me_cookie)
            self.set_cookie("cgSession", cg_session_cookie)
            self.login_attempted = True
            
        return credentials

    def clear_credentials(self) -> None:
        """Clear the credentials for the client session, effectively logging out the client session.

           Persistent credentials are not affected.
        """
        self.set_credentials(None)

    def resolve_credentials(
                self,
                *,
                profile_name: str | _Missing | None = MISSING,
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
            profile_name: Optional name of the profile to use for persistent credentials. Allows
                          for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                          If not provided or MISSING, defaults to the profile_name provided at client construction time.
                          If None, defaults to the default profile.
            remember_me_token: Optional override for the `rememberMe` cookie value.
            cg_session_token: Optional override for the `cgSession` cookie value.
            credentials: Optional `CgCredentials` object to use as the base for resolution.
            force: If True, ignore the in-process cache and reload from the credentials file.

        Returns:
            Resolved `CgCredentials` object, with parameter and environment variable overrides applied.
            If there are no valid credentials, returns an empty `CgCredentials()` object.
        """
        if not force and self.credentials is not None:
            credentials = deepcopy(self.credentials)
        else:
            if profile_name is MISSING:
                profile_name = self.profile_name
            credentials = get_credentials_with_override(
                profile_name=profile_name,
                credentials=credentials,
                remember_me_token=remember_me_token,
                cg_session_token=cg_session_token,
            )
        return credentials

    def is_logged_in(self) -> bool:
        """Return True if the client is logged in (i.e., has valid credentials), False otherwise."""
        return self.credentials is not None
