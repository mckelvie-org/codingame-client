"""
Protocol schema definitions for the CodinGamer service.
"""

from __future__ import annotations

from .schema import (
    CgCodingamePointsRankingDto,
    CgCodingamePointsStats,
    CgCodingamer,
    CgCodingamerFollower,
    CgRankHistoryEntry,
    CgXpThreshold,
)

__all__ = [
    "CgCodingamer", "CgCodingamerFollower", "CgRankHistoryEntry",
    "CgCodingamePointsRankingDto", "CgXpThreshold", "CgCodingamePointsStats",
]
