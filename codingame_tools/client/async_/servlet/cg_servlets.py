"""Async servlet endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cg_servlet import CgAsyncServlet, CgAsyncServletHelper
from .servlets.file_servlet import CgAsyncFileServletServlet, CgAsyncFileServletServletHelper
from .servlets.file_upload import CgAsyncFileUploadServlet, CgAsyncFileUploadServletHelper

if TYPE_CHECKING:
    from ..client import CgAsyncClient

__all__ = [
    "CgAsyncServlet",
    "CgAsyncServletHelper",
    "CgAsyncClient",
    "CgAsyncServlets",
    "CgAsyncFileServletServlet",
    "CgAsyncFileServletServletHelper",
    "CgAsyncFileUploadServlet",
    "CgAsyncFileUploadServletHelper",
]

class CgAsyncServlets:
    """
    Servlet endpoints for the async CodinGame client.

    An instance of this class is created on CgAsyncClient, giving users well-typed access to all
    servlet endpoints. Unlike a service (many named methods behind one shared endpoint URL), each
    servlet exposes exactly one operation via `__call__`. For example, to upload a file:

        async with CgAsyncClient() as client:
            result = await client.servlets.file_upload(content, filename="cover.png")
    """

    client: CgAsyncClient
    """The client through which endpoint requests are made."""

    # well-typed servlet endpoints
    file_upload: CgAsyncFileUploadServlet
    file_servlet: CgAsyncFileServletServlet

    def __init__(self, client: CgAsyncClient) -> None:
        self.client = client
        self.file_upload = CgAsyncFileUploadServlet(client)
        self.file_servlet = CgAsyncFileServletServlet(client)
