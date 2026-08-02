"""`CgDefaultLanguage`: pure catch-all `CgLanguage` for a `cg_id` this client has never seen."""

from __future__ import annotations

from .base import CgLanguage

__all__ = ["CgDefaultLanguage"]


class CgDefaultLanguage(CgLanguage):
    """No overrides--relies entirely on `CgLanguage`'s base-class defaults (extension unknown,
       comment syntax unknown, no stub, no local execution). Used only for a `cg_id` CodinGame
       might add in the future that this client has never seen--every language CodinGame is
       confirmed to support today has its own real module under
       `codingame_tools.language.languages`, even one that only implements `extension`, so it
       never falls back to this. Bound to the real `cg_id` it was looked up with (never a generic
       placeholder), so error messages/logging naming `.cg_id` are always accurate."""
