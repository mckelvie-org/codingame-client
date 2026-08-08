"""Per-language behavior for CodinGame solutions--file extension, local execution, comment
   syntax, and a `cg contribution create` starter stub--behind one abstract interface,
   `CgLanguage`. This is the *only* interface outside code should use to access a language; never
   import a concrete class like `CgPython3Language` directly, and never branch on a language ID
   string in `puzzle_manager`/`contribution_manager`--go through `get_language`/
   `get_language_by_extension` instead.

   Adding a new language is purely additive: drop in a new flat module under
   `codingame_tools.language.languages` (e.g. `languages/java.py`, exposing a module-level
   `LANGUAGE: CgLanguage` singleton--see `codingame_tools.language.registry`'s module docstring
   for the exact discovery contract) and override whichever `CgLanguage` capabilities it actually
   supports. No changes needed anywhere else--`codingame_tools.language.registry` discovers every
   module automatically at load time by walking `languages/` (no hardcoded list, no exclusion
   list).

   `codingame_tools.language.default.CgDefaultLanguage` is a pure catch-all for a `cg_id`
   CodinGame might add in the future that this client has never seen--every language CodinGame
   is confirmed to support today has its own real module under `languages/`, even one that only
   implements `extension` (see `languages/java.py`, `languages/cpp.py`, etc.).

   **Debugging is per-language, by necessity.** A debugger launch is a fundamentally different
   mechanism per language, not just a different command: Python runs in-process under debugpy
   (`codingame_tools.test_runner.debug_stdin`), while C++ runs gdb inside a container and is driven
   over a pipe by the cpptools adapter (`languages/cpp.py`). So `CgLanguage.start_debug_session`
   and `CgLanguage.vscode_provisioning` are per-language rather than shared, and a language gains
   debugging by implementing them--see `codingame_tools.language.vscode` for the generated
   launch-configuration contract that keeps them from colliding.

   **Containerized languages share one image.** Anything needing a toolchain cg can't assume is
   installed runs in a container built from `codingame_tools.language.toolchain`'s composable
   fragments--one image for every language, so a workspace runs one container rather than one per
   language. See `_docker.py`.
"""

from __future__ import annotations

from ._docker import (
    CgDockerCleanResult,
    CgDockerError,
    build_image_content,
    clean_managed,
    compose_dockerfile,
    compose_with_base,
    ensure_base_dockerfile,
    ensure_image,
    image_tag_for,
    latest_alias_for,
    list_managed_containers,
    remove_containers_for_root,
    tag_image,
)
from .base import (
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_RUN_TIMEOUT_SECONDS,
    DEFAULT_TOOLCHAIN_BUILD_TIMEOUT_SECONDS,
    TOOLCHAIN_SUBDIR_NAME,
    CgBuildProfile,
    CgBuildResult,
    CgDebugSession,
    CgLanguage,
    CgLanguageContext,
    CgLanguageOperationNotSupportedError,
    CgRunEvent,
    CgRunFinished,
    CgRunOutputChunk,
    CgRunResult,
    CgRunStream,
)
from .default import CgDefaultLanguage
from .registry import get_language, get_language_by_extension, list_language_cg_ids
from .toolchain import (
    BASE_IMAGE,
    PREAMBLE,
    CgToolchainError,
    CgToolchainFragment,
    all_fragments,
    default_languages,
    fragments_for_languages,
    render_dockerfile,
    resolve_language_slugs,
)
from .vscode import (
    CgVsCodeKind,
    CgVsCodeMergeError,
    CgVsCodeProvisioning,
    CgVsCodeRequest,
    find_workspace_root,
    write_provisioning,
)

__all__ = [
    "TOOLCHAIN_SUBDIR_NAME",
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "DEFAULT_BUILD_TIMEOUT_SECONDS",
    "DEFAULT_TOOLCHAIN_BUILD_TIMEOUT_SECONDS",
    "CgBuildProfile",
    "CgBuildResult",
    "CgDebugSession",
    "CgLanguage",
    "CgLanguageContext",
    "CgLanguageOperationNotSupportedError",
    "CgRunEvent",
    "CgRunFinished",
    "CgRunOutputChunk",
    "CgRunResult",
    "CgRunStream",
    "CgDefaultLanguage",
    "remove_containers_for_root",
    "CgDockerCleanResult",
    "CgDockerError",
    "clean_managed",
    "list_managed_containers",
    "build_image_content",
    "compose_dockerfile",
    "compose_with_base",
    "ensure_base_dockerfile",
    "ensure_image",
    "image_tag_for",
    "latest_alias_for",
    "tag_image",
    "BASE_IMAGE",
    "PREAMBLE",
    "CgToolchainError",
    "CgToolchainFragment",
    "all_fragments",
    "default_languages",
    "fragments_for_languages",
    "render_dockerfile",
    "resolve_language_slugs",
    "CgVsCodeKind",
    "CgVsCodeMergeError",
    "CgVsCodeProvisioning",
    "CgVsCodeRequest",
    "find_workspace_root",
    "write_provisioning",
    "get_language",
    "get_language_by_extension",
    "list_language_cg_ids",
]
