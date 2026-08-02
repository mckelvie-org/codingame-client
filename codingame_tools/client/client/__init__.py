"""
Async well-typed (dataclass-based) client for the CodinGame API.
"""

from __future__ import annotations

import aiohttp

from ...settings import CgSettings
from ..common.raw_client import CgRawClient
from ..service.cg_services import CgServices
from ..servlet.cg_servlets import CgServlets

__all__ = [
    "CgClient",
]

class CgClient(CgRawClient):
    """Async client with well-typed (dataclass-based) methods for specific CodinGame API endpoints,
       layered on top of the generic, schema-agnostic `CgRawClient`."""

    services: CgServices
    """Accessor for all well-typed service endpoints, e.g. `client.services.codingamer.find_codingame_points_stats_by_handle(...)`."""

    servlets: CgServlets
    """Accessor for all well-typed servlet endpoints, e.g. `client.servlets.file_upload(...)`."""

    def __init__(
                self,
                *,
                profile_name: str | None = None,
                default_http_headers: dict[str, str] | None = None,
                trace_configs: list[aiohttp.TraceConfig] | None = None,
                app_name: str | None = None,
                settings: CgSettings | None = None,
            ):
        """Create a CgClient.

        Args:
            profile_name: Optional name of the profile to use for persistent credentials. Allows
                          for multiple independent session profiles; e.g., if multiple CodinGame accounts are used.
                          If None, the default profile name is resolved from `settings` (see below).
                          This parameter may be overridden at authenticate() time.
            default_http_headers:
                          Optional default HTTP headers for requests. If None, default headers are used.
            trace_configs: Optional list of aiohttp.TraceConfig for the session. If None, an empty list is used.
            app_name: Optional name of the application using the client. Used to allow different applications to have different
                      cached credentials in the same environment. If None, a default application name is used.
            settings: Optional CgSettings to resolve the default profile name from, used only when
                      `profile_name` is None--see `CgRawClient.__init__` for the resolution
                      details. The `CgConfig` is not a separate parameter since it's already
                      reachable as `settings.config`.
        """
        super().__init__(
                profile_name=profile_name,
                default_http_headers=default_http_headers,
                trace_configs=trace_configs,
                app_name=app_name,
                settings=settings,
            )
        self.services = CgServices(self)
        self.servlets = CgServlets(self)
