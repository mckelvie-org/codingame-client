"""Async servlet endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cg_servlet import CgServlet, CgServletHelper
from .servlets.file_servlet import CgFileServletServlet, CgFileServletServletHelper
from .servlets.file_upload import CgFileUploadServlet, CgFileUploadServletHelper

if TYPE_CHECKING:
    from ..client import CgClient

__all__ = [
    "CgServlet",
    "CgServletHelper",
    "CgClient",
    "CgServlets",
    "CgFileServletServlet",
    "CgFileServletServletHelper",
    "CgFileUploadServlet",
    "CgFileUploadServletHelper",
]

class CgServlets:
    """
    Servlet endpoints for the async CodinGame client.

    An instance of this class is created on CgClient, giving users well-typed access to all
    servlet endpoints. Unlike a service (many named methods behind one shared endpoint URL), each
    servlet exposes exactly one operation via `__call__`. For example, to upload a file:

        async with CgClient() as client:
            result = await client.servlets.file_upload(content, filename="cover.png")
    """

    client: CgClient
    """The client through which endpoint requests are made."""

    # well-typed servlet endpoints
    file_upload: CgFileUploadServlet
    file_servlet: CgFileServletServlet

    def __init__(self, client: CgClient) -> None:
        self.client = client
        self.file_upload = CgFileUploadServlet(client)
        self.file_servlet = CgFileServletServlet(client)
