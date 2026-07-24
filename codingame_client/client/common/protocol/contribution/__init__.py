"""
Protocol schema definitions for the Contribution service.
"""

from __future__ import annotations

from .schema import (
    CgContribution,
    CgContributionData,
    CgContributionId,
    CgContributionVersion,
    CgHtml,
    CgMarkdown,
    CgPuzzleType,
    CgSolutionLanguage,
    CgStubGenerator,
    CgTestCase,
    CgTopic,
    cg_extension_to_solution_language,
)

__all__ = [
    "CgContribution", "CgContributionData", "CgContributionVersion", "CgTestCase",
    "CgMarkdown", "CgHtml", "CgStubGenerator", "CgTopic", "CgContributionId",
    "CgPuzzleType", "CgSolutionLanguage", "cg_extension_to_solution_language",
]
