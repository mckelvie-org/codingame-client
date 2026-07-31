"""Async `fileupload` servlet endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiohttp
from json_data_types import JsonDict

from ....common.raw_client import CgFileUploadError, CgUploadFileResult
from ..cg_servlet import CgAsyncServlet, CgAsyncServletHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncFileUploadServletHelper(CgAsyncServletHelper["CgAsyncFileUploadServlet"]):
    """Helper methods for CgAsyncFileUploadServlet. Currently empty."""


class CgAsyncFileUploadServlet(CgAsyncServlet):
    """Async `fileupload` servlet endpoint. Uploads a file to the CodinGame servers.

       **File type is restricted--this is not a general-purpose blob store.** Confirmed live
       (2026-07-27): a plain-text file (content `b"hello...\n"`, `content_type="text/plain"`) is
       rejected with a `CgFileUploadError` (`error_type="UNSUPPORT_FILE_ERROR"`, message
       "Unsupported file: Format not supported"), while a valid PNG image (real PNG byte content,
       `content_type="image/png"`) succeeds. Both tests used matching, honest content and
       `content_type`--whether the server actually inspects file content/signature versus just
       trusting the declared `content_type` header is NOT verified either way. The `testImage`
       param name suggests images are the intended use case, consistent with this endpoint's
       real-world use for contribution cover images. Only these two data points are confirmed--the
       full set of accepted formats is undocumented and unexplored; treat any format other than
       common image types as unverified."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "fileupload")
        self.helper = CgAsyncFileUploadServletHelper(self)

    async def __call__(
                self,
                content: bytes | str,
                *,
                filename: str | Path | None = None,
                content_type: str = "application/octet-stream",
                params: JsonDict | None = None,
            ) -> CgUploadFileResult:
        """Upload a file to the CodinGame servers.

           Generates a multipart MIME POST request (via `CgAsyncRawClient.servlet_post`) to
           `https://www.codingame.com/servlet/fileupload` with the file content, metadata, and
           parameters, then parses the raw `{"result": [{...}]}` response into a
           `CgUploadFileResult`.

           Files that are successfully uploaded are assigned a globally unique ID by the CodinGame
           servers, which can be used to download the file later (see `CgAsyncFileServletServlet`)
           and can be provided to other APIs that accept file IDs. Presumably there is some kind
           of garbage collection on the server side if a file ID is not attached to another
           persistent resource, but the policy is not documented. In general, an uploaded file
           should be attached to a persistent resource (e.g., a contribution) as soon as possible.

        Args:
            content:      The content of the file to upload, as bytes or a string. If a string is
                          provided, it will be encoded as UTF-8.
            filename:     Optional filename to provide to the server. Provided back to the client
                          at download time in the Content-Disposition header. Only the final path
                          component is used. Defaults to "file.bin".
            content_type: The MIME type of the file. Provided back to the client at download time
                          in the Content-Type header. Defaults to "application/octet-stream".
            params:       Optional JsonDict of additional named parameters to provide to the
                          server. Documentation is sparse, but in current usage, the only
                          parameter that seems to be used is "testImage", which should be set to
                          true for image files. If not provided, defaults to `{"testImage": True}`.

        Returns:
            A CgUploadFileResult with the uploaded file's assigned ID and server-echoed metadata.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, or if the response is not a valid JSON dictionary or
                if the status code is not 2xx.
            CgFileUploadError:
                If the server accepts the HTTP request (200 OK) but rejects the file content
                itself--e.g. an unsupported format. Confirmed live: a plain-text file is rejected
                this way even though upload of e.g. PNG image content succeeds.
        """
        if params is None:
            params = {"testImage": True}
        if filename is None:
            filename = "file.bin"
        filename = Path(filename).name  # Only use the final path component
        if isinstance(content, str):
            content = content.encode("utf-8")
        params_text = json.dumps(params, separators=(",", ":"))

        form = aiohttp.FormData()
        form.add_field("file", content, filename=filename, content_type=content_type)
        form.add_field("data", params_text, content_type="application/json")

        raw_result = await self.client.servlet_post(
                self.client.CODINGAME_SERVLET_URL, self.servlet_name, data=form)
        result_list = cast("list[JsonDict]", raw_result["result"])
        entry = result_list[0]
        error = entry.get("error")
        if error is not None:
            error_dict = cast(JsonDict, error)
            raise CgFileUploadError(
                    cast(str, error_dict.get("type", "UNKNOWN_ERROR")),
                    cast(str, error_dict.get("message", "")),
                    field_name=cast(str, entry.get("fieldName", "")),
                    name=cast(str, entry.get("name", "")),
                    size=cast(int, entry.get("size", 0)),
                )
        return CgUploadFileResult.from_dict(entry)
