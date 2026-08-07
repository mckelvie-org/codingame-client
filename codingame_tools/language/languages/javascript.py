"""`CgJavascriptLanguage`: `CgLanguage` for CodinGame's "Javascript"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgJavascriptLanguage", "LANGUAGE"]


class CgJavascriptLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Javascript")

    @property
    def extension(self) -> str:
        return "js"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """Installs nothing: Node is the `node20` subsystem, shared with TypeScript, which CodinGame
           also runs on Node 20.9.0."""
        return CgToolchainFragment(slug="javascript", version=1, depends_on=("node20",))


LANGUAGE = CgJavascriptLanguage()
