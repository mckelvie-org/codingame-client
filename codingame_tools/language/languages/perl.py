"""`CgPerlLanguage`: `CgLanguage` for CodinGame's "Perl"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgPerlLanguage", "LANGUAGE"]


class CgPerlLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Perl")

    @property
    def extension(self) -> str:
        return "pl"


LANGUAGE = CgPerlLanguage()
