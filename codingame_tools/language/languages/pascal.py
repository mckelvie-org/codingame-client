"""`CgPascalLanguage`: `CgLanguage` for CodinGame's "Pascal"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgPascalLanguage", "LANGUAGE"]


class CgPascalLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Pascal")

    @property
    def extension(self) -> str:
        return "pas"


LANGUAGE = CgPascalLanguage()
