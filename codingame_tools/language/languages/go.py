"""`CgGoLanguage`: `CgLanguage` for CodinGame's "Go"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgGoLanguage", "LANGUAGE"]


class CgGoLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Go")

    @property
    def extension(self) -> str:
        return "go"


LANGUAGE = CgGoLanguage()
