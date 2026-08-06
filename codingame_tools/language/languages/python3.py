"""`CgPython3Language`: the concrete `CgLanguage` implementation for CodinGame's "Python3"--see
   `codingame_tools.language.registry` for the discovery contract (`LANGUAGE` below) that finds
   it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator

from .._process import run_argv_streaming
from ..base import DEFAULT_RUN_TIMEOUT_SECONDS, CgLanguage, CgLanguageContext, CgRunEvent
from ..vscode import ACTION_DEBUG, CgVsCodeProvisioning, CgVsCodeRequest, entry_name

__all__ = [
    "CgPython3Language",
    "LANGUAGE",
]

_DEBUG_MODULE = "codingame_tools.debug"
"""The `python -m` entry point that resolves a test case and runs `solution.src` in-process under
   the debugger--see `codingame_tools.test_runner.debug_stdin` for why it must be in-process (a
   subprocess can't be stepped into by a debugger attached to the parent).

   Kind-agnostic, which is the whole reason one configuration can serve a workspace: it works out
   puzzle-vs-contribution from the file it is handed. The two per-kind entry points it wraps
   (`puzzle_manager.debug`, `contribution_manager.debug`) each demand to be told, and that is what
   used to force a configuration per working directory."""


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

    @property
    def supports_vscode(self) -> bool:
        return True

    async def build_vscode_provisioning(self, request: CgVsCodeRequest) -> CgVsCodeProvisioning:
        """A single `debugpy` launch configuration that runs the solution the active editor tab
           belongs to, against that working directory's selected test case.

           **Nothing in it is specific to a working directory**, so it is written once and never
           regenerated--not after an import, not after a language change, not for the next puzzle.
           The two questions a debug launch has to answer are both deferred to launch time:

           - *which working directory*, from VS Code's `${file}` macro, resolved by
             `codingame_tools.debug`; and
           - *which test case*, from that directory's `.meta/selected-test.json`, defaulting to the
             first test case.

           What it replaces was the opposite: a `pickString` of every test case on disk plus, for
           contributions, a local/validator picker, all baked in and all stale the moment the test
           cases changed.

           Passing `${file}` rather than an absolute path also keeps breakpoints bound to the exact
           file the user has open--including when that's the `solution.py` symlink rather than its
           `data/solution.src` target. Same no-realpath invariant
           `codingame_tools.test_runner.debug_stdin` documents.

           No build, so no `preLaunchTask`; no container, so no extra files."""
        return CgVsCodeProvisioning(
                configurations=[
                        {
                            "name": entry_name(self.cg_id, ACTION_DEBUG),
                            "type": "debugpy",
                            "request": "launch",
                            "module": _DEBUG_MODULE,
                            "args": ["${file}"],
                            "console": "integratedTerminal",
                            "justMyCode": True,
                        },
                    ],
                recommended_extensions=["ms-python.python"],
            )

    async def run_streaming(
                self,
                ctx: CgLanguageContext,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> AsyncGenerator[CgRunEvent, None]:
        """Runs `ctx.solution_file` with the *same* Python interpreter this client itself runs under
           (`sys.executable`), rather than hoping a "python3" on PATH matches. Forces unbuffered
           stdout (`-u` + `PYTHONUNBUFFERED=1`)--Python fully block-buffers stdout by default when
           it isn't attached to a TTY (true of a subprocess pipe), which would otherwise defeat
           progressive real-time streaming entirely.

           Python3 needs no build step, so it inherits `CgLanguage.build`'s no-op."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        argv = [sys.executable, "-u", str(ctx.solution_file)]
        async for event in run_argv_streaming(argv, input_text, timeout=timeout, env=env):
            yield event


LANGUAGE = CgPython3Language()
