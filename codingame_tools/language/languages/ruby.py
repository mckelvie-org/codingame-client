"""`CgRubyLanguage`: `CgLanguage` for CodinGame's "Ruby"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgRubyLanguage", "LANGUAGE"]


class CgRubyLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Ruby")

    @property
    def extension(self) -> str:
        return "rb"


LANGUAGE = CgRubyLanguage()
