"""Registry of known external 3-way diff/merge tools that can be pointed at three materialized
   directory trees (base/local/remote)--see `codingame_client.contribution_manager.manager`'s
   `CgContributionManager.last_committed_dir`/`remote_dir`/`materialize_remote`, and the
   `cg contribution diff`/`merge --interactive` CLI commands.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

__all__ = [
    "DEFAULT_MERGE_TOOL",
    "MERGE_TOOL_COMMANDS",
    "CgMergeToolNotFoundError",
    "launch_merge_tool",
]

DEFAULT_MERGE_TOOL = "meld"

MERGE_TOOL_COMMANDS: dict[str, list[str]] = {
    "meld": ["meld", "{base}", "{local}", "{remote}"],
    "kdiff3": ["kdiff3", "{base}", "{local}", "{remote}", "-o", "{local}"],
}
"""Maps a tool name to its launch argument template ("{base}"/"{local}"/"{remote}" substituted
   with the three materialized directory paths). "meld" is well-confirmed--it has native 3-way
   *directory* compare, drilling into a differing file for a per-hunk 3-way merge view. "kdiff3"
   is included on a best-effort basis (well known specifically for 3-way *merge* UX) but its exact
   CLI directory-mode conventions haven't been independently verified here--check `kdiff3 --help`
   if it doesn't behave as expected."""


class CgMergeToolNotFoundError(Exception):
    """Raised when the requested tool name isn't a known entry in `MERGE_TOOL_COMMANDS`, or its
       executable isn't found on PATH."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
                f"Merge tool {tool_name!r} not found on PATH, or not a known tool "
                f"(known: {', '.join(sorted(MERGE_TOOL_COMMANDS))})."
            )


def launch_merge_tool(tool_name: str, *, base_dir: Path, local_dir: Path, remote_dir: Path) -> int:
    """Launch the named external tool pointed at the three directories, blocking until it exits.
       `local_dir` is expected to be the real contribution working directory (not a temp copy),
       so edits made in the tool land directly in the real files--the caller can just re-run
       `cg contribution commit` afterward.

    Returns:
        The tool's process exit code.

    Raises:
        CgMergeToolNotFoundError: if `tool_name` isn't a known tool, or its executable isn't found
                                   on PATH.
    """
    template = MERGE_TOOL_COMMANDS.get(tool_name)
    if template is None or shutil.which(template[0]) is None:
        raise CgMergeToolNotFoundError(tool_name)
    args = [part.format(base=str(base_dir), local=str(local_dir), remote=str(remote_dir)) for part in template]
    result = subprocess.run(args, check=False)
    return result.returncode
