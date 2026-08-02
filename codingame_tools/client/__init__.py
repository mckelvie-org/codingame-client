"""
Client for the CodinGame API.
"""

from __future__ import annotations

from .client import CgClient
from .common.raw_client import CgRawClient

__all__ = [
    "CgClient",
    "CgRawClient",
]
