"""`CgOCamlLanguage`: `CgLanguage` for CodinGame's "OCaml"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgOCamlLanguage", "LANGUAGE"]


class CgOCamlLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("OCaml")

    @property
    def extension(self) -> str:
        return "ml"


LANGUAGE = CgOCamlLanguage()
