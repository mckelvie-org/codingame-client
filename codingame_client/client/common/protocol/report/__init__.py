"""
Protocol schema definitions for the Report service.
"""

from __future__ import annotations

from ..last_activities import CgPuzzleFeedback
from .schema import CgReportPuzzleProgress, CgSubmissionReport, CgValidatorResult

__all__ = [
    "CgPuzzleFeedback", "CgReportPuzzleProgress", "CgSubmissionReport", "CgValidatorResult",
]
