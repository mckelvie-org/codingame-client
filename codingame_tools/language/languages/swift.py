"""`CgSwiftLanguage`: `CgLanguage` for CodinGame's "Swift"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgSwiftLanguage", "LANGUAGE"]


class CgSwiftLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Swift")

    @property
    def extension(self) -> str:
        return "swift"


LANGUAGE = CgSwiftLanguage()
