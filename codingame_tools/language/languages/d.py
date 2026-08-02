"""`CgDLanguage`: `CgLanguage` for CodinGame's "D"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgDLanguage", "LANGUAGE"]


class CgDLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("D")

    @property
    def extension(self) -> str:
        return "d"


LANGUAGE = CgDLanguage()
