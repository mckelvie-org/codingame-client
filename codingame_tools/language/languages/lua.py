"""`CgLuaLanguage`: `CgLanguage` for CodinGame's "Lua"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage

__all__ = ["CgLuaLanguage", "LANGUAGE"]


class CgLuaLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Lua")

    @property
    def extension(self) -> str:
        return "lua"


LANGUAGE = CgLuaLanguage()
