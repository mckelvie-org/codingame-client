"""`CgGroovyLanguage`: `CgLanguage` for CodinGame's "Groovy"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgGroovyLanguage", "LANGUAGE"]


class CgGroovyLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Groovy")

    @property
    def extension(self) -> str:
        return "groovy"


LANGUAGE = CgGroovyLanguage()
