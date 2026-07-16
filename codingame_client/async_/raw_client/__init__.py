"""
Async-only low-level (JsonData) client.
"""

from __future__ import annotations

import aiohttp

__all__ = [
]

DEFAULT_HEADERS: dict[str, str] = {
        "User-Agent": (
            f"codingame-client/{0.1.0} (+https://github.com/mckelvie-org/codingame-client)"
            "(https://github.com/takos22/codingame)"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }
    
class AsyncRawClient:
    """Async-only low-level (JsonData) client."""

    _session: aiohttp.ClientSession
    """The aiohttp session used for requests."""
    
    _http_headers: dict[str, str]
    """The HTTP headers used for requests."""
    
    
    def __init__(self):
        self._session = aiohttp.ClientSession()
        self._http_headers = {
            "User-Agent": "CodinGameClient/1.0",
            "Accept": "application/json",
        }
