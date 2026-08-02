"""`CgVbNetLanguage`: `CgLanguage` for CodinGame's "VB.NET"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgVbNetLanguage", "LANGUAGE"]


class CgVbNetLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("VB.NET")

    @property
    def extension(self) -> str:
        return "vb"


LANGUAGE = CgVbNetLanguage()
