"""Unit tests for `codingame_tools.language.toolchain`: composing a multi-language toolchain image
   from dependency-ordered fragments.

Pure/local--no Docker, no network--so they run under the default `pdm run test` invocation. That is
the point of testing here rather than by building: the conflict these fragments exist to resolve
(two incompatible JDKs in one image) can be proven at the *composition* layer in milliseconds,
instead of by building a multi-gigabyte image to look at it.
"""

from __future__ import annotations

import pytest

from codingame_tools.language.toolchain import (
    BASE_IMAGE,
    PREAMBLE,
    CgToolchainError,
    CgToolchainFragment,
    all_fragments,
    default_languages,
    fragments_for_languages,
    render_dockerfile,
    resolve_fragments,
    resolve_language_slugs,
)

# A miniature registry standing in for the real one. Deliberately models the two shapes that matter:
# languages sharing one toolchain (c/cpp -> gcc), and a language family split across incompatible
# ones (java -> jdk21 while scala -> jvm8).
_GCC = CgToolchainFragment(slug="gcc", version=1, dockerfile="RUN install-gcc\n")
_JVM8 = CgToolchainFragment(slug="jvm8", version=1, dockerfile="RUN install-jvm8\n")
_JDK21 = CgToolchainFragment(slug="jdk21", version=1, dockerfile="RUN install-jdk21\n")
_C = CgToolchainFragment(slug="c", version=1, depends_on=("gcc",), env_script="export CG_CC=gcc")
_CPP = CgToolchainFragment(slug="cpp", version=1, depends_on=("gcc",), env_script="export CG_CXX=g++")
_JAVA = CgToolchainFragment(slug="java", version=1, depends_on=("jdk21",))
_SCALA = CgToolchainFragment(slug="scala", version=1, depends_on=("jvm8",))

_REGISTRY = {f.slug: f for f in (_GCC, _JVM8, _JDK21, _C, _CPP, _JAVA, _SCALA)}


def _slugs(*requested: str) -> list[str]:
    return [f.slug for f in resolve_fragments(requested, _REGISTRY)]


# --- resolution ---------------------------------------------------------------------------------


def test_dependencies_come_before_the_fragments_that_need_them() -> None:
    assert _slugs("cpp") == ["gcc", "cpp"]


def test_languages_sharing_a_toolchain_install_it_once() -> None:
    """The reason subsystems exist. C and C++ are one gcc; an image with both must not carry two."""
    order = _slugs("c", "cpp")

    assert order.count("gcc") == 1
    assert order == ["gcc", "c", "cpp"]


def test_incompatible_toolchains_coexist(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The conflict this whole design exists for: CodinGame runs Java on JDK 21 but Clojure, Groovy
       and Scala on JVM 1.8, so one image must carry both and neither may be global.

       Proven here rather than by building, which would mean two JDKs and several gigabytes to
       observe something that is entirely a property of composition."""
    order = _slugs("java", "scala")

    assert "jdk21" in order
    assert "jvm8" in order

    dockerfile = render_dockerfile(
            resolve_fragments(["java", "scala"], _REGISTRY), base_image="debian:x")
    assert "RUN install-jdk21" in dockerfile
    assert "RUN install-jvm8" in dockerfile


def test_order_is_deterministic_regardless_of_request_order() -> None:
    assert _slugs("cpp", "c") == _slugs("c", "cpp")


def test_a_subset_is_a_prefix_of_a_superset() -> None:
    """Not cosmetic: identical ordering makes a subset image's layers a prefix of the superset's, so
       adding a language rebuilds only from that point and a larger published image reuses layers
       already pulled. Any topological order would be *correct*; only a stable one is useful."""
    subset = _slugs("c")
    superset = _slugs("c", "cpp")

    assert superset[:len(subset)] == subset


def test_duplicate_requests_are_harmless() -> None:
    assert _slugs("cpp", "cpp") == ["gcc", "cpp"]


def test_a_cycle_is_reported_with_the_path_that_closes_it() -> None:
    registry = {
        "x": CgToolchainFragment(slug="x", version=1, depends_on=("y",)),
        "y": CgToolchainFragment(slug="y", version=1, depends_on=("x",)),
    }

    with pytest.raises(CgToolchainError, match=r"cycle: x -> y -> x"):
        resolve_fragments(["x"], registry)


def test_an_unknown_slug_names_what_is_known() -> None:
    with pytest.raises(CgToolchainError, match="unknown toolchain fragment 'nope'"):
        resolve_fragments(["nope"], _REGISTRY)


# --- composition --------------------------------------------------------------------------------


def test_a_fragment_with_nothing_to_install_emits_no_section() -> None:
    """A language wholly supplied by a subsystem is the normal case, not a degenerate one. Emitting
       an empty section would add a layer for nothing and make two identical images differ."""
    empty = CgToolchainFragment(slug="bare", version=1)

    dockerfile = render_dockerfile([empty], base_image="debian:x")

    assert "# --- bare ---" not in dockerfile


def test_an_activation_script_sources_its_dependencies_first() -> None:
    """Activation is transitive, so a caller sources one script rather than knowing the graph."""
    dockerfile = render_dockerfile(resolve_fragments(["cpp"], _REGISTRY), base_image="debian:x")

    script = dockerfile[dockerfile.index("# --- cpp ---"):]
    assert script.index(". /opt/cg/env.d/gcc.sh") < script.index("export CG_CXX=g++")


def test_the_header_records_every_fragment_and_version() -> None:
    """So a generated file can be recognized as cg's, told apart from a hand-edited one, and checked
       for staleness when a fragment's version moves."""
    dockerfile = render_dockerfile(resolve_fragments(["cpp"], _REGISTRY), base_image="debian:x")

    assert "# cg-toolchain: fragments=gcc@1,cpp@1 " in dockerfile
    assert "body-sha256=" in dockerfile


def test_different_fragment_sets_hash_differently() -> None:
    one = render_dockerfile(resolve_fragments(["c"], _REGISTRY), base_image="debian:x")
    two = render_dockerfile(resolve_fragments(["c", "cpp"], _REGISTRY), base_image="debian:x")

    assert one != two


# --- the real registry --------------------------------------------------------------------------


def test_cg_ids_map_to_slugs() -> None:
    """Users name languages the way CodinGame does; fragments are slugs because the name lands in
       shell paths and Dockerfile identifiers where `+` and case are hostile."""
    assert resolve_language_slugs(["C++", "Python3"]) == ["cpp", "python3"]
    assert resolve_language_slugs(["c++"]) == ["cpp"]  # matching is case-insensitive


def test_a_language_without_a_fragment_says_so_distinctly() -> None:
    """"You typed it wrong" and "cg can't containerize that yet" need different fixes, so they get
       different messages."""
    with pytest.raises(CgToolchainError, match="unknown language"):
        resolve_language_slugs(["Cobol"])
    with pytest.raises(CgToolchainError, match="no toolchain fragment yet"):
        resolve_language_slugs(["Haskell"])


def test_the_default_toolchain_is_every_supported_language() -> None:
    """Derived from which languages declare a fragment, so adding a language is one module change
       and the default can never drift from what is actually buildable.

       Everything rather than a minimal subset because the whole set is ~1.9 GB -- the big toolchains
       share one Debian base -- so trimming saves little and costs the user a decision."""
    languages = default_languages()

    assert set(languages) == {
        "Bash", "C", "C#", "C++", "Java", "Javascript", "Python3", "TypeScript"}
    # Every default language must actually resolve; a name in the list with no fragment would make
    # the zero-configuration build fail.
    assert fragments_for_languages(languages)


def test_a_subset_still_composes() -> None:
    """Subset builds stay available for anyone who wants one -- just not the default."""
    fragments = fragments_for_languages(["Python3", "C", "C++"])
    slugs = [f.slug for f in fragments]

    assert slugs.index("gcc11") < slugs.index("cpp")
    assert slugs.index("python311") < slugs.index("python3")
    assert slugs.count("gcc11") == 1  # C and C++ share it

    dockerfile = render_dockerfile(fragments, base_image=BASE_IMAGE, preamble=PREAMBLE)
    assert dockerfile.startswith("# cg-managed toolchain")
    assert f"ARG CG_BASE_IMAGE={BASE_IMAGE}" in dockerfile


def test_cpp_links_what_codingame_links() -> None:
    """cg previously passed no link libraries at all, so a solution using `pthread_create` or
       `dlopen` could link on CodinGame and fail locally. The flags live in the activation script
       rather than the image so changing one doesn't mean rebuilding gigabytes."""
    fragment = all_fragments()["cpp"]

    assert "-lm -lpthread -ldl -lcrypt" in fragment.env_script
    assert "-std=c++20" in fragment.env_script
    # Separate from CG_CXXFLAGS because link libraries must follow the translation unit, not precede
    # it -- putting them in the same variable would put them in the wrong place on the command line.
    assert "CG_CXXLIBS=" in fragment.env_script


def test_the_shipped_fragments_are_the_languages_worth_carrying() -> None:
    """Python, C++, Java and C# are CodinGame's most-used languages; C rides along on C++'s gcc and
       TypeScript on JavaScript's Node, so both are nearly free; Bash needs nothing at all. The
       remaining 19 stay stubs until someone needs them -- an image should not carry a toolchain
       merely to be thorough."""
    assert set(all_fragments()) == {
        "gcc11", "python311", "jdk21", "dotnet8", "node20",              # subsystems
        "bash", "c", "cpp", "csharp", "java", "javascript",              # languages
        "python3", "typescript",
    }


def test_bash_needs_no_subsystem_at_all() -> None:
    """The base image already has bash, so its fragment installs nothing and depends on nothing --
       the far end of the spectrum from TypeScript, which installs a compiler."""
    bash = all_fragments()["bash"]

    assert bash.depends_on == ()
    assert bash.dockerfile == ""
    # Tracing stands in for a debugger: there is no bash debug adapter worth wiring up, and `-x`
    # prints each command as it runs, which is what stepping would have shown.
    assert "-x" in bash.env_script


def test_javascript_and_typescript_share_one_node() -> None:
    """CodinGame runs both on Node 20.9.0. TypeScript additionally installs `tsc`, which is the one
       language fragment that legitimately installs something: a compiler on top of a runtime, with
       exactly one consumer."""
    fragments = fragments_for_languages(["JavaScript", "TypeScript"])
    slugs = [f.slug for f in fragments]

    assert slugs.count("node20") == 1
    assert all_fragments()["javascript"].dockerfile == ""
    assert "typescript@5.6.2" in all_fragments()["typescript"].dockerfile


def test_the_popular_four_compose_without_conflict() -> None:
    """Each brings its own subsystem and none collide, because none of them touch the global
       environment -- every toolchain is reached through its own activation script."""
    fragments = fragments_for_languages(["Python3", "C++", "Java", "C#"])
    slugs = [f.slug for f in fragments]

    for language, subsystem in (("cpp", "gcc11"), ("java", "jdk21"),
                                ("csharp", "dotnet8"), ("python3", "python311")):
        assert slugs.index(subsystem) < slugs.index(language), language

    dockerfile = render_dockerfile(fragments, base_image=BASE_IMAGE, preamble=PREAMBLE)
    # Each subsystem installs under its own prefix; none writes a global JAVA_HOME or PATH into the
    # image itself, which is what lets a future JVM-8 language coexist with Java 21.
    assert "ENV JAVA_HOME" not in dockerfile
    assert "ENV PATH" not in dockerfile
    assert dockerfile.count("/opt/cg/env.d/") >= len(fragments)


def test_java_carries_the_undocumented_gson_classpath() -> None:
    """Measured on CodinGame -- `java.class.path` includes gson, which their published table never
       mentions. Without it a solution importing `com.google.gson` compiles there and fails here."""
    assert "gson" in all_fragments()["jdk21"].dockerfile
    assert "CG_JAVA_CLASSPATH" in all_fragments()["jdk21"].env_script


def test_dotnet_is_shared_rather_than_owned_by_csharp() -> None:
    """C#, F# and VB.NET all run one .NET runtime on CodinGame, so the runtime is a subsystem. Were
       it folded into the C# fragment, an image with C# and F# would carry it twice."""
    assert all_fragments()["csharp"].depends_on == ("dotnet8",)
    assert all_fragments()["csharp"].dockerfile == ""


def test_flags_match_what_codingame_measurably_uses() -> None:
    """Measured by probe, not read from CodinGame's published table -- which was stale on every
       library version and silent on optimization.

       `-O2` locally against `-O0` remotely is the dangerous asymmetry: an O(n^2) solution fast
       enough on the developer's machine can exceed the time limit on submission, having passed
       locally. See doc/design/codingame-runtime.md."""
    fragments = all_fragments()

    for slug, flags_var in (("c", "CG_CFLAGS"), ("cpp", "CG_CXXFLAGS")):
        run_flags = next(
                line for line in fragments[slug].env_script.splitlines()
                if line.startswith(f"export {flags_var}="))
        assert "-O2" not in run_flags, f"{slug} must not out-optimize CodinGame: {run_flags}"

    python = fragments["python311"].dockerfile
    # numpy and scipy match CodinGame exactly. pandas cannot: 1.4.2 has no cp311 wheel, so pip
    # cannot install it on 3.11 and the image build fails -- 1.5.0 is the earliest that works.
    assert "numpy==1.23.2" in python
    assert "scipy==1.9.3" in python
    assert "pandas==1.5.0" in python
    # The *published* numpy (1.20.2) is impossible on 3.11 -- wheels stop at cp39.
    assert "1.20.2" not in python
