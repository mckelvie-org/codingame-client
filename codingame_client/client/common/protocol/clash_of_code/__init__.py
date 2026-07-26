"""
Protocol schema definitions for the ClashOfCode service.
"""

from __future__ import annotations

from ..schema import CgSolutionLanguage
from .schema import (
    CgClash,
    CgClashMode,
    CgClashPlayer,
    CgClashPlayerStatus,
    CgClashRank,
    CgClashType,
    CgTestSessionStatus,
)

__all__ = [
    "CgClash", "CgClashMode", "CgClashPlayer", "CgClashPlayerStatus", "CgClashRank",
    "CgClashType", "CgSolutionLanguage", "CgTestSessionStatus",
]
