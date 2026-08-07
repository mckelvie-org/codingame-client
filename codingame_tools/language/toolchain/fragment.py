"""Composable Dockerfile fragments: the pieces a multi-language toolchain image is built from.

   One image has to serve several languages at once--that is what makes a single dev container work,
   and what lets `cg` run more than one language without a container per language. But the languages
   don't get along by default. CodinGame runs **Oracle JDK 21.0.4 for Java and JVM 1.8 for Clojure,
   Groovy and Scala**, so a single image must carry both, and neither can own the global `JAVA_HOME`.
   Elsewhere the opposite is true and sharing is essential: C# / F# / VB.NET all run one .NET
   runtime, JavaScript and TypeScript one Node, C and C++ one gcc.

   Both facts point at the same shape: **an image is composed from fragments with dependencies**,
   like a makefile. A fragment is either

   - a **subsystem**--`gcc11`, `jvm8`, `jdk21`, `node20`--which installs a toolchain, or
   - a **language**, which usually installs nothing and merely depends on a subsystem plus supplies
     its own activation script. `C` and `C++` are exactly this: both depend on `gcc11`, both emit
     zero Dockerfile lines, and they differ only in whether their script exports `CG_CC` or `CG_CXX`.

   A fragment emitting no Dockerfile lines at all is therefore normal, not degenerate.

   ## Why activation scripts rather than a global environment

   Each fragment may ship `/opt/cg/env.d/<slug>.sh`, which exports what its toolchain needs and
   sources its dependencies' scripts first, so activation is transitive. Every command cg runs in
   the container is prefixed with one line:

   ```sh
   . /opt/cg/env.d/cpp.sh
   "$CG_CXX" $CG_CXXFLAGS -x c++ -o "$out" "$src"
   ```

   The two alternatives were rejected deliberately:

   - **A global `PATH`/`JAVA_HOME`** cannot represent two JDKs at once. The conflict above is simply
     unrepresentable, so this fails at the first multi-JVM image.
   - **Wrapper executables** (`/opt/cg/bin/cpp-compile`) would move compile flags *into the image*,
     versioning them with the image rather than with cg--so changing a warning flag would need an
     image rebuild. Activation scripts keep the split where it belongs: the **image** knows where its
     toolchain is, **cg** knows how to invoke it.

   ## Why ordering is deterministic

   `render_dockerfile` sorts topologically and breaks ties by slug, so a subset's fragment order is
   a prefix of a superset's. That makes a subset image's layers a prefix of the superset's, so adding
   a language rebuilds only from that point on, and a larger published image reuses layers already
   pulled. It is the reason to sort at all: correctness alone would accept any topological order.
"""

from __future__ import annotations

import hashlib
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "CgToolchainError",
    "CgToolchainFragment",
    "ENV_DIR",
    "render_dockerfile",
    "resolve_fragments",
]

ENV_DIR = "/opt/cg/env.d"
"""Where activation scripts live inside the image--see the module docstring.

   Under `/opt` rather than `/etc/profile.d` deliberately: these are *not* meant to apply to every
   shell. Sourcing them all would defeat the point, since two of them may set `JAVA_HOME`
   incompatibly. They are opt-in, one at a time, by the command that needs one."""


class CgToolchainError(Exception):
    """Raised for an unresolvable fragment set--an unknown slug, or a dependency cycle."""


@dataclass(frozen=True)
class CgToolchainFragment:
    """One composable piece of a toolchain image."""

    slug: str
    """Stable identifier, used in dependency edges, in the generated header, and as the activation
       script's filename. Lowercase, no spaces--it appears in shell and Dockerfile contexts."""

    version: int
    """Bumped whenever `dockerfile` or `env_script` changes, so an unmodified generated Dockerfile
       can be detected as stale and regenerated. Deliberately per fragment rather than one global
       template version: changing the Rust fragment shouldn't invalidate a C++-only image."""

    depends_on: tuple[str, ...] = ()
    """Slugs that must be installed before this one. The mechanism that lets several languages share
       a toolchain (`C` and `C++` -> `gcc11`) and lets conflicting ones coexist (`java` -> `jdk21`
       while `scala` -> `jvm8`)."""

    dockerfile: str = ""
    """Statements inserted verbatim. **Legitimately empty**: a language whose toolchain is entirely
       supplied by a subsystem contributes only its dependency edge and its activation script, and
       emits nothing here. An empty fragment produces no Dockerfile section and so no extra layer."""

    env_script: str = ""
    """Body of `/opt/cg/env.d/<slug>.sh`, if this fragment needs one. The composer prepends the
       `. <dep>.sh` lines itself, so a fragment only writes its own exports."""


def resolve_fragments(
            requested: Iterable[str],
            registry: Mapping[str, CgToolchainFragment],
        ) -> list[CgToolchainFragment]:
    """Every fragment needed for `requested`, dependencies first, in deterministic order.

       Ties are broken by slug so the result is stable across runs and, more importantly, so a
       subset's order is a prefix of a superset's--see the module docstring on layer sharing.

    Args:
        requested: Slugs asked for, in any order. Duplicates are harmless.
        registry:  Every known fragment, keyed by slug.

    Returns:
        Fragments in install order.

    Raises:
        CgToolchainError: on an unknown slug or a dependency cycle.
    """
    table = dict(registry)

    def lookup(slug: str) -> CgToolchainFragment:
        try:
            return table[slug]
        except KeyError:
            known = ", ".join(sorted(table)) or "<none>"
            raise CgToolchainError(
                    f"unknown toolchain fragment {slug!r}. Known: {known}") from None

    ordered: list[CgToolchainFragment] = []
    done: set[str] = set()
    # Depth-first with an explicit "in progress" set, so a cycle is reported with the path that
    # closes it rather than as a bare RecursionError.
    visiting: list[str] = []

    def visit(slug: str) -> None:
        fragment = lookup(slug)
        if fragment.slug in done:
            return
        if fragment.slug in visiting:
            cycle = " -> ".join([*visiting[visiting.index(fragment.slug):], fragment.slug])
            raise CgToolchainError(f"toolchain fragment dependency cycle: {cycle}")
        visiting.append(fragment.slug)
        for dependency in sorted(fragment.depends_on):
            visit(dependency)
        visiting.pop()
        done.add(fragment.slug)
        ordered.append(fragment)

    for slug in sorted(set(requested)):
        visit(slug)
    return ordered


def _env_script_statements(fragment: CgToolchainFragment) -> str:
    """Dockerfile statements writing `fragment`'s activation script.

       Written with `echo` into a redirect rather than a BuildKit heredoc or a base64 blob. Heredocs
       in `RUN` need a `# syntax=` frontend directive, which pulls an image from Docker Hub on first
       build; base64 would make the generated Dockerfile unreadable, and the user is expected to read
       and extend it. Every line is single-quoted, so nothing in a script body is interpreted at
       build time."""
    if not fragment.env_script.strip() and not fragment.depends_on:
        return ""
    lines = [f". {ENV_DIR}/{dependency}.sh" for dependency in sorted(fragment.depends_on)]
    lines.extend(fragment.env_script.strip().splitlines())
    if not lines:
        return ""
    echoes = " \\\n      ".join(f"echo {shlex.quote(line)};" for line in lines)
    return (
        f"RUN mkdir -p {ENV_DIR} && {{ \\\n"
        f"      {echoes} \\\n"
        f"    }} > {ENV_DIR}/{fragment.slug}.sh\n"
    )


def render_dockerfile(
            fragments: list[CgToolchainFragment],
            *,
            base_image: str,
            preamble: str = "",
        ) -> str:
    """The full cg-owned Dockerfile for `fragments`, already in install order.

       *Renders* cg's own `base.dockerfile` content. Distinct from
       `codingame_tools.language._docker.compose_dockerfile`, which *composes* that file on disk with
       the user's `custom.dockerfile` -- generation versus merging.

       The header is machine-readable in the same spirit as the single-language one it replaces: it
       records every fragment and its version, so a generated file can be recognized as cg's, checked
       for staleness, and told apart from one the user has edited.

    Args:
        fragments:  In install order, as returned by `resolve_fragments`.
        base_image: Value for the `CG_BASE_IMAGE` build arg--one pinned neutral base that every
                     fragment installs onto, rather than a per-language base image.
        preamble:   Statements common to every image, inserted before any fragment.
    """
    manifest = ",".join(f"{f.slug}@{f.version}" for f in fragments)
    body_parts: list[str] = [
        f"ARG CG_BASE_IMAGE={base_image}\n",
        "FROM ${CG_BASE_IMAGE}\n",
    ]
    if preamble.strip():
        body_parts.append("\n" + preamble.strip("\n") + "\n")
    for fragment in fragments:
        section = fragment.dockerfile.strip("\n")
        env = _env_script_statements(fragment)
        if not section and not env:
            # Normal, not degenerate: a language wholly supplied by a subsystem. Emitting an empty
            # section would add a comment-only layer and, worse, make two identical images differ.
            continue
        body_parts.append(f"\n# --- {fragment.slug} ---\n")
        if section:
            body_parts.append(section + "\n")
        if env:
            body_parts.append(env)
    body = "".join(body_parts)

    header = (
            "# cg-managed toolchain--do not edit.\n"
            "# Put your own additions in custom.dockerfile instead; they're appended to this file\n"
            "# and survive every cg template upgrade.\n"
            f"# cg-toolchain: fragments={manifest} "
            f"body-sha256={hashlib.sha256(body.encode('utf-8')).hexdigest()}\n"
        )
    return header + body
