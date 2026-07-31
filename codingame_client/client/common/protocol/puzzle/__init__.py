"""
Protocol schema definitions for the Puzzle service.
"""

from __future__ import annotations

from ..last_activities import CgLastActivityPuzzle, CgPuzzleFeedback, CgPuzzleTopicNode
from ..schema import CgSolutionLanguage
from .schema import (
    CgFollowingCodingamer,
    CgFollowingPuzzleProgress,
    CgGeneratedPuzzleSession,
    CgLanguageCertification,
    CgPuzzleMinimalProgress,
    CgPuzzleOfTheWeek,
    CgSolvedPuzzlesByLanguage,
)

__all__ = [
    "CgFollowingCodingamer", "CgFollowingPuzzleProgress", "CgGeneratedPuzzleSession",
    "CgLanguageCertification", "CgLastActivityPuzzle", "CgPuzzleFeedback",
    "CgPuzzleMinimalProgress", "CgPuzzleOfTheWeek", "CgPuzzleTopicNode", "CgSolutionLanguage",
    "CgSolvedPuzzlesByLanguage",
]
