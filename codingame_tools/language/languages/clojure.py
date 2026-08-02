"""`CgClojureLanguage`: `CgLanguage` for CodinGame's "Clojure"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgClojureLanguage", "LANGUAGE"]


class CgClojureLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Clojure")

    @property
    def extension(self) -> str:
        return "clj"


LANGUAGE = CgClojureLanguage()
