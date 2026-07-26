"""
JSON-serializable dataclasses for the Report service's findReportBySubmission Codingame API
method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .....common.dataclass_wizard_x import Alias, CatchAll, CgEpochMillis, JSONWizardX
from ..last_activities.schema import CgPuzzleFeedback


@dataclass
class CgReportPuzzleProgress(JSONWizardX):
    """Lightweight puzzle progress summary, as embedded in
       `CgSubmissionReport.puzzle_progress`. A much smaller summary than `CgLastActivityPuzzle`
       (last_activities/schema.py) or `CgPuzzleMinimalProgress` (puzzle/schema.py)."""

    id: int
    """Numeric ID of the puzzle."""

    achievement_count: int
    """Total number of achievements associated with this puzzle."""

    done_achievement_count: int
    """Number of this puzzle's achievements the codingamer has unlocked."""

    validator_score: int
    """Unclear why this differs from the enclosing `CgSubmissionReport.score`--observed as 0
       here despite a 100.0 `score`/`best_score` on the same report. Possibly stale/unrelated to
       this specific submission."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgValidatorResult(JSONWizardX):
    """A single server-side validator's result for a submission, as embedded in
       `CgSubmissionReport.validators`."""

    method_name: str
    """Internal name of the validator method, e.g. "Validator_1"."""

    name: str
    """Display name/label for the validator test case, e.g. "Miguel de Cervantes"."""

    difficulty: int
    """Relative difficulty/weight of this validator, e.g. 100."""

    success: bool
    """Whether the submission passed this validator."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgSubmissionReport(JSONWizardX):
    """The complete response to Report/findReportBySubmission: a report on a single puzzle
       submission's results."""

    codingamer_id: int
    """The submitting codingamer's numeric ID."""

    submission_id: int
    """Numeric ID of the submission this report is for (matches the `submission_id` argument)."""

    score: float
    """The submission's validator score, 0.0 to 100.0."""

    best_score: float
    """The codingamer's best-ever validator score for this puzzle, 0.0 to 100.0 (may be higher
       than `score` if this submission wasn't their best attempt)."""

    achievements_completed: bool
    """Whether all achievements for this puzzle have been completed by the codingamer."""

    shared: bool
    """Whether the codingamer has publicly shared their solution."""

    validator_shareable: bool
    """Whether this submission's validator results are eligible to be shared."""

    puzzle_progress: CgReportPuzzleProgress
    """Lightweight puzzle progress summary."""

    validators: list[CgValidatorResult]
    """Per-validator results for this submission."""

    achievements: list[Any]
    """Achievements unlocked by this submission. Only observed as an empty list so far, so
       element shape is unknown."""

    _completed_time: CgEpochMillis = Alias("completedTime")
    """When this submission was completed."""

    extra_data: CatchAll = field(default_factory=dict)

    feedback: CgPuzzleFeedback | None = None
    """Community feedback/rating summary for the puzzle. Not confirmed to always be present
       (only a single example observed so far)."""

    @property
    def completed_time(self) -> datetime:
        """See the field docstring for `_completed_time`. Always UTC."""
        return self._completed_time

    @completed_time.setter
    def completed_time(self, value: datetime) -> None:
        self._completed_time = CgEpochMillis.upcast(value)


__all__ = ["CgReportPuzzleProgress", "CgSubmissionReport", "CgValidatorResult"]
