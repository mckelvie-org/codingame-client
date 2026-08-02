"""`CgJavaLanguage`: `CgLanguage` for CodinGame's "Java"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgJavaLanguage", "LANGUAGE"]


class CgJavaLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Java")

    @property
    def extension(self) -> str:
        return "java"


LANGUAGE = CgJavaLanguage()
