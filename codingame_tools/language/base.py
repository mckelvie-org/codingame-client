"""`CgLanguage`: the abstract interface every per-language plugin implements, and the *only*
   interface outside code should use to access language-specific behavior--see the package
   docstring (`codingame_tools.language`) for the discovery/registry mechanism that produces
   instances of this.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .vscode import CgVsCodeProvisioning, CgVsCodeRequest

__all__ = [
    "TOOLCHAIN_SUBDIR_NAME",
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "DEFAULT_BUILD_TIMEOUT_SECONDS",
    "CgLanguage",
    "CgLanguageContext",
    "CgLanguageOperationNotSupportedError",
    "CgBuildProfile",
    "CgBuildResult",
    "CgDebugSession",
    "CgRunStream",
    "CgRunOutputChunk",
    "CgRunResult",
    "CgRunFinished",
    "CgRunEvent",
]

TOOLCHAIN_SUBDIR_NAME = "docker"
"""Name of the per-user global toolchain directory under the cg data dir--see
   `CgLanguageContext.toolchain_dir`."""

DEFAULT_RUN_TIMEOUT_SECONDS = 10.0
"""Default wall-clock timeout for a single local run--a solution under active development can
   easily infinite-loop; this keeps a bad run from hanging indefinitely rather than reporting it
   as a (timed-out) failure."""

DEFAULT_BUILD_TIMEOUT_SECONDS = 120.0
"""Default wall-clock timeout for `CgLanguage.build`--deliberately far more generous than
   `DEFAULT_RUN_TIMEOUT_SECONDS`, because a cold build can involve pulling/building a container
   image and compiling from scratch. Keeping the two separate is the whole reason building is its
   own step: a slow first compile must never be reported as a test case timing out."""

CgRunStream = Literal["stdout", "stderr"]

CgBuildProfile = Literal["run", "debug"]
"""Which flavor of build to produce. `"run"` is for normal local test execution; `"debug"` is built
   for debuggability instead of speed (no optimization, full symbols) and may compile from a
   different source path so a debugger's recorded paths map back to the file the user actually has
   open. Interpreted languages ignore this entirely."""


@dataclass(frozen=True)
class CgLanguageContext:
    """Everything a `CgLanguage` needs to know about *where* a solution lives, independent of any
       particular run.

       Deliberately **infallible and identity-free**: constructing one must never require a working
       directory to have been imported (no reading `puzzle.json`/`contribution.json`, no network, no
       failure modes). A manager can hand one out for a directory holding nothing but a solution
       file. `input_text`/`timeout` are deliberately *not* here--those are per-call, not per-context,
       and folding them in would defeat the "build once, run many" split."""

    root: Path
    """The puzzle/contribution working directory root (resolved absolute)--the directory holding
       `data/`, `.meta/`, and the `solution.<ext>` symlink. For a containerized language this is the
       mount source, which is why it's the root and not just `data/`."""

    solution_file: Path
    """`<root>/data/solution.src`--the one real, editable, submittable file."""

    solution_link: Path | None
    """`<root>/solution.<ext>` (the convenience symlink to `solution_file`) if it currently exists,
       else `None`. Kept distinct from `solution_file` because a debug build wants to compile *this*
       path when available: it's the path the user actually has open in an editor, so it's the one a
       debugger's recorded source paths need to match (same reasoning as
       `codingame_tools.test_runner.debug_stdin`'s no-realpath rule)."""

    meta_dir: Path
    """The working directory's `.meta/`--gitignored scratch space. Used for per-root toolchain
       overrides. Note this is *not* always `<root>/.meta`: a contribution whose git-dir lives in
       `data/` puts it at `<root>/data/.meta`."""

    toolchain_dir: Path
    """The per-user global toolchain directory (`<cg data dir>/docker`), holding the shared,
       user-tweakable per-language image definitions. Global rather than per-root so that tweaking a
       language's toolchain once applies to every puzzle and contribution using that language."""


@dataclass(frozen=True)
class CgDebugSession:
    """A running, ready-to-attach debug target--see `CgLanguage.start_debug_session`."""

    ok: bool
    """Whether the target actually came up. A *result* rather than an exception for the same reason
       `CgBuildResult` is: this is driven by an editor's preLaunchTask, where a failed build is a
       routine outcome that needs displaying, not a crash."""

    output: str
    """What to show the user--build diagnostics when startup failed, otherwise usually empty."""

    details: dict[str, str] = field(default_factory=dict)
    """Language-specific facts the editor's launch configuration needs, e.g. the container name and
       the address `gdbserver` is listening on. Deliberately untyped: what a debug adapter needs
       varies enough per language that a fixed schema would be wrong for the second one."""


@dataclass(frozen=True)
class CgBuildResult:
    """The outcome of `CgLanguage.build`.

       A *result*, never an exception, even on failure: a compile error is an expected, routine
       outcome that callers need to display (not a crash), and raising would make
       `cg puzzle play`--which does not wrap its loop in a try/except--traceback on a typo."""

    ok: bool
    """Whether a usable artifact now exists. Always True for languages that need no build."""

    output: str
    """Compiler/build diagnostics (warnings even on success, errors on failure). Empty when there
       was nothing to do. Never contains program output--build is a separate subprocess from run
       precisely so that build noise can never contaminate a solution's stdout."""

    up_to_date: bool
    """True when nothing had to be rebuilt because the source was unchanged since the last
       successful build. Lets a caller stay quiet on the common no-op path."""


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

    async def start_debug_session(
                self,
                ctx: CgLanguageContext,
                input_file: Path,
                *,
                timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
            ) -> CgDebugSession:
        """Get the solution ready to be attached to by a debugger, with `input_file` as its stdin,
           and return how to reach it.

           For a compiled, containerized language this builds the debug profile and starts a stopped
           `gdbserver`; the editor then attaches. Languages whose debugger launches the program
           itself (Python3, via `debugpy` running `codingame_tools.puzzle_manager.debug`) don't need
           this at all and leave it unimplemented.

           Feeding stdin from a *file* is the whole reason this exists as a separate step: it lets
           the redirection happen in a command we control, rather than relying on a debug adapter's
           own stdin handling.

        Raises:
            CgLanguageOperationNotSupportedError: base implementation always raises.
        """
        raise CgLanguageOperationNotSupportedError(self, "start_debug_session")

    async def stop_debug_session(self, ctx: CgLanguageContext) -> None:
        """Tear down whatever `start_debug_session` started. Idempotent, and safe to call when
           nothing is running--it's wired to a `postDebugTask`, which fires even if the session
           never really began. Base implementation: no-op, so a language that needs no teardown
           inherits correct behavior."""
        return None

    async def build_vscode_provisioning(self, request: CgVsCodeRequest) -> CgVsCodeProvisioning | None:
        """Describe the VS Code run/debug configuration this language wants for the working
           directory in `request`, or `None` if it has no editor integration yet.

           Returns a description; it does not write anything. Where the files go and how they merge
           with the user's existing config is `codingame_tools.language.vscode`'s job--a plugin
           deliberately has no say in (and no knowledge of) workspace-root resolution.

           Base implementation: `None`."""
        return None

    async def build(
                self,
                ctx: CgLanguageContext,
                *,
                profile: CgBuildProfile = "run",
                timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
            ) -> CgBuildResult:
        """Produce whatever artifact `run_streaming()` needs, if this language needs one at all.

           A **separate, explicit step** rather than something `run_streaming()` does implicitly, so
           that a caller can display build diagnostics separately from program output, report a
           compile error once instead of once per test case, and give building its own (much more
           generous) timeout. It must be cheap to call repeatedly: a language that compiles is
           expected to detect that the source is unchanged since the last successful build and
           return `up_to_date=True` having done nothing.

           Base implementation: an immediate no-op success, which is correct for every interpreted
           language.

        Returns:
            A `CgBuildResult`. Never raises on a *build* failure (a compile error is a routine
            outcome, not a crash)--check `.ok`.
        """
        return CgBuildResult(ok=True, output="", up_to_date=True)

    def run_streaming(
                self,
                ctx: CgLanguageContext,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> AsyncIterator[CgRunEvent]:
        """Run the solution described by `ctx`, feeding `input_text` to stdin, yielding
           `CgRunOutputChunk`s tagged by stream as they're produced and ending with exactly one
           `CgRunFinished` carrying the aggregated `CgRunResult`. See `CgRunOutputChunk` for the
           stdout/stderr ordering caveat.

           Does **not** build. A language that needs a build artifact expects `build()` to have been
           called first and should fail cleanly if it hasn't.

        Raises:
            CgLanguageOperationNotSupportedError: the base implementation always raises this,
                                                   immediately (not lazily on iteration); only a
                                                   language that actually supports local
                                                   execution overrides it.
        """
        raise CgLanguageOperationNotSupportedError(self, "run_streaming")

    async def run(
                self,
                ctx: CgLanguageContext,
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
        async for event in self.run_streaming(ctx, input_text, timeout=timeout):
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
