"""`CgTypeScriptLanguage`: `CgLanguage` for CodinGame's "TypeScript"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgTypeScriptLanguage", "LANGUAGE"]


class CgTypeScriptLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("TypeScript")

    @property
    def extension(self) -> str:
        return "ts"


LANGUAGE = CgTypeScriptLanguage()
