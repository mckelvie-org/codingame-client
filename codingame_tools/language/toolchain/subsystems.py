"""Subsystem fragments: the toolchains languages install and share.

   A *subsystem* is a fragment that isn't a language. It exists because the mapping between languages
   and toolchains is neither one-to-one nor one-way:

   - **Several languages, one toolchain.** C and C++ are the same gcc; C# / F# / VB.NET are one .NET
     runtime; JavaScript and TypeScript are one Node. Installing that toolchain once, and having each
     language depend on it, is the only way an image containing both isn't carrying it twice.
   - **One language family, several incompatible toolchains.** CodinGame runs Java on Oracle JDK
     21.0.4 but Clojure, Groovy and Scala on JVM 1.8, so an image with Java *and* Scala needs both
     JDKs present and neither global. Separate subsystems, separate activation scripts.

   **Versions here are not arbitrary--they mirror what CodinGame actually runs**, because the entire
   value of a pinned toolchain is that a local run predicts a submission. Getting one wrong is worse
   than having no container at all: it produces confident local success followed by remote failure.
   See `codingame_tools.language.languages` for the per-language fragments that depend on these.

   Only the subsystems backing implemented languages live here. Adding a language means adding its
   subsystem alongside it, rather than shipping toolchains nothing can drive--which would inflate
   every image for no benefit.
"""

from __future__ import annotations

from .fragment import CgToolchainFragment

__all__ = [
    "BASE_IMAGE",
    "PREAMBLE",
    "SUBSYSTEMS",
]

BASE_IMAGE = "debian:bookworm-slim"
"""The one neutral base every fragment installs onto.

   Deliberately not a language image such as `gcc:14`. A per-language base cannot compose--two of
   them cannot both be `FROM`--and it hides the toolchain version in an image tag, which is exactly
   how the C++ build came to be silently two major gcc releases ahead of CodinGame's."""

PREAMBLE = """\
# Common to every cg toolchain image, whatever languages it carries.
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \\
    && apt-get install -y --no-install-recommends ca-certificates coreutils \\
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/cg/env.d /build
WORKDIR /build
"""
"""Statements shared by every image, before any fragment.

   `coreutils` supplies the `timeout` and `stdbuf` the run and debug paths depend on (already present
   on Debian; named so a swapped base still gets them)."""

_GCC11 = CgToolchainFragment(
        slug="gcc11",
        version=1,
        # Measured on CodinGame (see doc/design/codingame-runtime.md): gcc **11.2.0**, `__cplusplus`
        # 202002, `_GLIBCXX_RELEASE` 11, glibc **2.36**, x86_64.
        #
        # Bookworm gives gcc 11.3.0 and glibc 2.36 -- the glibc matches exactly, and the compiler is
        # one patch level up within the same C++20 feature set. Far closer than the gcc 14 this
        # replaces, which was two major releases ahead and accepted C++20 constructs CodinGame
        # rejects. Matching 11.2.0 exactly would mean building gcc from source, which is not worth a
        # patch release.
        #
        # Note CodinGame's `/etc/os-release` claims Debian 11 (bullseye), whose glibc is 2.31 -- but
        # both the compile-time headers and the run-time loader report 2.36, which is bookworm's. The
        # label is misleading; the measured glibc is what the base image is chosen to match.
        dockerfile="""\
RUN apt-get update \\
    && apt-get install -y --no-install-recommends gcc-11 g++-11 gdb libc6-dev \\
    && rm -rf /var/lib/apt/lists/*
""",
        env_script="""\
export CG_CC=/usr/bin/gcc-11
export CG_CXX=/usr/bin/g++-11
""",
    )
"""gcc, shared by C and C++.

   Installed as the versioned `gcc-11`/`g++-11` binaries rather than the unversioned aliases (which
   bookworm points at gcc 12), so the compiler cannot drift when the base image updates--the failure
   this whole exercise exists to prevent."""

_PYTHON311 = CgToolchainFragment(
        slug="python311",
        version=3,
        # Measured on CodinGame by running a probe solution (see doc/design/codingame-runtime.md),
        # not taken from their published table -- which is stale on the libraries:
        #
        #   published:  Python 3.11.5, NumPy 1.20.2, pandas 1.2.4, SciPy 1.6.3
        #   measured:   Python 3.11.5, NumPy 1.23.2, pandas 1.4.2, SciPy 1.9.3
        #
        # The published NumPy is not merely wrong but impossible: 1.20.2 ships wheels for cp37-cp39
        # only and predates 3.11's C-API, so that pairing cannot exist.
        #
        # numpy and scipy are pinned to exactly what CodinGame runs. **pandas cannot be**: 1.4.2
        # publishes no cp311 wheel either (cp38/39/310 only), so pip cannot install it on 3.11 and
        # the image build fails outright -- which is how this was found, by building rather than
        # reasoning. CodinGame evidently compiles it from source; cg takes 1.5.0, the earliest
        # release with a cp311 wheel, rather than building pandas on every image build.
        #
        # Bookworm's python3 is 3.11.2 against CodinGame's 3.11.5 -- same minor series, and the
        # closest apt-installable match.
        dockerfile="""\
RUN apt-get update \\
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \\
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/cg/python311 \\
    && /opt/cg/python311/bin/pip install --no-cache-dir \\
        numpy==1.23.2 pandas==1.5.0 scipy==1.9.3
""",
        env_script="""\
export CG_PYTHON=/opt/cg/python311/bin/python3
export PATH=/opt/cg/python311/bin:$PATH
""",
    )
"""Python, in its own virtualenv.

   Separated from the system interpreter so installing NumPy/pandas/SciPy cannot disturb anything
   Debian depends on, and so a future second Python version can coexist the way the two JDKs must."""

_JDK21 = CgToolchainFragment(
        slug="jdk21",
        version=1,
        # Measured on CodinGame: java.version 21.0.4, vendor "Oracle Corporation", HotSpot 64-Bit
        # Server VM 21.0.4+8-LTS-274, java.home /opt/coderunner/jdk-21.0.4.
        #
        # Temurin rather than Oracle: same OpenJDK 21.0.4 sources and the same HotSpot VM, but
        # installable without a licence click and published for both architectures. The vendor string
        # differs; nothing a puzzle can observe does.
        #
        # `TARGETARCH` is supplied by BuildKit, so one fragment serves amd64 and arm64 -- CodinGame is
        # x86_64, but a build on Apple Silicon must not be forced through emulation.
        #
        # Deliberately under its own prefix and *not* on the global PATH: CodinGame keeps four JDKs
        # side by side (jdk1.8.0_211, jdk-11.0.2, jdk-17.0.8, jdk-21.0.4) because Clojure, Groovy and
        # Scala need JVM 1.8 while Java needs 21. Only the activation script decides which is active.
        dockerfile="""\
ARG TARGETARCH
RUN set -eu; \\
    apt-get update; \\
    apt-get install -y --no-install-recommends curl; \\
    rm -rf /var/lib/apt/lists/*; \\
    case "${TARGETARCH:-amd64}" in \\
      amd64) jdk_arch=x64 ;; \\
      arm64) jdk_arch=aarch64 ;; \\
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \\
    esac; \\
    mkdir -p /opt/cg/jdk21; \\
    base=https://github.com/adoptium/temurin21-binaries/releases/download; \\
    file="OpenJDK21U-jdk_${jdk_arch}_linux_hotspot_21.0.4_7.tar.gz"; \\
    curl -fsSL "${base}/jdk-21.0.4%2B7/${file}" \\
      | tar -xz -C /opt/cg/jdk21 --strip-components=1
# CodinGame puts gson on every Java solution's classpath (measured: java.class.path contains
# /codemachine/lib/java/external/gson.jar). Undocumented, but a solution may well import it.
RUN mkdir -p /opt/cg/java-libs \\
    && curl -fsSL -o /opt/cg/java-libs/gson.jar \\
       https://repo1.maven.org/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar
""",
        env_script="""\
export JAVA_HOME=/opt/cg/jdk21
export CG_JAVA_CLASSPATH=/opt/cg/java-libs/gson.jar
export PATH=$JAVA_HOME/bin:$PATH
""",
    )
"""Java's JDK, installed under its own prefix.

   The prefix is the whole point: CodinGame runs four JDKs simultaneously, and any image supporting
   both Java and Scala must do the same. Nothing here touches the global environment."""

_DOTNET8 = CgToolchainFragment(
        slug="dotnet8",
        version=1,
        # Measured on CodinGame: .NET 8.0.8 runtime, RuntimeIdentifier linux-x64, DOTNET_ROOT
        # /opt/coderunner/dotnet/sdk. Their published "Runtime 8.0.401" is the *SDK* version, which
        # ships exactly that runtime -- so the docs and the probe agree once you know which is which.
        #
        # Microsoft's install script handles architecture detection itself, so no TARGETARCH case is
        # needed. The SDK, not just the runtime: C# has to be compiled.
        #
        # One runtime serves C#, F# and VB.NET -- the sharing case subsystems exist for, and the
        # reason this is not simply folded into the C# fragment.
        dockerfile="""\
RUN set -eu; \\
    apt-get update; \\
    apt-get install -y --no-install-recommends curl libicu72; \\
    rm -rf /var/lib/apt/lists/*; \\
    curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh; \\
    # `bash`, not `sh`: the installer uses `set -o pipefail`, which dash rejects outright
    # ("Illegal option"). Debian's /bin/sh is dash, so `sh dotnet-install.sh` fails at line 12.
    bash /tmp/dotnet-install.sh --version 8.0.401 --install-dir /opt/cg/dotnet8; \\
    rm /tmp/dotnet-install.sh
""",
        env_script="""\
export DOTNET_ROOT=/opt/cg/dotnet8
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export PATH=/opt/cg/dotnet8:$PATH
""",
    )
""".NET, shared by C#, F# and VB.NET.

   `DOTNET_CLI_TELEMETRY_OPTOUT`/`DOTNET_NOLOGO` because a first-run banner on stdout would corrupt a
   solution's output, which is compared byte for byte."""

_NODE20 = CgToolchainFragment(
        slug="node20",
        version=1,
        # CodinGame runs Node 20.9.0 for both JavaScript and TypeScript. Bookworm ships 18.x, so this
        # takes the exact upstream tarball rather than whatever apt offers -- a major version apart is
        # the kind of gap that changes which syntax parses.
        #
        # A subsystem rather than part of the JavaScript fragment because TypeScript runs on the same
        # Node; an image with both must not carry two.
        dockerfile="""\
ARG TARGETARCH
RUN set -eu; \\
    apt-get update; \\
    apt-get install -y --no-install-recommends curl xz-utils; \\
    rm -rf /var/lib/apt/lists/*; \\
    case "${TARGETARCH:-amd64}" in \\
      amd64) node_arch=x64 ;; \\
      arm64) node_arch=arm64 ;; \\
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \\
    esac; \\
    mkdir -p /opt/cg/node20; \\
    curl -fsSL "https://nodejs.org/dist/v20.9.0/node-v20.9.0-linux-${node_arch}.tar.xz" \\
      | tar -xJ -C /opt/cg/node20 --strip-components=1
""",
        env_script="""\
export CG_NODE=/opt/cg/node20/bin/node
export PATH=/opt/cg/node20/bin:$PATH
""",
    )
"""Node, shared by JavaScript and TypeScript."""

SUBSYSTEMS: tuple[CgToolchainFragment, ...] = (_GCC11, _PYTHON311, _JDK21, _DOTNET8, _NODE20)
"""Every subsystem cg ships. Collected by `codingame_tools.language.toolchain.registry`."""
