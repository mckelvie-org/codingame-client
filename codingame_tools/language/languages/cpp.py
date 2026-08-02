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
    SRC_MOUNT_DIR,
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
from ..vscode import CgVsCodeProvisioning, CgVsCodeRequest, owner_name, owner_slug

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
       unreliable stdin handling entirely. Test-case input files are already real files on disk and
       visible inside the read-only `/src` mount, so nothing has to be copied in."""
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
       debug functionality needs it, since those drive the container from the host. It references
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

           Either way `-x c++` is mandatory--g++ doesn't recognize a `.src` extension and would
           treat the file as a linker input ("file format not recognized")."""
        if profile == "debug" and ctx.solution_link is not None:
            return f"{SRC_MOUNT_DIR}/{ctx.solution_link.name}"
        relative = ctx.solution_file.relative_to(ctx.root)
        return f"{SRC_MOUNT_DIR}/{relative.as_posix()}"

    async def _toolchain(self, ctx: CgLanguageContext, *, timeout: float) -> CgToolchain:
        return await ensure_toolchain(
                root=ctx.root, meta_dir=ctx.meta_dir, toolchain_dir=ctx.toolchain_dir,
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
                input_file: Path,
                *,
                timeout: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
            ) -> CgDebugSession:
        """Build the debug profile and start a stopped `gdbserver` with `input_file` as stdin.

           `input_file` must live inside the working directory (test-case inputs do), since the
           container only sees `/src`."""
        build_result = await self.build(ctx, profile="debug", timeout=timeout)
        if not build_result.ok:
            return CgDebugSession(ok=False, output=build_result.output)
        try:
            relative = input_file.resolve().relative_to(ctx.root)
        except ValueError:
            return CgDebugSession(
                    ok=False,
                    output=f"{input_file} is outside {ctx.root}, so it isn't visible inside the "
                           "container (only the working directory is mounted).",
                )
        toolchain = await self._toolchain(ctx, timeout=timeout)
        result = await run_argv_capture(
                docker_exec_argv(
                    toolchain.container_name,
                    start_debug_script(f"{SRC_MOUNT_DIR}/{relative.as_posix()}")),
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

    async def build_vscode_provisioning(self, request: CgVsCodeRequest) -> CgVsCodeProvisioning:
        """A `cppdbg` configuration that attaches to the in-container `gdbserver`, plus the tasks
           that start and stop it and a `devcontainer.json` for IntelliSense.

           gdb runs *inside* the container too, reached via `pipeTransport` shelling out to `docker
           exec`--so the host needs nothing but Docker. `miDebuggerServerAddress` is then the
           container's own localhost, which is why no port is published.

           `sourceFileMap` maps `/src` to the working directory as an **absolute host path**, not
           `${workspaceFolder}`: the workspace root is usually a parent of the working directory
           (see `codingame_tools.language.vscode`), so `${workspaceFolder}` would point at the wrong
           place. The debug build compiles the `solution.<ext>` symlink specifically so the path gdb
           records maps back onto the file the user has open."""
        ctx = request.ctx
        prefix = owner_name(ctx.root)
        slug = owner_slug(ctx.root)
        test_input_id = f"cg_{slug}_testCase"
        cg_args = f"--puzzle-dir {shlex.quote(str(ctx.root))}"
        debug_command = "puzzle" if request.kind == "puzzle" else "contribution"
        if request.kind == "contribution":
            cg_args = f"--contribution-dir {shlex.quote(str(ctx.root))}"
        container = container_name_for(LANG_SLUG, ctx.root)

        inputs: list[dict[str, object]] = [
                {
                    "id": test_input_id,
                    "type": "pickString",
                    "description": f"Test case to debug {ctx.root.name}'s solution against",
                    "options": [
                            {"label": f"{tc.id}: {tc.label}", "value": tc.id}
                            for tc in request.test_cases
                        ],
                },
            ]
        start_args = f"{cg_args} debug start ${{input:{test_input_id}}}"
        if request.kind == "contribution":
            side_input_id = f"cg_{slug}_side"
            inputs.append({
                    "id": side_input_id,
                    "type": "pickString",
                    "description": "Test case side",
                    "options": ["local", "validator"],
                })
            start_args = (
                    f"{cg_args} debug start ${{input:{test_input_id}}} ${{input:{side_input_id}}}")

        return CgVsCodeProvisioning(
                configurations=[
                        {
                            "name": f"{prefix}Debug solution against test case",
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
                            "sourceFileMap": {SRC_MOUNT_DIR: str(ctx.root)},
                            "preLaunchTask": f"{prefix}start debug session",
                            "postDebugTask": f"{prefix}stop debug session",
                        },
                    ],
                inputs=inputs,
                tasks=[
                        {
                            "label": f"{prefix}start debug session",
                            "type": "shell",
                            "command": f"cg {debug_command} {start_args}",
                            "presentation": {"reveal": "silent", "panel": "shared"},
                            "problemMatcher": [],
                        },
                        {
                            "label": f"{prefix}stop debug session",
                            "type": "shell",
                            "command": f"cg {debug_command} {cg_args} debug stop",
                            "presentation": {"reveal": "never", "panel": "shared"},
                            "problemMatcher": [],
                        },
                    ],
                files={
                    ".devcontainer/devcontainer.json": _devcontainer_json(ctx.root),
                },
                recommended_extensions=["ms-vscode.cpptools"],
            )


LANGUAGE = CgCppLanguage()
