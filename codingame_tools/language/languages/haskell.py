"""`CgHaskellLanguage`: `CgLanguage` for CodinGame's "Haskell"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgHaskellLanguage", "LANGUAGE"]


class CgHaskellLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Haskell")

    @property
    def extension(self) -> str:
        return "hs"


LANGUAGE = CgHaskellLanguage()
