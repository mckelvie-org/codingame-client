"""Discovery of every `codingame_tools.language.languages` module, and the lookup functions built
   on top of the resulting index--`get_language`/`get_language_by_extension`/
   `list_language_cg_ids`. See `codingame_tools.language.languages`'s package docstring for the
   discovery contract each language module must follow.

   Discovery runs once, eagerly, the first time this module is imported (i.e. at
   `codingame_tools.language` package load time)--not lazily on first lookup. There are only
   27 language modules today, so there's no meaningful cost concern either way; eager discovery
   is simply easier to reason about (the index is fully built before any caller could possibly
   observe it partially populated).

   Importing `CgLanguage`/`CgDefaultLanguage` here is from `.base`/`.default` specifically, never
   from `codingame_tools.language` itself--the parent package's `__init__.py` is still
   mid-execution while this module runs during discovery, so importing from it here would hit a
   partially-initialized module. Every language module under `.languages` must follow the same
   rule (import `CgLanguage` from `..base`, never from `codingame_tools.language`).
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from .base import CgLanguage
from .default import CgDefaultLanguage

__all__ = [
    "get_language",
    "get_language_by_extension",
    "list_language_cg_ids",
]

_LANGUAGES_PACKAGE_DIR = Path(__file__).parent / "languages"
_LANGUAGES_PACKAGE_NAME = f"{__package__}.languages"


def _discover_languages() -> dict[str, CgLanguage]:
    """Walk every immediate module of `codingame_tools.language.languages`, import it, and read
       its `LANGUAGE: CgLanguage` singleton--see that package's docstring for this discovery
       contract. No hardcoded list of language modules, and no exclusion list--every module
       under `languages/` is, by construction, a real language plugin (there's nothing else to
       exclude--`default.py`/`_process.py`/`registry.py` all live one level up, outside this
       walk)."""
    by_cg_id: dict[str, CgLanguage] = {}
    for info in pkgutil.iter_modules([str(_LANGUAGES_PACKAGE_DIR)]):
        module = importlib.import_module(f"{_LANGUAGES_PACKAGE_NAME}.{info.name}")
        language: CgLanguage = module.LANGUAGE
        by_cg_id[language.cg_id] = language
    return by_cg_id


_by_cg_id: dict[str, CgLanguage] = _discover_languages()
_by_extension: dict[str, CgLanguage] = {
        language.extension: language for language in _by_cg_id.values() if language.extension is not None
    }
_unknown_by_cg_id: dict[str, CgDefaultLanguage] = {}
"""Lazily-populated cache for `cg_id`s that aren't a discovered language plugin--so repeated
   `get_language()` calls for the same unrecognized ID return the identical object
   (identity-stable, like a real singleton) rather than a fresh instance each time."""


def get_language(cg_id: str) -> CgLanguage:
    """Look up the `CgLanguage` for a CodinGame protocol language ID.

       Always succeeds: returns the real implementation if `cg_id` matches a discovered language
       plugin, or--for a `cg_id` this client has no record of at all--a `CgDefaultLanguage` bound
       to that ID anyway (memoized, so repeated lookups of the same unrecognized ID return the
       same object).
    """
    language = _by_cg_id.get(cg_id)
    if language is not None:
        return language
    unknown = _unknown_by_cg_id.get(cg_id)
    if unknown is None:
        unknown = CgDefaultLanguage(cg_id)
        _unknown_by_cg_id[cg_id] = unknown
    return unknown


def get_language_by_extension(filename_or_extension: str) -> CgLanguage | None:
    """Look up the `CgLanguage` whose `extension` matches `filename_or_extension` (a bare
       extension, with or without a leading '.', or a full filename--only the suffix after the
       last '.' is considered; case-insensitive).

    Returns:
        The matching `CgLanguage`, or `None` if no known language claims this extension--there's
        no reasonable default to fall back to, unlike `get_language`.
    """
    ext = filename_or_extension.lower()
    if "." in ext:
        ext = ext.rsplit(".", 1)[1]
    return _by_extension.get(ext)


def list_language_cg_ids() -> tuple[str, ...]:
    """The `cg_id`s of every discovered language plugin (sorted)--every language CodinGame is
       confirmed to support has one, whether or not it implements local execution."""
    return tuple(sorted(_by_cg_id))
