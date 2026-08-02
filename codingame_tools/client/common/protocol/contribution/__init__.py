"""
Protocol schema definitions for the Contribution service.
"""

from __future__ import annotations

from .schema import (
    CgContribution,
    CgContributionData,
    CgContributionId,
    CgContributionModerator,
    CgContributionStatusChange,
    CgContributionStatusHistoryEntry,
    CgContributionVersion,
    CgDeleteContributionResult,
    CgHtml,
    CgMarkdown,
    CgModerationAction,
    CgPendingContribution,
    CgPersonalContribution,
    CgPuzzleType,
    CgSolutionLanguage,
    CgStubGenerator,
    CgTestCase,
    CgTopic,
    CgValidateAction,
)

__all__ = [
    "CgContribution", "CgContributionData", "CgContributionModerator", "CgContributionStatusChange",
    "CgContributionStatusHistoryEntry", "CgContributionVersion", "CgTestCase", "CgModerationAction",
    "CgMarkdown", "CgHtml", "CgStubGenerator", "CgTopic", "CgContributionId",
    "CgPendingContribution", "CgPersonalContribution", "CgPuzzleType", "CgSolutionLanguage", "CgValidateAction",
    "CgDeleteContributionResult",
]
