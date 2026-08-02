"""`CgPhpLanguage`: `CgLanguage` for CodinGame's "PHP"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgPhpLanguage", "LANGUAGE"]


class CgPhpLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("PHP")

    @property
    def extension(self) -> str:
        return "php"


LANGUAGE = CgPhpLanguage()
