"""`CgObjectiveCLanguage`: `CgLanguage` for CodinGame's "ObjectiveC"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgObjectiveCLanguage", "LANGUAGE"]


class CgObjectiveCLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("ObjectiveC")

    @property
    def extension(self) -> str:
        return "m"


LANGUAGE = CgObjectiveCLanguage()
