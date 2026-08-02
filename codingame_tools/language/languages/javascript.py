"""`CgJavascriptLanguage`: `CgLanguage` for CodinGame's "Javascript"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgJavascriptLanguage", "LANGUAGE"]


class CgJavascriptLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Javascript")

    @property
    def extension(self) -> str:
        return "js"


LANGUAGE = CgJavascriptLanguage()
