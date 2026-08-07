"""`CgCLanguage`: `CgLanguage` for CodinGame's "C"--extension and toolchain fragment only; local
   execution and contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgCLanguage", "LANGUAGE"]


class CgCLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("C")

    @property
    def extension(self) -> str:
        return "c"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """Installs nothing: C is entirely supplied by the shared `gcc11` subsystem, which C++ also
           depends on, so an image containing both carries one compiler rather than two.

           All this fragment contributes is the dependency edge and an activation script naming the
           C compiler and CodinGame's flags -- `mode C17`, linking `-lm -lpthread -ldl -lcrypt`.

           **The flags are measured, not guessed.** A probe run on CodinGame reports `__OPTIMIZE__`
           *undefined* and `__NO_INLINE__` defined, so the platform compiles at **-O0** -- while cg
           previously used `-O2`. That asymmetry is the dangerous direction: an O(n^2) solution fast
           enough locally at -O2 can exceed the time limit on submission, and the local run would
           have said it was fine. Matching means the local run predicts the remote one, which is the
           only reason to pin a toolchain at all. See doc/design/codingame-runtime.md.

           `-O0` explicitly rather than by omission, and deliberately **not** configurable. Optimizing
           past CodinGame buys nothing: puzzles are designed to be solvable in every supported
           language, so the time limits are set by the slowest of them and a C solution has orders of
           magnitude of headroom either way. It also makes single-stepping faithful -- at -O0 the code
           you step through is the code you wrote, with nothing reordered or inlined away."""
        return CgToolchainFragment(
                slug="c",
                version=2,
                depends_on=("gcc11",),
                env_script=(
                    'export CG_CFLAGS="-std=c17 -O0 -g -Wall -Wextra"\n'
                    'export CG_CFLAGS_DEBUG="-std=c17 -O0 -g3 -Wall -Wextra"\n'
                    'export CG_CLIBS="-lm -lpthread -ldl -lcrypt"\n'
                ),
            )


LANGUAGE = CgCLanguage()
