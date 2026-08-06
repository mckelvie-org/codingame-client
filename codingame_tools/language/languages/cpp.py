"""`CgCppLanguage`: `CgLanguage` for CodinGame's "C++", compiled and run inside Docker so nothing
   has to be installed locally--see `codingame_tools.language.registry` for the discovery contract
   (`LANGUAGE` below) that finds it.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import AsyncGenerator
from pathlib import Path

from .._docker import (
    BUILD_DIR,
    CgDockerError,
    CgToolchain,
    container_name_for,
    docker_exec_argv,
    ensure_toolchain,
    latest_alias_for,
)
from .._process import run_argv_capture, run_argv_streaming
from ..base import (
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_RUN_TIMEOUT_SECONDS,
    CgBuildProfile,
    CgBuildResult,
    CgDebugSession,
    CgLanguage,
    CgLanguageContext,
    CgRunEvent,
)
from ..vscode import (
    ACTION_DEBUG,
    ACTION_START_DEBUG_SESSION,
    ACTION_STOP_DEBUG_SESSION,
    CgVsCodeProvisioning,
    CgVsCodeRequest,
    entry_name,
)

__all__ = [
    "CgCppLanguage",
    "LANGUAGE",
]

LANG_SLUG = "cpp"

CACHED_MARKER = "cg-build:cached"
COMPILED_MARKER = "cg-build:compiled"
"""Machine markers the build script writes to **stdout** (diagnostics go to stderr) so the caller
   can tell a cached no-op from a real compile. Necessary because a clean compile emits no
   diagnostics at all, making it otherwise indistinguishable from the cached path."""

TEMPLATE_VERSION = 1
"""Bumped whenever `TEMPLATE_BODY` changes. An explicit integer rather than the cg package version,
   so upgrading cg without a toolchain change causes no image churn. An unmodified `base.dockerfile`
   older than this is silently regenerated; an edited one is left alone with a warning."""

TEMPLATE_BODY = f"""
ARG CG_BASE_IMAGE=gcc:14
FROM ${{CG_BASE_IMAGE}}

# gdb/gdbserver are for debugging; coreutils supplies the `timeout` and `stdbuf` the run wrapper
# relies on (already present on Debian, named here in case the base image is swapped).
RUN apt-get update \\
    && apt-get install -y --no-install-recommends gdb gdbserver coreutils \\
    && rm -rf /var/lib/apt/lists/*

ENV CG_CXXFLAGS="-std=c++20 -O2 -g -Wall -Wextra"
ENV CG_CXXFLAGS_DEBUG="-std=c++20 -O0 -g3 -Wall -Wextra"

RUN mkdir -p {BUILD_DIR}/run {BUILD_DIR}/debug
WORKDIR {BUILD_DIR}
"""
"""The cg-owned half of the toolchain image. Users add to it in `custom.dockerfile`, which is
   appended verbatim and never touched by cg--so this can be replaced on a template bump without
   any merging. `ARG CG_BASE_IMAGE` and the two `CG_CXXFLAGS*` variables exist so the two most
   likely tweaks don't require editing the base at all (override them in `custom.dockerfile`)."""


def build_script(source: str, profile: CgBuildProfile) -> str:
    """Shell to compile `source` (a path inside the container) into `/build/<profile>/solution`,
       skipping the work entirely when nothing relevant changed.

       Hashes **only the source file**--never a directory tree. `/src` contains
       `.meta/.contribution-git/` (an entire git object database) and `data/tests/`, both of which
       churn on every git operation and would cause constant spurious rebuilds.

       Caches failures as well as successes: rebuilding known-bad source replays the saved
       diagnostics instead of recompiling, so a repeat is cheap and says exactly the same thing.

       Compiler diagnostics go to **stderr**; stdout carries only a `CACHED_MARKER`/`COMPILED_MARKER`
       machine marker. They have to be separable because a clean compile with no warnings says
       nothing at all, which would otherwise be indistinguishable from the cached fast path."""
    flags = "$CG_CXXFLAGS_DEBUG" if profile == "debug" else "$CG_CXXFLAGS"
    out = f"{BUILD_DIR}/{profile}"
    src = shlex.quote(source)
    return f"""
set -u
mkdir -p {out}
if [ ! -f {src} ]; then
    echo "no solution source at {source}" >&2
    exit 2
fi
HASH="$(sha256sum {src} | cut -d' ' -f1)-$(printf '%s' "{flags}" | sha256sum | cut -d' ' -f1)"
if [ "$(cat {out}/ok 2>/dev/null)" = "$HASH" ]; then
    echo {CACHED_MARKER}
    exit 0
fi
if [ "$(cat {out}/fail 2>/dev/null)" = "$HASH" ]; then
    echo {CACHED_MARKER}
    cat {out}/log >&2
    exit 1
fi
echo {COMPILED_MARKER}
if g++ {flags} -x c++ -o {out}/solution {src} >{out}/log 2>&1; then
    printf '%s' "$HASH" >{out}/ok
    rm -f {out}/fail
    cat {out}/log >&2
    exit 0
fi
printf '%s' "$HASH" >{out}/fail
rm -f {out}/ok
cat {out}/log >&2
exit 1
"""


def run_script(timeout: float) -> str:
    """Shell to exec the built binary.

       `timeout` runs **inside** the container because killing the local `docker exec` client does
       not terminate the process inside it--an infinite-looping solution would otherwise survive its
       timeout and keep burning CPU, with runs piling up in a long-lived container. It's set one
       second *beyond* the caller's timeout on purpose: the outer timeout should win the race, so a
       runaway is reported as a clean `timed_out=True` rather than as an opaque exit code 124. This
       is the backstop that guarantees cleanup, not the primary mechanism.

       `stdbuf -o0 -e0` because a C++ binary on a pipe is fully block-buffered, so a solution
       printing a few lines would emit nothing until exit--exactly the problem the Python3 plugin
       solves with `-u`/`PYTHONUNBUFFERED=1`. Without it `run_streaming` would stream nothing."""
    binary = f"{BUILD_DIR}/run/solution"
    return f"""
set -u
if [ ! -x {binary} ]; then
    echo "solution is not built--run \\`cg puzzle build\\` (or \\`cg contribution build\\`) first" >&2
    exit 2
fi
exec timeout -k 1 {int(timeout) + 1} stdbuf -o0 -e0 {binary}
"""


GDBSERVER_PORT = 2345
"""Port `gdbserver` listens on *inside* the container. Never published to the host: the gdb that
   connects also runs inside the container (reached by cppdbg's `pipeTransport`, which shells out to
   `docker exec`), so it dials the container's own localhost. That's what keeps the host's only
   requirement `docker`--no local gdb, no local toolchain, no port juggling between containers."""

DEBUG_STDIN_FILE_NAME = "debug-stdin"
"""Name of the file `start_debug_session` writes into the working directory's `.meta/` to redirect
   the debugged program's stdin from. A copy rather than the test case's own file, so that exactly
   the bytes the caller specified reach the program--see `start_debug_session`."""

_GDBSERVER_LOG = f"{BUILD_DIR}/gdbserver.log"
_GDBSERVER_PID = f"{BUILD_DIR}/gdbserver.pid"

_KILL_PREVIOUS = f"""
if [ -f {_GDBSERVER_PID} ]; then
    kill "$(cat {_GDBSERVER_PID})" 2>/dev/null || true
    rm -f {_GDBSERVER_PID}
fi
"""
"""Terminate a previous gdbserver by **recorded PID**, never by `pkill -f <pattern>`.

   Pattern-matching is a trap here: `docker exec sh -c '<script>'` puts the whole script in the
   shell's own command line, so any pattern naming gdbserver's arguments also matches the shell
   running the script--which promptly kills itself (observed as a mysterious exit code 143). A PID
   file sidesteps that entirely, and needs only `kill`, not procps."""


def start_debug_script(input_file: str) -> str:
    """Shell to (re)start a stopped `gdbserver` for the debug build, with stdin redirected from
       `input_file`.

       The redirection is the reason a debug session is set up by a command of ours rather than left
       to the debug adapter: doing it in a shell we control sidesteps cppdbg's notoriously
       unreliable stdin handling entirely.

       `input_file` is a container path to a file `start_debug_session` wrote itself, *not* the test
       case's own file--see there for why redirecting from the test case would feed the wrong
       bytes."""
    binary = f"{BUILD_DIR}/debug/solution"
    src = shlex.quote(input_file)
    return f"""
set -u
{_KILL_PREVIOUS}
if [ ! -x {binary} ]; then
    echo "debug build missing--build with --profile debug first" >&2
    exit 2
fi
if [ ! -f {src} ]; then
    echo "no such test case input: {input_file}" >&2
    exit 2
fi
rm -f {_GDBSERVER_LOG}
# setsid detaches it from this exec session, which ends as soon as this script returns.
setsid gdbserver :{GDBSERVER_PORT} {binary} <{src} >{_GDBSERVER_LOG} 2>&1 &
echo $! >{_GDBSERVER_PID}
# gdbserver binds and then blocks waiting for a connection; wait until it says so, rather than
# returning optimistically and letting the editor report an opaque "connection refused".
i=0
while [ $i -lt 40 ]; do
    if grep -q "Listening on port" {_GDBSERVER_LOG} 2>/dev/null; then
        exit 0
    fi
    i=$((i + 1))
    sleep 0.25
done
cat {_GDBSERVER_LOG} >&2
exit 1
"""


STOP_DEBUG_SCRIPT = f"""
{_KILL_PREVIOUS}
exit 0
"""
"""Teardown. Always succeeds: it runs from a `postDebugTask`, which fires even when the session
   never really started, so "nothing to kill" is a normal outcome rather than an error."""


def _devcontainer_json(root: Path) -> str:
    """A `devcontainer.json` for "Reopen in Container".

       Purely a convenience for IntelliSense over the container's own headers--none of the run or
       debug functionality needs it, since those drive the container from the host. That's what
       makes it safe to keep under `.meta/` (gitignored, generated, not the user's to maintain)
       even though VS Code won't discover it there on its own: point the Dev Containers extension
       at it explicitly if you want it. It references
       the **already-built image by tag** rather than a `dockerFile` path, which sidesteps pointing
       at Dockerfiles that live outside the folder (they're per-user and global by default).

       Note VS Code mounts the folder at `/workspaces/<name>` here, not at `/src`--harmless for
       IntelliSense, but it's why the generated cppdbg configuration is the host-side one and not
       an in-container variant."""
    content = {
            "name": f"CG {root.name} (C++)",
            "image": latest_alias_for(LANG_SLUG),
            "customizations": {"vscode": {"extensions": ["ms-vscode.cpptools"]}},
            "runArgs": list(_DEVCONTAINER_RUN_ARGS),
        }
    return json.dumps(content, indent=2) + "\n"


_DEVCONTAINER_RUN_ARGS = ("--cap-add=SYS_PTRACE", "--security-opt", "seccomp=unconfined")
"""Same ptrace allowances the cg-managed container gets--so debugging also works if the user does
   reopen the folder in the dev container."""


class CgCppLanguage(CgLanguage):
    """C++ (CodinGame's `cg_id` "C++"), compiled and run in a container so no local toolchain is
       needed. See `codingame_tools.language._docker` for the container/image model."""

    def __init__(self) -> None:
        super().__init__("C++")

    @property
    def extension(self) -> str:
        return "cpp"

    @property
    def comment_prefix(self) -> str:
        return "//"

    def source_path_in_container(self, ctx: CgLanguageContext, profile: CgBuildProfile) -> str:
        """Which path inside the container to compile.

           A **debug** build prefers the `solution.cpp` symlink: g++ records the path it was given
           in the debug info, and that path has to map back to the file the user actually has open
           for breakpoints to bind (the same no-realpath invariant
           `codingame_tools.test_runner.debug_stdin` documents). Otherwise compile
           `data/solution.src` directly.

           The host path *is* the in-container path--the mount root is bind-mounted at its own
           location (see `codingame_tools.language._docker`)--so there is nothing to translate here,
           and the path g++ records in the debug info is one the host debugger can open directly.
           That is what removes `sourceFileMap` from the generated launch configuration.

           Either way `-x c++` is mandatory--g++ doesn't recognize a `.src` extension and would
           treat the file as a linker input ("file format not recognized")."""
        if profile == "debug" and ctx.solution_link is not None:
            return str(ctx.solution_link)
        return str(ctx.solution_file)

    async def _toolchain(self, ctx: CgLanguageContext, *, timeout: float) -> CgToolchain:
        return await ensure_toolchain(
                root=ctx.mount_root, meta_dir=ctx.meta_dir, toolchain_dir=ctx.toolchain_dir,
                lang_slug=LANG_SLUG, template_version=TEMPLATE_VERSION,
                template_body=TEMPLATE_BODY, timeout=timeout,
            )

    async def build(
                self,
                ctx: CgLanguageContext,
                *,
                profile: CgBuildProfile = "run",
                timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
            ) -> CgBuildResult:
        """Compile the solution inside the container, bringing the image and container up first if
           needed. Near-free when the source hasn't changed since the last successful build.

           Compiler diagnostics come back in the result rather than as an exception--a compile error
           is a routine thing to display, not a crash. A Docker problem (no daemon, image build
           failure) is reported the same way, so a caller never has to catch anything here."""
        try:
            toolchain = await self._toolchain(ctx, timeout=timeout)
        except CgDockerError as e:
            return CgBuildResult(ok=False, output=str(e), up_to_date=False)

        result = await run_argv_capture(
                docker_exec_argv(
                    toolchain.container_name,
                    build_script(self.source_path_in_container(ctx, profile), profile)),
                timeout=timeout,
            )
        if result.timed_out:
            return CgBuildResult(
                    ok=False, up_to_date=False,
                    output=f"compiling timed out after {timeout}s (raise --build-timeout if the "
                           "first build is simply slow)",
                )
        compiler_output = result.stderr.strip()
        output = "\n".join([*toolchain.warnings, compiler_output]).strip()
        return CgBuildResult(
                ok=result.ok, output=output,
                up_to_date=result.ok and CACHED_MARKER in result.stdout,
            )

    async def run_streaming(
                self,
                ctx: CgLanguageContext,
                input_text: str,
                *,
                timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS,
            ) -> AsyncGenerator[CgRunEvent, None]:
        """Run the already-built binary in the container, streaming its output.

           Does **not** build--that's a separate step (see `CgLanguage.build`). It does ensure the
           container is up, since losing the container also loses the artifacts that live inside it;
           if the binary is missing, the run fails with a message saying to build first."""
        toolchain = await self._toolchain(ctx, timeout=DEFAULT_BUILD_TIMEOUT_SECONDS)
        argv = docker_exec_argv(toolchain.container_name, run_script(timeout), interactive=True)
        async for event in run_argv_streaming(argv, input_text, timeout=timeout):
            yield event

    async def start_debug_session(
                self,
                ctx: CgLanguageContext,
                stdin_text: str,
                *,
                timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
            ) -> CgDebugSession:
        """Build the debug profile and start a stopped `gdbserver` fed by `stdin_text`.

           `stdin_text` is written to `<meta_dir>/debug-stdin` and redirected from there rather than
           from the test case's own file. Copying is not incidental: a contribution's test-case file
           carries a final newline this client added (see `common.text_files`), and redirecting from
           it would put one extra byte on stdin--diverging from `cg contribution play` and from
           CodinGame, which appends nothing. A copy also drops the requirement that the caller's file
           live inside the working directory, since this one does by construction.

           `meta_dir` is the natural home: it's gitignored scratch space and it sits inside `root`,
           which sits inside the mount root--so it's already visible inside the container at the
           same path, with no extra plumbing."""
        build_result = await self.build(ctx, profile="debug", timeout=timeout)
        if not build_result.ok:
            return CgDebugSession(ok=False, output=build_result.output)
        stdin_file = ctx.meta_dir / DEBUG_STDIN_FILE_NAME
        stdin_file.parent.mkdir(parents=True, exist_ok=True)
        stdin_file.write_text(stdin_text, encoding="utf-8")
        toolchain = await self._toolchain(ctx, timeout=timeout)
        result = await run_argv_capture(
                docker_exec_argv(
                    toolchain.container_name, start_debug_script(str(stdin_file))),
                timeout=timeout,
            )
        if not result.ok:
            return CgDebugSession(
                    ok=False, output=(result.combined.strip() or "failed to start gdbserver"))
        return CgDebugSession(
                ok=True, output=build_result.output,
                details={
                    "container": toolchain.container_name,
                    "address": f"localhost:{GDBSERVER_PORT}",
                    "program": f"{BUILD_DIR}/debug/solution",
                },
            )

    async def stop_debug_session(self, ctx: CgLanguageContext) -> None:
        """Kill any `gdbserver` left running. Never raises--including when Docker is unavailable or
           the container is already gone, since this runs from a `postDebugTask`."""
        try:
            toolchain = await self._toolchain(ctx, timeout=DEFAULT_BUILD_TIMEOUT_SECONDS)
        except CgDockerError:
            return
        await run_argv_capture(
                docker_exec_argv(toolchain.container_name, STOP_DEBUG_SCRIPT), timeout=60.0)

    @property
    def supports_vscode(self) -> bool:
        return True

    async def build_vscode_provisioning(self, request: CgVsCodeRequest) -> CgVsCodeProvisioning:
        """A single `cppdbg` configuration that attaches to the in-container `gdbserver`, plus the
           tasks that start and stop it and a `devcontainer.json` for IntelliSense.

           **Nothing in it is specific to a working directory**, so it is written once and never
           regenerated. Three things used to make that impossible, and each is now resolved at
           launch time instead of baked in:

           - *Which test case.* Was a `pickString` of everything on disk (plus a local/validator
             picker for contributions), stale the moment tests changed. Now `cg debug start` reads
             the working directory's `.meta/selected-test.json`.
           - *Which working directory.* Was `--puzzle-dir`/`--contribution-dir` with an absolute
             path. Now `--file ${file}`, from which `cg debug start` infers both the kind and the
             root.
           - *Which container.* Was named per working directory. The container is now per
             (workspace x language)--see `codingame_tools.language._docker.container_name_for`--so
             its name is the same for every working directory the configuration serves.

           gdb runs *inside* the container too, reached via `pipeTransport` shelling out to `docker
           exec`--so the host needs nothing but Docker. `miDebuggerServerAddress` is then the
           container's own localhost, which is why no port is published.

           There is no `sourceFileMap`: the workspace is mounted at its own path, so the paths gdb
           recorded are already the paths VS Code has open. The debug build compiles the
           `solution.<ext>` symlink specifically so that path is the one the user is looking at.

           The tasks pass `${workspaceFolder}` explicitly rather than letting cg guess the mount
           root, so VS Code's real workspace wins over `find_workspace_root`'s heuristic. A mismatch
           is self-correcting rather than broken: the mount is part of the container spec hash, so a
           differently-mounted container is recreated rather than reused."""
        container = container_name_for(LANG_SLUG, request.workspace_root)
        target = '--file "${file}" --workspace-root "${workspaceFolder}"'

        return CgVsCodeProvisioning(
                configurations=[
                        {
                            "name": entry_name(self.cg_id, ACTION_DEBUG),
                            "type": "cppdbg",
                            "request": "launch",
                            "program": f"{BUILD_DIR}/debug/solution",
                            "cwd": BUILD_DIR,
                            "MIMode": "gdb",
                            "miDebuggerPath": "/usr/bin/gdb",
                            "miDebuggerServerAddress": f"localhost:{GDBSERVER_PORT}",
                            "stopAtEntry": True,
                            "externalConsole": False,
                            "pipeTransport": {
                                "pipeProgram": "docker",
                                "pipeArgs": ["exec", "-i", container, "sh", "-c"],
                                "debuggerPath": "/usr/bin/gdb",
                                "pipeCwd": "",
                            },
                            "preLaunchTask": entry_name(self.cg_id, ACTION_START_DEBUG_SESSION),
                            "postDebugTask": entry_name(self.cg_id, ACTION_STOP_DEBUG_SESSION),
                        },
                    ],
                tasks=[
                        {
                            "label": entry_name(self.cg_id, ACTION_START_DEBUG_SESSION),
                            "type": "shell",
                            "command": f"cg debug start {target}",
                            "presentation": {"reveal": "silent", "panel": "shared"},
                            "problemMatcher": [],
                        },
                        {
                            "label": entry_name(self.cg_id, ACTION_STOP_DEBUG_SESSION),
                            "type": "shell",
                            "command": f"cg debug stop {target}",
                            "presentation": {"reveal": "never", "panel": "shared"},
                            "problemMatcher": [],
                        },
                    ],
                files={
                    # Under .meta/, not the working directory root: this file is generated, never
                    # hand-edited, and .meta/ is the one place already gitignored -- at the root it
                    # would be committed into whatever repository tracks the working directory.
                    # Costs automatic "Reopen in Container" discovery, which only ever offered
                    # IntelliSense over the container's headers; nothing about running or debugging
                    # goes through it (see _devcontainer_json).
                    f"{request.ctx.meta_dir.relative_to(request.ctx.root).as_posix()}/.devcontainer/devcontainer.json":
                        _devcontainer_json(request.workspace_root),
                },
                # Written at the working directory root through 1.0.x, before .meta/ was settled on
                # as the home for generated files. Left behind it is untracked clutter offering a
                # stale "Reopen in Container".
                obsolete_files=[".devcontainer/devcontainer.json"],
                recommended_extensions=["ms-vscode.cpptools"],
            )


LANGUAGE = CgCppLanguage()
