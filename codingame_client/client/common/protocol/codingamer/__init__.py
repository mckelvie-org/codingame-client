"""
Protocol schema definitions for the CodinGamer service.
"""

from __future__ import annotations

from .schema import (
    CgCodingamePointsRankingDto,
    CgCodingamePointsStats,
    CgCodingamer,
    CgRankHistoryEntry,
    CgXpThreshold,
)

__all__ = [
    "CgCodingamer", "CgRankHistoryEntry", "CgCodingamePointsRankingDto",
    "CgXpThreshold", "CgCodingamePointsStats",
]
