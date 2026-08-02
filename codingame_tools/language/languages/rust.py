"""`CgRustLanguage`: `CgLanguage` for CodinGame's "Rust"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgRustLanguage", "LANGUAGE"]


class CgRustLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Rust")

    @property
    def extension(self) -> str:
        return "rs"


LANGUAGE = CgRustLanguage()
