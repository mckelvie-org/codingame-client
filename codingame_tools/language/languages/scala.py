"""`CgScalaLanguage`: `CgLanguage` for CodinGame's "Scala"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgScalaLanguage", "LANGUAGE"]


class CgScalaLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Scala")

    @property
    def extension(self) -> str:
        return "scala"


LANGUAGE = CgScalaLanguage()
