"""
Async-only client for the CodinGame API.
"""

from __future__ import annotations

from .client import CgAsyncClient
from .raw_client import CgAsyncRawClient

__all__ = [
    "CgAsyncClient",
    "CgAsyncRawClient",
]
