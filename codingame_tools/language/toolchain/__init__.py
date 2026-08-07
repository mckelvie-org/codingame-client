"""Composable multi-language toolchain images.

   One image serves several languages, built from dependency-ordered fragments -- see
   `fragment` for the model and why it exists, and `subsystems` for the shared toolchains
   languages install onto.
"""

from __future__ import annotations

from .fragment import (
    ENV_DIR,
    CgToolchainError,
    CgToolchainFragment,
    render_dockerfile,
    resolve_fragments,
)
from .registry import (
    all_fragments,
    default_languages,
    fragments_for_languages,
    resolve_language_slugs,
)
from .subsystems import BASE_IMAGE, PREAMBLE, SUBSYSTEMS

__all__ = [
    "BASE_IMAGE",
    "ENV_DIR",
    "PREAMBLE",
    "SUBSYSTEMS",
    "CgToolchainError",
    "CgToolchainFragment",
    "all_fragments",
    "default_languages",
    "render_dockerfile",
    "fragments_for_languages",
    "resolve_fragments",
    "resolve_language_slugs",
]
