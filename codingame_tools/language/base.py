"""`CgLanguage`: the abstract interface every per-language plugin implements, and the *only*
   interface outside code should use to access language-specific behavior--see the package
   docstring (`codingame_tools.language`) for the discovery/registry mechanism that produces
   instances of this.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = [
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "CgLanguage",
    "CgLanguageOperationNotSupportedError",
    "CgRunStream",
    "CgRunOutputChunk",
    "CgRunResult",
    "CgRunFinished",
    "CgRunEvent",
]

DEFAULT_RUN_TIMEOUT_SECONDS = 10.0
"""Default wall-clock timeout for a single local run--a solution under active development can
   easily infinite-loop; this keeps a bad run from hanging indefinitely rather than reporting it
   as a (timed-out) failure."""

CgRunStream = Literal["stdout", "stderr"]


@dataclass(frozen=True)
class CgRunOutputChunk:
    """A piece of output produced by a running solution, as soon as it's available.

       stdout and stderr are two independent, separately-buffered OS pipes--`stream` says which
       one this chunk came from, but the *order* two chunks from different streams are yielded in
       is only the order this reader happened to receive them, not a guarantee about the target
       process's true relative write order between the two streams. Treat the two streams as
       separate; don't rely on cross-stream ordering."""

    stream: CgRunStream
    text: str


@dataclass(frozen=True)
class CgRunResult:
    """The outcome of running a solution file against one input, once it's finished."""

    output: str
    """Everything the solution wrote to stdout."""

    stderr: str
    """Everything the solution wrote to stderr--not treated as failure by itself (a solution may
       legitimately write debug output there), but surfaced for inspection when a run does fail."""

    returncode: int
    """The subprocess's exit code (0 conventionally means "ran without crashing"). Meaningless
       (always -1) when `timed_out` is True."""

    timed_out: bool
    """Whether the run was killed for exceeding its timeout (see `DEFAULT_RUN_TIMEOUT_SECONDS`).
       `output`/`stderr` hold whatever was captured before the kill."""


@dataclass(frozen=True)
class CgRunFinished:
    """The final event yielded by `CgLanguage.run_streaming()`--every run ends with exactly one
       of these, carrying the same aggregated result `CgLanguage.run()` returns."""

    result: CgRunResult


CgRunEvent = CgRunOutputChunk | CgRunFinished
"""What `CgLanguage.run_streaming()` yields: zero or more `CgRunOutputChunk`s as they're produced,
   followed by exactly one `CgRunFinished`."""


class CgLanguage(ABC):  # noqa: B024 -- deliberately no @abstractmethod; see docstring below.
    """A single CodinGame-supported programming language's behavior: how to run a solution
       locally, its file extension, its single-line-comment syntax, and a starter stub for a
       freshly-created contribution.

       Deliberately has no `@abstractmethod`s: "not supported by this language yet" is the
       expected, common state (true for every language but Python3 today, and will stay true
       incrementally as languages are added one capability at a time), so every capability below
       has a graceful base-class default (raise, for the one genuinely load-bearing operation;
       `None`, for everything else) rather than forcing every new minimal language plugin to
       write boilerplate "not implemented" overrides. `ABC` here is used in the structural/
       documentation sense--don't construct this directly; use a language plugin's own singleton
       or `codingame_tools.language.get_language()`/`get_language_by_extension()`.
    """

    def __init__(self, cg_id: str) -> None:
        self._cg_id = cg_id

    @property
    def cg_id(self) -> str:
        """CodinGame's own canonical identifier for this language, e.g. "Python3", "Java",
           "C++"--the exact string used in `TestSession/play`/`TestSession/submit`'s
           `programmingLanguageId`, and a contribution's `solutionLanguage`
           (`createContribution`/`updateContribution`)."""
        return self._cg_id

    @property
    def extension(self) -> str | None:
        """The file extension (no leading dot, e.g. "py") conventionally used for this
           language's solution source, or `None` if not known. Base implementation: `None`."""
        return None

    @property
    def comment_prefix(self) -> str | None:
        """The single-line-comment prefix for this language's source syntax (e.g. "#" for
           Python3), or `None` if not known. Base implementation: `None`. See `format_comment`."""
        return None

    def format_comment(self, text: str) -> str | None:
        """Format `text` as a single-line comment in this language's syntax, or `None` if
           `comment_prefix` isn't known for this language--callers must treat `None` as "no safe
           placeholder text can be generated," not substitute a guessed comment syntax."""
        prefix = self.comment_prefix
        return None if prefix is None else f"{prefix} {text}"

    async def build_contribution_create_stub_source(self) -> str | None:
        """Build a trivial, real, working starter `data/solution.src` for `cg contribution
           create` that passes the seeded title-only test/validator pair (input `"1"` -> output
           `"1"`), or `None` if this language has no such stub yet (the working directory's
           `solution.src` is then left empty/unwritten).

           Async so a plugin is free to do real work to produce this (render a template, consult
           a language service) rather than only ever returning a fixed string. Base
           implementation: `None`."""
        return None

    def run_streaming(
                self,
                solution_file: Path,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> AsyncIterator[CgRunEvent]:
        """Run `solution_file` as a subprocess, feeding `input_text` to stdin, yielding
           `CgRunOutputChunk`s tagged by stream as they're produced and ending with exactly one
           `CgRunFinished` carrying the aggregated `CgRunResult`. See `CgRunOutputChunk` for the
           stdout/stderr ordering caveat.

        Raises:
            CgLanguageOperationNotSupportedError: the base implementation always raises this,
                                                   immediately (not lazily on iteration); only a
                                                   language that actually supports local
                                                   execution overrides it.
        """
        raise CgLanguageOperationNotSupportedError(self, "run_streaming")

    async def run(
                self,
                solution_file: Path,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> CgRunResult:
        """Convenience wrapper for a caller that doesn't need progressive output: drains
           `run_streaming()` and returns its final `CgRunResult`. Not overridden by any language
           plugin--every plugin gets this for free once it implements `run_streaming()`.

        Raises:
            CgLanguageOperationNotSupportedError: see `run_streaming()`.
        """
        async for event in self.run_streaming(solution_file, input_text, timeout=timeout):
            if isinstance(event, CgRunFinished):
                return event.result
        raise AssertionError("run_streaming() ended without a CgRunFinished event")


class CgLanguageOperationNotSupportedError(Exception):
    """Raised by a `CgLanguage` method whose base-class default means "not implemented for this
       language yet" (currently only `run_streaming`/`run`). Callers are expected to catch and
       handle this directly--there's no manager-specific translation wrapper."""

    def __init__(self, language: CgLanguage, operation: str) -> None:
        self.cg_id = language.cg_id
        self.operation = operation
        super().__init__(f"{language.cg_id!r} does not support {operation!r} yet.")
