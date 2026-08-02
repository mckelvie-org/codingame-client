"""`CgBashLanguage`: `CgLanguage` for CodinGame's "Bash"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgBashLanguage", "LANGUAGE"]


class CgBashLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Bash")

    @property
    def extension(self) -> str:
        return "sh"


LANGUAGE = CgBashLanguage()
