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
from ..vscode import CgVsCodeProvisioning, CgVsCodeRequest, owner_name, owner_slug

__all__ = [
    "CgPython3Language",
    "LANGUAGE",
]

_DEBUG_MODULE = {
        "puzzle": "codingame_tools.puzzle_manager.debug",
        "contribution": "codingame_tools.contribution_manager.debug",
    }
"""The `python -m` entry point that resolves a test case and runs `solution.src` in-process under
   the debugger--see `codingame_tools.test_runner.debug_stdin` for why it must be in-process (a
   subprocess can't be stepped into by a debugger attached to the parent)."""


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

    async def build_vscode_provisioning(self, request: CgVsCodeRequest) -> CgVsCodeProvisioning:
        """A `debugpy` launch configuration that runs `data/solution.src` against a test case
           picked from a dropdown, plus the dropdown(s) feeding it.

           The test-case list is generated from what's actually on disk, which is the point: the
           hand-written configuration this replaces carried a note telling you to regenerate its
           25-entry list by hand after every `cg puzzle import`.

           Passes VS Code's `${file}` macro as the target rather than an absolute path, so the
           debugger binds breakpoints to the exact file the user has open--including when that's
           the `solution.py` symlink rather than its `data/solution.src` target. That's the same
           no-realpath invariant `codingame_tools.test_runner.debug_stdin` documents, and it also
           means one configuration works for every Python working directory in the workspace.

           No build, so no `preLaunchTask`; no container, so no extra files."""
        prefix = owner_name(request.ctx.root)
        slug = owner_slug(request.ctx.root)
        kind = request.kind
        index_input_id = f"cg_{slug}_testCase"
        inputs = [
                {
                    "id": index_input_id,
                    "type": "pickString",
                    "description": f"Test case to run {request.ctx.root.name}'s solution against",
                    "options": [
                            {"label": f"{tc.id}: {tc.label}", "value": tc.id}
                            for tc in request.test_cases
                        ],
                },
            ]
        args: list[str] = ["${file}", f"${{input:{index_input_id}}}"]
        if kind == "contribution":
            # Local vs validator is a fixed two-way choice, kept as its own picker rather than
            # multiplying every ordinal by two in a single list.
            side_input_id = f"cg_{slug}_side"
            inputs.append({
                    "id": side_input_id,
                    "type": "pickString",
                    "description": "Test case side",
                    "options": ["local", "validator"],
                })
            args.append(f"${{input:{side_input_id}}}")
        return CgVsCodeProvisioning(
                configurations=[
                        {
                            "name": f"{prefix}Debug solution against test case",
                            "type": "debugpy",
                            "request": "launch",
                            "module": _DEBUG_MODULE[kind],
                            "args": args,
                            "console": "integratedTerminal",
                            "justMyCode": True,
                        },
                    ],
                inputs=inputs,
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
