"""`CgCppLanguage`: `CgLanguage` for CodinGame's "C++"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgCppLanguage", "LANGUAGE"]


class CgCppLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("C++")

    @property
    def extension(self) -> str:
        return "cpp"


LANGUAGE = CgCppLanguage()
