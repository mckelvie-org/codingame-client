"""`CgDartLanguage`: `CgLanguage` for CodinGame's "Dart"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgDartLanguage", "LANGUAGE"]


class CgDartLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Dart")

    @property
    def extension(self) -> str:
        return "dart"


LANGUAGE = CgDartLanguage()
