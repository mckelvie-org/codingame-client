"""Async `fileservlet` servlet endpoint."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

import aiohttp

from ....common.raw_client import CgDownloadFileResult
from ..cg_servlet import CgAsyncServlet, CgAsyncServletHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncFileServletServletHelper(CgAsyncServletHelper["CgAsyncFileServletServlet"]):
    """Helper methods for CgAsyncFileServletServlet. Currently empty."""


class CgAsyncFileServletServlet(CgAsyncServlet):
    """Async `fileservlet` servlet endpoint. Downloads a file from the CodinGame servers."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "fileservlet")
        self.helper = CgAsyncFileServletServletHelper(self)

    async def __call__(
                self,
                id: int,
                format: str | None = None,
                timestamp: datetime | None = None,
                *,
                require_login: bool = True,
            ) -> CgDownloadFileResult:
        """Download a file from the CodinGame servers.

           Generates a GET request (via `CgAsyncRawClient.servlet_get_bytes`) to
           `https://static.codingame.com/servlet/fileservlet?id={id}&format={format}&timestamp={timestamp}`,
           then parses the response's content, content type, and Content-Disposition filename (if
           any) into a `CgDownloadFileResult`.

        Args:
            id:        The globally unique ID of the file to download, as provided by the server
                       at upload time (see `CgAsyncFileUploadServlet`).
            format:    Optional format string to request a specific format of the file. If not
                       provided, the server returns the file in its original format.
            timestamp: Optional timestamp to request a specific version of the file. If not
                       provided, the server returns the latest version.
            require_login:
                       If True (the default), the session must be logged in. If False, the
                       request is made with whatever credentials (if any) are already attached to
                       the session--some files are publicly downloadable and don't need a login at
                       all, so this allows the server to decide (via a 401/403) rather than always
                       requiring one up front.

        Returns:
            A CgDownloadFileResult with the file's content, content type, and filename (if any).

        Raises:
            CgAuthenticationError:
                If require_login is True and the session is not authenticated and cannot
                implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs.
        """
        params: dict[str, str] = {"id": str(id)}
        if format:
            params["format"] = format
        if timestamp:
            # The timestamp in the URL is interpreted as milliseconds since the epoch.
            params["timestamp"] = str(int(timestamp.timestamp() * 1000))
        content, response = await self.client.servlet_get_bytes(
                self.client.CODINGAME_STATIC_SERVLET_URL, self.servlet_name, params,
                require_login=require_login)
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
