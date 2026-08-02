"""`CgCSharpLanguage`: `CgLanguage` for CodinGame's "C#"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgCSharpLanguage", "LANGUAGE"]


class CgCSharpLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("C#")

    @property
    def extension(self) -> str:
        return "cs"


LANGUAGE = CgCSharpLanguage()
