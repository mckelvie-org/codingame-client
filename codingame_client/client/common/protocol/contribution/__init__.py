"""
Protocol schema definitions for the Contribution service.
"""

from __future__ import annotations

from .schema import (
    CgContribution,
    CgContributionData,
    CgContributionId,
    CgContributionStatusChange,
    CgContributionStatusHistoryEntry,
    CgContributionVersion,
    CgDeleteContributionResult,
    CgHtml,
    CgMarkdown,
    CgPendingContribution,
    CgPuzzleType,
    CgSolutionLanguage,
    CgStubGenerator,
    CgTestCase,
    CgTopic,
    CgValidateAction,
    cg_extension_to_solution_language,
    cg_solution_language_to_extension,
)

__all__ = [
    "CgContribution", "CgContributionData", "CgContributionStatusChange",
    "CgContributionStatusHistoryEntry", "CgContributionVersion", "CgTestCase",
    "CgMarkdown", "CgHtml", "CgStubGenerator", "CgTopic", "CgContributionId",
    "CgPendingContribution", "CgPuzzleType", "CgSolutionLanguage", "CgValidateAction",
    "CgDeleteContributionResult",
    "cg_extension_to_solution_language", "cg_solution_language_to_extension",
]
