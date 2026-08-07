"""`CgTypeScriptLanguage`: `CgLanguage` for CodinGame's "TypeScript"--extension only; local execution and
   contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgTypeScriptLanguage", "LANGUAGE"]


class CgTypeScriptLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("TypeScript")

    @property
    def extension(self) -> str:
        return "ts"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """Node comes from the shared `node20` subsystem; the compiler itself is installed here,
           because only TypeScript needs it.

           An exception to the usual shape -- most language fragments emit no Dockerfile lines at all
           -- and a reasonable one: `tsc` is a package on top of a runtime rather than a runtime, so
           a `typescript` subsystem would have exactly one consumer forever.

           Installed into the Node prefix, so it stays inside `node20`'s tree and no global `PATH`
           entry is created. CodinGame runs TypeScript 5.6.2 on Node 20.9.0."""
        return CgToolchainFragment(
                slug="typescript",
                version=1,
                depends_on=("node20",),
                dockerfile=(
                    # PATH is set for this RUN only, never in the image: npm's shebang is
                    # `#!/usr/bin/env node`, so invoking it by absolute path fails with exit 127
                    # when node isn't on PATH -- which it deliberately never is. Scoping the
                    # variable to the one command keeps the isolation property intact.
                    "RUN PATH=/opt/cg/node20/bin:$PATH \\\n"
                    "    npm install -g --prefix /opt/cg/node20 typescript@5.6.2\n"
                ),
                env_script='export CG_TSC=/opt/cg/node20/bin/tsc\n',
            )


LANGUAGE = CgTypeScriptLanguage()
