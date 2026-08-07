"""`CgJavaLanguage`: `CgLanguage` for CodinGame's "Java"--extension and toolchain fragment only;
   local execution and contribution-create stub generation aren't implemented yet.
"""

from __future__ import annotations

from ..base import CgLanguage
from ..toolchain.fragment import CgToolchainFragment

__all__ = ["CgJavaLanguage", "LANGUAGE"]


class CgJavaLanguage(CgLanguage):
    def __init__(self) -> None:
        super().__init__("Java")

    @property
    def extension(self) -> str:
        return "java"

    @property
    def toolchain_fragment(self) -> CgToolchainFragment:
        """Installs nothing itself: the JDK is the `jdk21` subsystem, which no other language may
           share -- Clojure, Groovy and Scala need JVM 1.8, and CodinGame keeps four JDKs side by
           side for exactly that reason.

           `CG_JAVA_CLASSPATH` carries gson because CodinGame does: a measured run reports
           `java.class.path` containing `/codemachine/lib/java/external/gson.jar`. It is absent from
           their published table, so a solution importing `com.google.gson` would compile there and
           fail here without it.

           A solution must be `class Solution` with a `public static void main(String[])`, which is
           what CodinGame's own stub provides."""
        return CgToolchainFragment(
                slug="java",
                version=1,
                depends_on=("jdk21",),
                env_script=(
                    'export CG_JAVAC="$JAVA_HOME/bin/javac"\n'
                    'export CG_JAVA="$JAVA_HOME/bin/java"\n'
                ),
            )


LANGUAGE = CgJavaLanguage()
