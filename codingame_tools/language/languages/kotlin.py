"""`CgKotlinLanguage`: `CgLanguage` for CodinGame's "Kotlin"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgKotlinLanguage", "LANGUAGE"]


class CgKotlinLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Kotlin")

    @property
    def extension(self) -> str:
        return "kt"


LANGUAGE = CgKotlinLanguage()
