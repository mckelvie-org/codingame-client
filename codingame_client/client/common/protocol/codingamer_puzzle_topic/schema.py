"""
JSON-serializable dataclasses for the CodingamerPuzzleTopic service's findTopicsByCodingamerId
Codingame API method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .....common.dataclass_wizard_x import Alias, CatchAll, CgEpochMillis, JSONWizardX

CgPuzzleTopicCategory = str
"""The difficulty category a puzzle topic belongs to, e.g. "FUNDAMENTALS", "INTERMEDIATE",
   "ADVANCED"."""


@dataclass
class CgCodingamerPuzzleTopic(JSONWizardX):
    """A codingamer's progress on a single puzzle topic (e.g. "Arrays", "BFS"), as returned by
       findTopicsByCodingamerId. Only topics the codingamer has made some progress on are
       returned (100 topics observed for a codingamer active since ~2018)."""

    category: CgPuzzleTopicCategory
    """The topic's difficulty category; see `CgPuzzleTopicCategory`."""

    handle: str
    """Opaque (but human-readable) slug for the topic, e.g. "2d-array", "bfs"."""

    label: str
    """Display name for the topic, e.g. "2D array", "BFS"."""

    puzzle_count: int
    """Number of puzzles tagged with this topic that the codingamer has solved/attempted."""

    _last_progress_time: CgEpochMillis = Alias("lastProgressTime")
    """When the codingamer last made progress on a puzzle tagged with this topic."""

    extra_data: CatchAll = field(default_factory=dict)

    @property
    def last_progress_time(self) -> datetime:
        """See the field docstring for `_last_progress_time`. Always UTC."""
        return self._last_progress_time

    @last_progress_time.setter
    def last_progress_time(self, value: datetime) -> None:
        self._last_progress_time = CgEpochMillis.upcast(value)


__all__ = ["CgCodingamerPuzzleTopic", "CgPuzzleTopicCategory"]
