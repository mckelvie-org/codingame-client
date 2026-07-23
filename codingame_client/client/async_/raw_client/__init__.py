"""
Async-only low-level (JsonData) client.
"""

from __future__ import annotations

import contextlib
import http.cookies
import json
import re
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import cast

import aiohttp
from json_data_types import JsonData, JsonDict, JsonList

from ....common.typedefs import Never, Self, override
from ....credentials.cg_credentials import CgCredentials
from ...common.raw_client import (
    MISSING,
    CgAuthenticationError,
    CgClientHttpError,
    CgDownloadFileResult,
    CgRawClient,
    _Missing,
)

__all__ = [
]

class CgAsyncClientHttpError(CgClientHttpError):
    """Async-only client HTTP error. Adds the aiohttp response objeect to the exception for debugging purposes."""
    
    response: aiohttp.ClientResponse | None
    
    def __init__(
                self,
                message: str | None = None,
                *,
                response: aiohttp.ClientResponse | None = None,
                content: JsonData | bytes | None | _Missing = MISSING,
                status_code: int | None = None,
            ):
        """Create a CgAsyncClientHttpError, providing available context.
        
        Args:
            message:      Optional error message. If not provided, will use the status code's default phrase
            response:     Optional aiohttp.ClientResponse object. If provided, will be used to determine the status
                          code and content if not provided.
            content:      Optional decoded content of the response. If not provided, will attempt to use already
                          cached content bytes read from the response, if provided. If not provided and no cached content is
                          available, will be None.
            status_code:  Optional status code. If not provided, will attempt to read from the response if provided, or 200 otherwise.
        """
        if status_code is None:
            status_code = response.status if response is not None else 200
        if content is MISSING:
            content = None
            if response is not None:
                with contextlib.suppress(Exception):
                    # This is invasive, but we can't await in a constructor, so we try to read the cached content if available.
                    # it's only used for debugging/descriptive purposes anyway.
                    content = response._body
        super().__init__(message, status_code=status_code, content=content)
        self.response = response
        
    @classmethod
    def normalize(
                cls,
                e: aiohttp.ClientResponseError,
                *,
                content: JsonData | bytes | None | _Missing = MISSING,
                response: aiohttp.ClientResponse | None=None,
            ) -> Self:
        """Normalize an exception raised by aiohttp into a CgAsyncClientHttpError, preserving the status code and message.
        Args:
            e:            The original aiohttp.ClientResponseError exception.
            content:      Optional decoded content of the response. If not provided, will attempt to use already
                          cached content bytes read from the response, if provided. If not provided and no cached content is
                          available, will be None.
            response:     Optional aiohttp.ClientResponse object. If provided, will be used to determine the status code
                          and content if not provided.
        """
        return cls(e.message, response=response, content=content, status_code=e.status)


class CgAsyncRawClient(CgRawClient):
    """Async-only low-level (JsonData) client."""

    session: aiohttp.ClientSession
    """The aiohttp session used for requests."""
    
    
    _trace_configs: list[aiohttp.TraceConfig]
    
    def __init__(
                self,
                *,
                profile_name: str | None = None,
                default_http_headers: dict[str, str] | None = None,
                trace_configs: list[aiohttp.TraceConfig] | None = None,
                app_name: str | None = None,
            ):
        """Create a CgAsyncRawClient.

        Args:
            profile_name: Optional name of the profile to use for persistent credentials. Allows
                          for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                          If None, defaults to the default profile. This parameter may be overridden at authenticate() time.
            default_http_headers:
                          Optional default HTTP headers for requests. If None, default headers are used.
            trace_configs: Optional list of aiohttp.TraceConfig for the session. If None, an empty list is used.
            app_name: Optional name of the application using the client. Used to allow different applications to have different
                      cached credentials in the same environment. If None, a default application name is used.
        """
        super().__init__(profile_name=profile_name, default_http_headers=default_http_headers, app_name=app_name)
        if trace_configs is None:
            trace_configs = []
        self._trace_configs = list(trace_configs)
        self.session = aiohttp.ClientSession(
            headers=self.default_http_headers,
            trace_configs=self._trace_configs,
        )
        
    def __enter__(self) -> Never:
        raise NotImplementedError("__enter__ not supported for CgAsyncRawClient--use __aenter__ instead.")
    
    def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None
            ) -> Never:
        raise NotImplementedError("__exit__ not supported for CgAsyncRawClient--use __aexit__ instead.")
    
    async def __aenter__(self) -> CgAsyncRawClient:
        await self.session.__aenter__()
        return self
    
    async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: TracebackType | None
            ) -> bool | None:
        # aiohttp.ClientSession.__aexit__ always returns None (never suppresses the exception).
        await self.session.__aexit__(exc_type, exc_val, exc_tb)
        return None
    
    async def close(self) -> None:
        """Close the client session."""
        await self.session.close()
    
    @override
    def set_cookie(
                self,
                name: str,
                value: str | None = None,
                *,
                domain: str = "www.codingame.com",
            ) -> None:
        """Set a cookie for the client session.
        
           The cookie will be sent with all requests to the specified domain for the remainder
           of the client session.
           
           If value is None, the cookie will be deleted.
        """
        if value is None:
            self.session.cookie_jar.clear(predicate=lambda morsel: morsel.key == name and morsel["domain"] == domain)
        else:
            cookie = http.cookies.SimpleCookie()
            cookie[name] = value
            morsel: http.cookies.Morsel[str] = cookie[name]
            morsel["domain"] = domain
            morsel["path"] = "/"
            self.session.cookie_jar.update_cookies(cookie)

    async def validate_credentials(self) -> None:
        """Verifies that current client credentials are valid by making a test request to the CodinGame API.
           Raises CgAuthenticationError if the credentials are invalid or if the request fails for any reason.

           The client session must be logged in (i.e., have valid credentials) before calling this method.

           This method can be overridden in subclasses to perform a more specific test request, if desired.

           Uses Notification/findUnreadNotifications as the test request rather than
           CodinGamer/findCodinGamerPublicInformations, since the latter is public and succeeds even
           when unauthenticated--it would not actually detect invalid/expired credentials. findUnreadNotifications
           requires authentication (it returns 422 when called without a valid session), and empirically appears
           to be side-effect-free (repeated calls return identical results, including `seenDate`).
        """
        if self.credentials is None:
            raise CgAuthenticationError("Client session is not logged in.")
        # Perform a test request to verify credentials
        try:
            codingamer_id = self.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError("Client session is not logged in.")
            await self.service_request_to_list("Notification", "findUnreadNotifications", [ codingamer_id ])
        except CgAsyncClientHttpError as e:
            raise CgAuthenticationError("Invalid client credentials.") from e
            
    async def authenticate(
                self,
                *,
                profile_name: str | _Missing | None = MISSING,
                remember_me_token: str | None = None,
                cg_session_token: str | None = None,
                credentials: CgCredentials | None = None,
                force: bool = False,
                require_credentials: bool = False,
                validate: bool = False
            ) -> None:
        """Authenticate the client session, at one of three independent strictness levels
           (`require_credentials` x `validate`; a fourth level, no authentication at all, is
           available by simply not calling this method--see `service_request`'s `require_login`):

               require_credentials=False, validate=False (the default): best-effort. Resolves
                   credentials and applies them to the session if available, but does not raise
                   if none are available--the session is simply left unauthenticated.
               require_credentials=True,  validate=False: login required. Raises
                   CgAuthenticationError if no credentials are available. Does not check that
                   they are still valid/unexpired.
               require_credentials=True,  validate=True:  validated login required. Raises if no
                   credentials are available, and separately raises if they fail a live
                   validation check against the server (e.g. expired/revoked).

           (`require_credentials=False, validate=True` is also accepted: best-effort resolution,
           and if that happens to find credentials, they are validated too; if it doesn't, this
           is still not an error.)

        Resolution order:
            1. If force is False and credentials are already cached in the client, do nothing.
            2. If non-null `remember_me_token` / `cg_session_token` are provided, use those values.
            3. If `credentials` is provided, use non-null token values from that object.
            4. check the `REMEMBER_ME_TOKEN_ENV_VAR` / `CG_SESSION_TOKEN_ENV_VAR` environment variables for overrides.
            5. If neither is provided and force is False, check the in-process cache for the app's credentials.
            6. If not in the cache, check the per-app private credentials file (which populates the cache on success).
            7. If none of the above are available, return an empty `CgCredentials()`

        Args:
            profile_name: Optional name of the profile to use for persistent credentials. Allows
                          for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                          If not provided or MISSING, the profile provided at client construction time is used.
                          If None, defaults to the default profile.
            remember_me_token: Optional override for the `rememberMe` cookie value.
            cg_session_token: Optional override for the `cgSession` cookie value.
            credentials: Optional `CgCredentials` object to use as the base for resolution.
            force: If True, ignore the client session and in-process cache and reload from the credentials file.
            require_credentials: If True, raise CgAuthenticationError if no usable credentials could
                          be resolved. If False (the default), silently leave the session unauthenticated.
            validate: If True, verify that the resolved credentials are valid by making a test request.
                          Has no effect if no credentials were resolved and `require_credentials` is False.
        """
        try:
            self.login_attempted = True
            if not force and self.credentials is not None:
                return
            resolved_credentials = self.resolve_credentials(
                profile_name=profile_name,
                remember_me_token=remember_me_token,
                cg_session_token=cg_session_token,
                credentials=credentials,
                force=force
            )
            have_credentials = (
                resolved_credentials.remember_me_cookie is not None
                and resolved_credentials.cg_session_cookie is not None
            )
            if not have_credentials:
                if require_credentials:
                    raise CgAuthenticationError(
                            "Both a rememberMe and a cgSession cookie are required to log in; "
                            "only one (or neither) was available."
                        )
                return
            self.set_credentials(resolved_credentials)
            if validate:
                await self.validate_credentials()
        except Exception:
            self.clear_credentials()
            raise
            
    async def require_authenticate(self) -> None:
        """Ensure that the client session is logged in (i.e., has both a rememberMe and a cgSession
           cookie--see `set_credentials` for why both are required). Implicitly log in if possible.
           If not, raise CgAuthenticationError."""
        if self.credentials is None and not self.login_attempted:
            await self.authenticate(require_credentials=True)
        if self.credentials is None:
            raise CgAuthenticationError()

    async def get_json_data_response(self, response: aiohttp.ClientResponse) -> JsonData:
        """Get a JSON-decoded response from an aiohttp response, raising CgAsyncClientHttpError if the
           response could not be decoded at all or if the status code is not 2xx.

           Unlike a strict JSON-RPC-style API, CodinGame's services may return any JSON-serializable
           value at the top level, not just an object--e.g., a bare array, or a bare `null` for some
           endpoints when unauthenticated. This method does not attempt to distinguish a JSON string
           value from equivalent raw (non-JSON) text content, nor a JSON `null` from an empty/missing
           body--both are represented the same way in the returned value.

           Returns:
               The JSON-decoded data: a dict, list, str, int, float, bool, or None.

           Raises:
               CgAsyncClientHttpError:
                   If a transport error occurs, if the response content could not be decoded at all,
                   or if the status code is not 2xx.
        """

        # Note here that we attempt to decode the response as JSON even if the status code is not 2xx,
        # because some endpoints return JSON error messages with non-2xx status codes. The content will be included in the
        # raised CgAsyncClientHttpError for debugging purposes, and so that the caller can translate the error into a
        # more specific exception if desired.
        content: JsonData | bytes | None = None

        try:
            try:
                # First, we try to decode the response as JSON. If it fails, we try to read it as text or bytes.
                content = cast(JsonData, await response.json())
            except aiohttp.ContentTypeError as not_json_error:
                # Content-Type was not application/json, so we try to read the response as text or bytes.
                try:
                    content = await response.text()
                    # In some contexts, codingame does not properly supply a content-type header,
                    # so we try to parse the response as json anyway.
                    if response.content_type == "application/octet-stream":
                        with contextlib.suppress(json.JSONDecodeError):
                            content = cast(JsonData, json.loads(content))
                except Exception:
                    # content is neither JSON nor text, so we try to read it as bytes.
                    try:
                        content = await response.read()
                    except Exception:
                        # Could not fetch content, so we leave it as None and raise an error.
                        content = None
                        # before raising our own error, we try to raise the original error to get the correct status code and message.
                        response.raise_for_status()
                        ctype = response.headers.get(aiohttp.hdrs.CONTENT_TYPE, "<unspecified>").lower()
                        raise CgAsyncClientHttpError(
                                f"Unable to read response content in response (Content-Type: {ctype!r})",
                                response=response,
                                content=content
                            ) from not_json_error
            # at this point, content is decoded as best we can--either JSON-decoded data, a string, bytes, or None. It will
            # be included in the raised CgAsyncClientHttpError if we raise one.
            response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            raise CgAsyncClientHttpError.normalize(e, content=content, response=response) from e
        if isinstance(content, (bytes, bytearray, memoryview)):
            # Raw bytes are not valid JsonData; this means we couldn't decode the content as JSON or text.
            raise CgAsyncClientHttpError(
                    f"Unable to decode response content as JSON or text (Content-Type: {response.content_type!r})",
                    response=response,
                    content=content
                )
        if content is None:
            # None is not valid JsonData; this means we couldn't decode the content as JSON or text.
            raise CgAsyncClientHttpError(
                    f"Unable to decode response content (Content-Type: {response.content_type!r})",
                    response=response,
                    content=content
                )
        return content

    async def get_json_dict_response(self, response: aiohttp.ClientResponse) -> JsonDict:
        """Like `get_json_data_response`, but additionally requires the decoded content to be a JSON dict.

           Convenience wrapper for the common case where an endpoint is known to always return a
           JSON object on success.

           Returns:
               The JSON-decoded dictionary.

           Raises:
               CgAsyncClientHttpError:
                   If a transport error occurs, if the response content could not be decoded at all,
                   if the status code is not 2xx, or if the decoded content is not a dict.
        """
        content = await self.get_json_data_response(response)
        if not isinstance(content, dict):
            raise CgAsyncClientHttpError(
                    f"Invalid response type: expected a JSON dictionary, got {type(content).__name__}",
                    response=response,
                    content=content
                )
        return content

    async def get_json_list_response(self, response: aiohttp.ClientResponse) -> JsonList:
        """Like `get_json_data_response`, but additionally requires the decoded content to be a JSON list.

           Convenience wrapper for the common case where an endpoint is known to always return a
           JSON array on success.

           Returns:
               The JSON-decoded list.

           Raises:
               CgAsyncClientHttpError:
                   If a transport error occurs, if the response content could not be decoded at all,
                   if the status code is not 2xx, or if the decoded content is not a list.
        """
        content = await self.get_json_data_response(response)
        if not isinstance(content, list):
            raise CgAsyncClientHttpError(
                    f"Invalid response type: expected a JSON list, got {type(content).__name__}",
                    response=response,
                    content=content
                )
        return content

    async def _prepare_service_request(
                self,
                service_name: str,
                func_name: str,
                args: list[JsonData] | None,
                require_login: bool,
            ) -> tuple[str, list[JsonData]]:
        """Shared setup for `service_request`/`service_request_to_dict`/`service_request_to_list`:
           normalizes `args`, builds the endpoint URL, and ensures authentication if required."""
        if args is None:
            args = []
        endpoint_url = f"{self.CODINGAME_SERVICES_URL}{service_name}/{func_name}"
        if require_login:
            await self.require_authenticate()
        return endpoint_url, args

    async def service_request(
                self,
                service_name: str,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> JsonData:
        """Make an API request to a CodinGame service endpoint, returning its JSON-decoded response.

           This is the most common type of request made to the CodinGame API. It is used for most endpoints,
           except for file uploads and downloads.

           Generates a POST request to the URL https://www.codingame.com/services/{service_name}/{func_name}
           with a JSON body of `args`.

           In general, the session must be authenticated.

           This is a low-level method that does not distinguish between normal responses and error responses,
           and does not assume the response is a JSON object--some endpoints return a bare array, or a bare
           `null`, depending on the service and function called.

            Args:
                service_name: The name of the CodinGame service; e.g., "Vote", or "Contribution".
                func_name:    The name of the function to call within the service; e.g., "findContribution".
                args:         A list of JsonData positional arguments to pass to the function.
                require_login:
                              If True (the default), the session must be logged in (i.e., have both a
                              rememberMe and a cgSession cookie). If False, the request will be made
                              without requiring authentication, for endpoints that are genuinely public.

            Returns:
                The JSON-decoded response data. May be a successful response or an error response,
                depending on the service and function called.

            Raises:
                CgAuthenticationError:
                    If the session is not authenticated and cannot implicitly login.
                CgAsyncClientHttpError:
                    If a transport error occurs, if the response content could not be decoded at all,
                    or if the status code is not 2xx.
        """
        endpoint_url, args = await self._prepare_service_request(service_name, func_name, args, require_login)
        async with self.session.post(endpoint_url, json=args) as response:
            result = await self.get_json_data_response(response)
        return result

    async def service_request_to_dict(
                self,
                service_name: str,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> JsonDict:
        """Like `service_request`, but additionally requires (and type-checks) that the response is a JSON dict.

           See `service_request` for details on the request; see `get_json_dict_response` for details on
           the additional error condition.

            Raises:
                CgAuthenticationError:
                    If the session is not authenticated and cannot implicitly login.
                CgAsyncClientHttpError:
                    If a transport error occurs, if the response content could not be decoded at all,
                    if the status code is not 2xx, or if the decoded content is not a dict.
        """
        endpoint_url, args = await self._prepare_service_request(service_name, func_name, args, require_login)
        async with self.session.post(endpoint_url, json=args) as response:
            result = await self.get_json_dict_response(response)
        return result

    async def service_request_to_list(
                self,
                service_name: str,
                func_name: str,
                args: list[JsonData] | None = None,
                *,
                require_login: bool = True
            ) -> JsonList:
        """Like `service_request`, but additionally requires (and type-checks) that the response is a JSON list.

           See `service_request` for details on the request; see `get_json_list_response` for details on
           the additional error condition.

            Raises:
                CgAuthenticationError:
                    If the session is not authenticated and cannot implicitly login.
                CgAsyncClientHttpError:
                    If a transport error occurs, if the response content could not be decoded at all,
                    if the status code is not 2xx, or if the decoded content is not a list.
        """
        endpoint_url, args = await self._prepare_service_request(service_name, func_name, args, require_login)
        async with self.session.post(endpoint_url, json=args) as response:
            result = await self.get_json_list_response(response)
        return result

    async def upload_file(
                self,
                content: bytes | str,
                *,
                filename: str | Path | None = None,
                content_type: str = "application/octet-stream",
                params: JsonDict | None = None,
            ) -> JsonDict:
        """Uploads a file to the CodinGame servers, returning the response data as a json-decoded dictionary.
        
           Generates a multipart MIME POST request to the URL https://www.codingame.com/servlet/fileupload with
           the file content, metadata, and parameters.
           
           Files that are successfully uploaded are assigned a globally unique ID by the CodinGame servers,
           which can be used to download the file later and can be provided to other APIs that accept file IDs.
           Presumably there is some kind of garbage collection on the server side if a file ID is not attached
           to another persistent resource, but the policy is not documented. In general, an uploaded
           file should be attached to a persistent resource (e.g., a contribution) as soon as possible.
        
           This is a low-level method that does not distinguish between normal responses and error responses, provided
           they are a valid JsonDict.
           
            Args:
                content:      The content of the file to upload, as bytes or a string.
                              If a string is provided, it will be encoded as UTF-8.
                filename:     Optional filename to provide to the server. This filename will be provided
                              back to the client at download time in the Content-Disposition header.
                              Only the final path component is used. If not provided, defaults to "file.bin".
                content_type: The MIME type of the file. This content type will be provided back to the
                              client at download time in the Content-Type header. Defaults to "application/octet-stream".
                params:       Optional JsonDict of additional named parameters to provide to the server.
                              Documentation is sparse, but in current usage, the only parameter that seems to be used is "testImage",
                              which should be set to true for image files.
                              If not provided, defaults to { "testImage": true }.
                
            Returns:
                A JsonDict containing the response data. May be a successful response or an error response,
                depending on the service and function called. If successful, looks like:
                    {
                        "result": [
                            {
                                "fieldName": "file",
                                "name": "cover.png",
                                "size": 250401,
                                "id": 163935944975958
                            }
                        ]
                    }            
                
            Raises:
                CgAuthenticationError:
                    If the session is not authenticated and cannot implicitly login.
                CgAsyncClientHttpError:
                    If a transport error occurs, or if the response is not a valid JSON dictionary
                    or if the status code is not 2xx.
        """
        if params is None:
            params = {"testImage": True}
        if filename is None:
            filename = "file.bin"
        filename = Path(filename).name  # Only use the final path component
        if isinstance(content, str):
            content = content.encode("utf-8")
        params_text = json.dumps(params, separators=(",", ":"))
        endpoint_url = f"{self.CODINGAME_SERVLET_URL}/fileupload"

        form = aiohttp.FormData()
        form.add_field("file", content, filename=filename, content_type=content_type)
        form.add_field("data", params_text, content_type="application/json")

        await self.require_authenticate()
        async with self.session.post(endpoint_url, data=form) as response:
            result = await self.get_json_dict_response(response)
        return result
        
    async def download_file(
            self,
            id: int,
            format: str | None = None,
            timestamp: datetime |None = None,
            *,
            require_login: bool = True,
        ) -> CgDownloadFileResult:
        """Downloads a file from the CodinGame servers, returning a tuple of (file_bytes, content_type).

        Generates a GET request to the URL https://static.codingame.com/servlet/fileservlet?id={id}&format={format}&timestamp={timestamp}

        Args:
            id:        The globally unique ID of the file to download, as provided by the server at upload time.
            format:    Optional format string to request a specific format of the file. If not provided, the server
                       will return the file in its original format.
            timestamp: Optional timestamp to request a specific version of the file. If not provided, the server will
                       return the latest version of the file.
            require_login:
                       If True (the default), the session must be logged in. If False, the request is made
                       with whatever credentials (if any) are already attached to the session--some files
                       are publicly downloadable and don't need a login at all, so this allows the server to
                       be the one to decide (via a 401/403) rather than always requiring it up front.

        Returns:
            A CgDownloadFileResult object containing the file bytes, content type, and filename (if provided by the server).
        Raises:
            CgAuthenticationError:
                If require_login is True and the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs
        """
        url = f"{self.CODINGAME_STATIC_SERVLET_URL}/fileservlet?id={id}"
        if format:
            url += f"&format={format}"
        if timestamp:
            # The timestamp in the URL is interpreted as milliseconds since the epoch.
            ms_timestamp = int(timestamp.timestamp() * 1000)
            url += f"&timestamp={ms_timestamp}"
        if require_login:
            await self.require_authenticate()
        async with self.session.get(url) as response:
            try:
                response.raise_for_status()
                content = await response.read()
                content_type = response.headers.get(aiohttp.hdrs.CONTENT_TYPE, "application/octet-stream").lower()
                disposition = response.headers.get(aiohttp.hdrs.CONTENT_DISPOSITION)
                filename: str | None = None
                if disposition:
                    # Extract filename from Content-Disposition header
                    # TODO: Make this more robust
                    match = re.search(r'filename="([^"]+)"', disposition)
                    if match:
                        filename = match.group(1)
                return CgDownloadFileResult.create(id=id, content=content, content_type=content_type, filename=filename)
            except aiohttp.ClientResponseError as e:
                raise CgAsyncClientHttpError.normalize(e, content=None, response=response) from e
    
