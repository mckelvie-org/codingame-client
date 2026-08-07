"""`CgBashLanguage`: `CgLanguage` for CodinGame's "Bash"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgBashLanguage", "LANGUAGE"]


class CgBashLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Bash")

    @property
    def extension(self) -> str:
        return "sh"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """The only language with no subsystem: `bash` is in the base image already, so this
           installs nothing and depends on nothing.

           Bookworm ships bash 5.2.15 against CodinGame's 5.1.16 (published; their `dpkg` reports
           `5.1-6`, which is that upstream patch level). Close enough that no puzzle should notice,
           and pinning an older bash would mean building it from source for a shell.

           **Debugging is tracing, not breakpoints.** There is no debug adapter for bash worth
           wiring up, so `CG_BASH_DEBUG_FLAGS` carries `-x`: the shell prints each command as it
           executes, to stderr, which for a shell solution is the information a stepping debugger
           would have given you anyway."""
        return CgToolchainFragment(
                slug="bash",
                version=1,
                env_script=(
                    'export CG_BASH=/bin/bash\n'
                    'export CG_BASH_DEBUG_FLAGS="-x"\n'
                ),
            )


LANGUAGE = CgBashLanguage()
