"""
Protocol schema definitions for the Puzzle service.
"""

from __future__ import annotations

from ..last_activities import CgLastActivityPuzzle, CgPuzzleFeedback, CgPuzzleTopicNode
from ..schema import CgSolutionLanguage
from .schema import (
    CgFollowingCodingamer,
    CgFollowingPuzzleProgress,
    CgLanguageCertification,
    CgPuzzleMinimalProgress,
    CgPuzzleOfTheWeek,
    CgSolvedPuzzlesByLanguage,
)

__all__ = [
    "CgFollowingCodingamer", "CgFollowingPuzzleProgress", "CgLanguageCertification",
    "CgLastActivityPuzzle", "CgPuzzleFeedback", "CgPuzzleMinimalProgress", "CgPuzzleOfTheWeek",
    "CgPuzzleTopicNode", "CgSolutionLanguage", "CgSolvedPuzzlesByLanguage",
]
