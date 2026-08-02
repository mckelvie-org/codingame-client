"""`CgPython3Language`: the concrete `CgLanguage` implementation for CodinGame's "Python3"--see
   `codingame_tools.language.registry` for the discovery contract (`LANGUAGE` below) that finds
   it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from .._process import run_argv_streaming
from ..base import DEFAULT_RUN_TIMEOUT_SECONDS, CgLanguage, CgRunEvent

__all__ = [
    "CgPython3Language",
    "LANGUAGE",
]


class CgPython3Language(CgLanguage):
    """Python3 (CodinGame's `cg_id` "Python3"), the only language with a full implementation
       today. See `CgLanguage` for what each capability means."""

    def __init__(self) -> None:
        super().__init__("Python3")

    @property
    def extension(self) -> str:
        return "py"

    @property
    def comment_prefix(self) -> str:
        return "#"

    async def build_contribution_create_stub_source(self) -> str:
        return "n = input()\nprint(n)\n"

    async def run_streaming(
                self,
                solution_file: Path,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> AsyncGenerator[CgRunEvent, None]:
        """Runs `solution_file` with the *same* Python interpreter this client itself runs under
           (`sys.executable`), rather than hoping a "python3" on PATH matches. Forces unbuffered
           stdout (`-u` + `PYTHONUNBUFFERED=1`)--Python fully block-buffers stdout by default when
           it isn't attached to a TTY (true of a subprocess pipe), which would otherwise defeat
           progressive real-time streaming entirely."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        argv = [sys.executable, "-u", str(solution_file)]
        async for event in run_argv_streaming(argv, input_text, timeout=timeout, env=env):
            yield event


LANGUAGE = CgPython3Language()
