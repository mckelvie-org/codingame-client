"""Servlet endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from ..client import CgAsyncClient

__all__ = [
    "CgAsyncServlet",
    "CgAsyncServletHelper",
]


class CgAsyncServlet:
    """Base class for a servlet endpoint.

       Unlike a `CgAsyncService` (which multiplexes many named RPC-style methods behind a single
       shared JSON endpoint), a servlet exposes exactly one operation, reached via its own
       dedicated URL (e.g. `https://www.codingame.com/servlet/fileupload`)--there is no shared
       request-dispatch mechanism to factor out here the way `service_request*` does for
       services. Concrete subclasses implement that one operation as `__call__`, so a servlet is
       invoked as `client.servlets.file_upload(...)` rather than via a named method.
    """

    client: CgAsyncClient

    servlet_name: str
    """The servlet's own name, i.e. the final path component of its URL (e.g. "fileupload")."""

    def __init__(self, client: CgAsyncClient, servlet_name: str) -> None:
        self.client = client
        self.servlet_name = servlet_name


TServlet = TypeVar("TServlet", bound=CgAsyncServlet)


class CgAsyncServletHelper(Generic[TServlet]):
    """Base class for a servlet's helper object. See `CgAsyncServiceHelper`--same model, applied
       to servlets: higher-level convenience methods layered on top of a servlet's own `__call__`,
       never doing anything a caller couldn't already do themselves.

       Generic over `TServlet` (bound to `CgAsyncServlet`) for the same reason
       `CgAsyncServiceHelper` is generic over `TService`--see there for details.
    """

    servlet: TServlet
    """The servlet endpoint instance this helper is attached to."""

    def __init__(self, servlet: TServlet) -> None:
        self.servlet = servlet

    @property
    def client(self) -> CgAsyncClient:
        """The client through which the owning servlet makes requests."""
        return self.servlet.client
