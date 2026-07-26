"""
Protocol schema definitions for the TestSession service.
"""

from __future__ import annotations

from ..contribution import CgHtml, CgStubGenerator
from ..last_activities import CgLastActivityContributor
from ..schema import CgSolutionLanguage
from .schema import (
    CgAvailableLanguage,
    CgMultipleLanguagesTestParams,
    CgPlayComparison,
    CgPlayError,
    CgPlayRequest,
    CgPlayResult,
    CgPlayStackFrame,
    CgSubmitRequest,
    CgTestSession,
    CgTestSessionAnswer,
    CgTestSessionContribution,
    CgTestSessionPuzzle,
    CgTestSessionQuestion,
    CgTestSessionQuestionDetails,
    CgTestSessionQuestionSummary,
    CgTestSessionTestCase,
)

__all__ = [
    "CgAvailableLanguage", "CgHtml", "CgLastActivityContributor",
    "CgMultipleLanguagesTestParams", "CgPlayComparison", "CgPlayError", "CgPlayRequest",
    "CgPlayResult", "CgPlayStackFrame", "CgSolutionLanguage", "CgStubGenerator",
    "CgSubmitRequest", "CgTestSession", "CgTestSessionAnswer", "CgTestSessionContribution",
    "CgTestSessionPuzzle", "CgTestSessionQuestion", "CgTestSessionQuestionDetails",
    "CgTestSessionQuestionSummary", "CgTestSessionTestCase",
]
