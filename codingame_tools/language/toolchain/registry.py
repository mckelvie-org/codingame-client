"""Every known toolchain fragment, and the translation from CodinGame language names to slugs.

   Two sources feed one table: the subsystems cg ships (`subsystems.SUBSYSTEMS`) and whatever each
   language plugin declares through `CgLanguage.toolchain_fragment`. Languages own their own
   fragments for the same reason they own their own run and debug logic -- adding a language should
   mean adding one module, not editing a central list.

   Users name languages the way CodinGame does (`"C++"`, `"Python3"`); fragments are slugs (`cpp`,
   `python3`) because the name ends up in shell paths and Dockerfile identifiers where `+` and case
   are hostile. `resolve_language_slugs` is the one place that mapping happens, so nothing else has
   to know both spellings.
"""

from __future__ import annotations

from .fragment import CgToolchainError, CgToolchainFragment, resolve_fragments
from .subsystems import SUBSYSTEMS

__all__ = [
    "all_fragments",
    "default_languages",
    "fragments_for_languages",
    "resolve_language_slugs",
]


def all_fragments() -> dict[str, CgToolchainFragment]:
    """Every fragment cg knows, keyed by slug.

       Built fresh rather than cached: the language registry is itself lazily discovered, and a
       stale copy here would be a second source of truth for something that already has one."""
    # Imported here, not at module scope: the language registry imports every plugin, each of which
    # imports `base`, which imports this package. At module scope that is a cycle -- the same one
    # `codingame_tools.language.vscode` resolves the same way.
    from ..registry import get_language, list_language_cg_ids

    table: dict[str, CgToolchainFragment] = {f.slug: f for f in SUBSYSTEMS}
    for cg_id in list_language_cg_ids():
        fragment = get_language(cg_id).toolchain_fragment
        if fragment is None:
            continue
        existing = table.get(fragment.slug)
        if existing is not None and existing != fragment:
            raise CgToolchainError(
                    f"two different toolchain fragments claim the slug {fragment.slug!r} "
                    f"({cg_id} collides with an existing definition)")
        table[fragment.slug] = fragment
    return table


def default_languages() -> list[str]:
    """Every language cg can put in an image -- the default contents of the toolchain.

       **Derived, never a hardcoded list.** A language is in the default set exactly when it declares
       a `toolchain_fragment`, so adding one is a single-module change and the two can never drift
       apart.

       The default is *everything* rather than a minimal subset because the whole set costs about
       1.9 GB: the languages that dominate (JDK, .NET, Node) share one Debian base instead of each
       dragging its own, so trimming saves far less than the confusion of having to choose. Subset
       builds remain available for anyone who wants one -- see `CgSettingsData.toolchain_languages`
       -- they are just not something a user should have to think about."""
    from ..registry import get_language, list_language_cg_ids

    return [
        cg_id for cg_id in list_language_cg_ids()
        if get_language(cg_id).toolchain_fragment is not None
    ]


def resolve_language_slugs(languages: list[str]) -> list[str]:
    """Fragment slugs for CodinGame language names, e.g. `["C++"] -> ["cpp"]`.

    Raises:
        CgToolchainError: if a name isn't a known language, or is one with no container support --
                           distinguished, because "you typed it wrong" and "cg can't containerize
                           that yet" need different fixes.
    """
    # Imported here, not at module scope: the language registry imports every plugin, each of which
    # imports `base`, which imports this package. At module scope that is a cycle -- the same one
    # `codingame_tools.language.vscode` resolves the same way.
    from ..registry import get_language, list_language_cg_ids

    known = {cg_id.casefold(): cg_id for cg_id in list_language_cg_ids()}
    slugs: list[str] = []
    for name in languages:
        cg_id = known.get(name.casefold())
        if cg_id is None:
            raise CgToolchainError(
                    f"unknown language {name!r}. Known: {', '.join(sorted(known.values()))}")
        fragment = get_language(cg_id).toolchain_fragment
        if fragment is None:
            raise CgToolchainError(
                    f"{cg_id} has no toolchain fragment yet, so it can't be built into an image. "
                    "Languages gain one as they gain a real build/run backend.")
        slugs.append(fragment.slug)
    return slugs


def fragments_for_languages(languages: list[str]) -> list[CgToolchainFragment]:
    """Everything needed to build an image for `languages`, in install order.

       The whole pipeline in one call: names to slugs, slugs to fragments, dependencies pulled in and
       ordered deterministically."""
    return resolve_fragments(resolve_language_slugs(languages), all_fragments())
