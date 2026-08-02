"""`CgFSharpLanguage`: `CgLanguage` for CodinGame's "F#"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgFSharpLanguage", "LANGUAGE"]


class CgFSharpLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("F#")

    @property
    def extension(self) -> str:
        return "fs"


LANGUAGE = CgFSharpLanguage()
