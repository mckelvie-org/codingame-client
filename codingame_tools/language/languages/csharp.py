"""`CgCSharpLanguage`: `CgLanguage` for CodinGame's "C#"--extension and toolchain fragment only;
   local execution and contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgCSharpLanguage", "LANGUAGE"]


class CgCSharpLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("C#")

    @property
    def extension(self) -> str:
        return "cs"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """Installs nothing itself: .NET is the `dotnet8` subsystem, shared with F# and VB.NET --
           CodinGame runs all three on one runtime, so an image with several must not carry it twice.

           Measured there as .NET 8.0.8 with `DOTNET_ROOT=/opt/coderunner/dotnet/sdk` prepended to
           `PATH`, which is the same per-language activation this fragment performs.

           `-unsafe` matches CodinGame's published compile flag."""
        return CgToolchainFragment(
                slug="csharp",
                version=1,
                depends_on=("dotnet8",),
                env_script=(
                    'export CG_DOTNET=/opt/cg/dotnet8/dotnet\n'
                    'export CG_CSFLAGS="-unsafe"\n'
                ),
            )


LANGUAGE = CgCSharpLanguage()
