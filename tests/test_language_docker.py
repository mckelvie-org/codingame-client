"""Tests for `codingame_tools.language._docker` and the C++ plugin built on it.

Split in two:

- The pure tests (naming, Dockerfile templating/versioning, generated shell scripts) need no
  Docker at all and run under the default `pdm run test` invocation.
- The integration tests are marked `docker` and **excluded by default** (see `pyproject.toml`'s
  `addopts`), because they build a real image--a cold first run pulls `gcc:14`--and need a running
  daemon. They additionally carry a `skipif` over a cached `docker info` probe, so that even when
  explicitly selected with `-m docker` they skip cleanly rather than failing on a machine where the
  daemon is down. Marker alone would mean CI never probes; skipif alone would spawn a probe
  subprocess on every collection.

  Run them with: `pdm run pytest -m docker`
"""

from __future__ import annotations

import asyncio
import functools
import json
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from codingame_tools.language import (
    CgLanguageContext,
    CgVsCodeRequest,
    get_language,
)
from codingame_tools.language._docker import (
    BASE_DOCKERFILE_NAME,
    CUSTOM_DOCKERFILE_NAME,
    clean_managed,
    compose_dockerfile,
    container_create_argv,
    container_name_for,
    container_spec_hash,
    containers_for_root,
    docker_exec_argv,
    ensure_base_dockerfile,
    ensure_container,
    image_tag_for,
    latest_alias_for,
    list_managed_containers,
    list_managed_images,
    read_base_dockerfile_state,
    remove_containers_for_root,
    render_base_dockerfile,
    resolve_toolchain_dir,
)
from codingame_tools.language.languages.cpp import (
    CACHED_MARKER,
    DEBUG_STDIN_CONTAINER_PATH,
    DEBUG_STDIN_FILE_NAME,
    LANG_SLUG,
    TEMPLATE_BODY,
    TEMPLATE_VERSION,
    build_script,
    run_script,
    target_architecture,
)


@functools.cache
def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
                ["docker", "info"], capture_output=True, timeout=30, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")

ECHO_DOUBLE = """\
#include <iostream>
int main() { int n; std::cin >> n; std::cout << n * 2 << std::endl; }
"""


@pytest.fixture(autouse=True)
def _remove_test_container(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[None]:
    """Remove the container a `docker`-marked test created.

       Containers are named deterministically from the mount root, and every test gets a fresh
       `tmp_path`, so without this each run leaves one container per test behind forever. Scoped to
       `docker`-marked tests only--running `docker rm` after every pure test would add a subprocess
       to each of them for nothing."""
    yield
    if request.node.get_closest_marker("docker") is None or not _docker_available():
        return
    subprocess.run(
            ["docker", "rm", "-f", container_name_for(LANG_SLUG, tmp_path.resolve())],
            capture_output=True, timeout=60, check=False)


def _ctx(tmp_path: Path, source: str) -> CgLanguageContext:
    root = tmp_path / "puzzle"
    (root / "data").mkdir(parents=True)
    solution = root / "data" / "solution.src"
    solution.write_text(source)
    link = root / "solution.cpp"
    link.symlink_to(Path("data") / "solution.src")
    return CgLanguageContext(
            root=root, solution_file=solution, solution_link=link,
            meta_dir=root / ".meta", toolchain_dir=tmp_path / "toolchain",
            # The enclosing workspace, not the working directory--see _docker's mount-root comment.
            mount_root=tmp_path,
        )


# --- naming (pure) --------------------------------------------------------------------------


def test_image_tag_is_content_addressed() -> None:
    """Keying on Dockerfile content, not on the working directory, is what lets every root share one
       image and makes any edit produce a new tag automatically."""
    assert image_tag_for("cpp", "FROM gcc:14\n") == image_tag_for("cpp", "FROM gcc:14\n")
    assert image_tag_for("cpp", "FROM gcc:14\n") != image_tag_for("cpp", "FROM gcc:13\n")
    assert image_tag_for("cpp", "x").startswith("cg-cpp:")


def test_containers_remove_themselves_when_they_stop(tmp_path: Path) -> None:
    """`--rm` is what keeps a container that stops for any reason--`docker kill`, Docker Desktop
       quitting, a reboot--from lingering as a stopped husk in `docker ps -a`. Verified against real
       Docker: without it, killing one leaves `Exited (137)` behind forever.

       Safe because the container holds only build artifacts, so losing it costs a rebuild."""
    assert "--rm" in container_create_argv(tmp_path, "cg-cpp-x")


def test_container_name_is_per_mount_root_and_docker_safe(tmp_path: Path) -> None:
    """Per mount root--i.e. per workspace--so every working directory in a workspace shares one
       container, which is what lets the generated launch configuration name it and stay static."""
    a = container_name_for("cpp", tmp_path / "one")
    b = container_name_for("cpp", tmp_path / "two")
    assert a != b
    # Docker names can't contain "/", which is why the path is hashed rather than embedded.
    assert "/" not in a
    assert a.startswith("cg-cpp-")


# --- Dockerfile templating and versioning (pure) ---------------------------------------------


def test_a_freshly_written_base_is_recognized_as_unedited(tmp_path: Path) -> None:
    path = tmp_path / BASE_DOCKERFILE_NAME
    path.write_text(render_base_dockerfile("cpp", 3, "FROM gcc:14\n"))

    state = read_base_dockerfile_state(path, "cpp")

    assert state.exists
    assert state.version == 3
    assert not state.edited


def test_editing_the_body_is_detected(tmp_path: Path) -> None:
    path = tmp_path / BASE_DOCKERFILE_NAME
    path.write_text(render_base_dockerfile("cpp", 3, "FROM gcc:14\n") + "RUN echo hi\n")

    assert read_base_dockerfile_state(path, "cpp").edited


def test_a_body_starting_with_a_blank_line_is_not_mistaken_for_edited(tmp_path: Path) -> None:
    """Regression: the header regex used `\\s*$`, which in MULTILINE mode happily consumed the
       header's own trailing newline and matched `$` at the next line's end. That pushed the body
       offset one character too far, so any body beginning with a blank line--which the real C++
       template does--hashed differently than it was written, and every freshly-generated file read
       back as "edited" (and so was never upgraded)."""
    path = tmp_path / BASE_DOCKERFILE_NAME
    path.write_text(render_base_dockerfile("cpp", 1, "\nFROM gcc:14\n"))

    assert not read_base_dockerfile_state(path, "cpp").edited


def test_the_real_cpp_template_round_trips_as_unedited(tmp_path: Path) -> None:
    """Same regression, against the actual shipped template rather than a synthetic body."""
    ensure_base_dockerfile(tmp_path, LANG_SLUG, TEMPLATE_VERSION, TEMPLATE_BODY)

    state = read_base_dockerfile_state(tmp_path / BASE_DOCKERFILE_NAME, LANG_SLUG)

    assert state.version == TEMPLATE_VERSION
    assert not state.edited


def test_a_hand_written_file_with_no_header_counts_as_edited(tmp_path: Path) -> None:
    """No recognizable header means cg didn't write it, so it must never be overwritten."""
    path = tmp_path / BASE_DOCKERFILE_NAME
    path.write_text("FROM gcc:14\n")

    state = read_base_dockerfile_state(path, "cpp")

    assert state.version is None
    assert state.edited


def test_ensure_creates_both_dockerfiles(tmp_path: Path) -> None:
    path, warnings = ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:14\n")

    assert path.is_file()
    assert (tmp_path / CUSTOM_DOCKERFILE_NAME).is_file()
    assert warnings == []


def test_an_unmodified_stale_base_is_silently_upgraded(tmp_path: Path) -> None:
    """The normal upgrade path: cg ships a new template and the user never had to do anything."""
    ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:13\n")

    _, warnings = ensure_base_dockerfile(tmp_path, "cpp", 2, "FROM gcc:14\n")

    state = read_base_dockerfile_state(tmp_path / BASE_DOCKERFILE_NAME, "cpp")
    assert state.version == 2
    assert "gcc:14" in (tmp_path / BASE_DOCKERFILE_NAME).read_text()
    assert warnings == []


def test_an_edited_stale_base_is_warned_about_never_overwritten(tmp_path: Path) -> None:
    ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:13\n")
    base = tmp_path / BASE_DOCKERFILE_NAME
    base.write_text(base.read_text() + "RUN echo mine\n")

    _, warnings = ensure_base_dockerfile(tmp_path, "cpp", 2, "FROM gcc:14\n")

    assert "RUN echo mine" in base.read_text()
    assert "gcc:14" not in base.read_text()
    assert len(warnings) == 1
    assert "older cg template" in warnings[0]


def test_an_edited_current_base_is_left_alone_silently(tmp_path: Path) -> None:
    ensure_base_dockerfile(tmp_path, "cpp", 2, "FROM gcc:14\n")
    base = tmp_path / BASE_DOCKERFILE_NAME
    base.write_text(base.read_text() + "RUN echo mine\n")

    _, warnings = ensure_base_dockerfile(tmp_path, "cpp", 2, "FROM gcc:14\n")

    assert "RUN echo mine" in base.read_text()
    assert warnings == []


def test_a_custom_dockerfile_survives_every_base_upgrade(tmp_path: Path) -> None:
    """The whole point of the two-file split: the common customization is additive, so cg can
       replace the base freely without ever needing to merge."""
    ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:13\n")
    custom = tmp_path / CUSTOM_DOCKERFILE_NAME
    custom.write_text("RUN apt-get install -y libfoo-dev\n")

    ensure_base_dockerfile(tmp_path, "cpp", 2, "FROM gcc:14\n")
    ensure_base_dockerfile(tmp_path, "cpp", 3, "FROM gcc:15\n")

    assert custom.read_text() == "RUN apt-get install -y libfoo-dev\n"


def test_compose_appends_custom_to_base(tmp_path: Path) -> None:
    ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:14\n")
    (tmp_path / CUSTOM_DOCKERFILE_NAME).write_text("RUN echo mine\n")

    composed = compose_dockerfile(tmp_path)

    assert "FROM gcc:14" in composed
    assert composed.index("FROM gcc:14") < composed.index("RUN echo mine")


def test_a_custom_dockerfile_changes_the_image_tag(tmp_path: Path) -> None:
    ensure_base_dockerfile(tmp_path, "cpp", 1, "FROM gcc:14\n")
    before = image_tag_for("cpp", compose_dockerfile(tmp_path))
    (tmp_path / CUSTOM_DOCKERFILE_NAME).write_text("RUN echo mine\n")

    assert image_tag_for("cpp", compose_dockerfile(tmp_path)) != before


def test_toolchain_dir_prefers_a_per_root_override(tmp_path: Path) -> None:
    meta = tmp_path / ".meta"
    globals_ = tmp_path / "toolchain"
    assert resolve_toolchain_dir(meta, globals_, "cpp") == globals_ / "cpp"

    override = meta / "docker" / "cpp"
    override.mkdir(parents=True)
    (override / BASE_DOCKERFILE_NAME).write_text("FROM gcc:14\n")
    assert resolve_toolchain_dir(meta, globals_, "cpp") == override


# --- generated shell (pure) -------------------------------------------------------------------


def test_build_script_compiles_with_explicit_language() -> None:
    """`-x c++` is mandatory: the file is data/solution.src, and g++ doesn't recognize `.src`--it
       would treat it as a linker input and fail with "file format not recognized"."""
    script = build_script("/src/data/solution.src", "run")

    assert "-x c++" in script
    assert "$CG_CXXFLAGS" in script


def test_debug_build_uses_debug_flags() -> None:
    assert "$CG_CXXFLAGS_DEBUG" in build_script("/src/solution.cpp", "debug")


def test_build_script_hashes_only_the_source_file() -> None:
    """Hashing a tree instead would churn on every git operation--/src contains the contribution's
       entire git object database and its tests/."""
    script = build_script("/src/data/solution.src", "run")

    assert "sha256sum /src/data/solution.src" in script
    assert "find" not in script  # no tree walk


def test_run_script_enforces_the_timeout_inside_the_container() -> None:
    """Killing the local `docker exec` client does not kill the process inside the container, so an
       infinite loop would otherwise survive its timeout and keep burning CPU."""
    script = run_script(10.0)

    assert "timeout -k 1 11" in script


def test_run_script_forces_unbuffered_output() -> None:
    """Without this a C++ binary on a pipe block-buffers, so a solution printing a few lines emits
       nothing until exit and run_streaming streams nothing."""
    assert "stdbuf -o0 -e0" in run_script(10.0)


def test_run_script_fails_clearly_when_not_built() -> None:
    assert "not built" in run_script(10.0)


def test_exec_argv_passes_the_script_in_argv_not_stdin() -> None:
    """stdin has to stay free for the solution's own input."""
    argv = docker_exec_argv("c1", "echo hi", interactive=True)

    assert argv == ["docker", "exec", "-i", "c1", "sh", "-c", "echo hi"]
    assert docker_exec_argv("c1", "echo hi") == ["docker", "exec", "c1", "sh", "-c", "echo hi"]


def test_build_stamp_covers_the_source_path_not_just_its_contents() -> None:
    """The compiled path ends up in the debug info, so it is part of what the build *is*.

       Omitting it was a real staleness bug: switching between two identical-content paths--
       `data/solution.src` and the `solution.<ext>` symlink pointing at it--hashed the same, so the
       previous binary stayed in place carrying the old path in its DWARF, and breakpoints silently
       failed to bind."""
    from_real = build_script("/w/puzzle/data/solution.src", "debug")
    from_link = build_script("/w/puzzle/solution.cpp", "debug")

    assert "/w/puzzle/data/solution.src" in from_real
    # The path is folded into the stamp, so the two builds cannot be mistaken for one another.
    real_hash_line = next(ln for ln in from_real.splitlines() if ln.startswith("HASH="))
    link_hash_line = next(ln for ln in from_link.splitlines() if ln.startswith("HASH="))
    assert real_hash_line != link_hash_line


def test_cpp_always_compiles_the_real_file_never_the_symlink(tmp_path: Path) -> None:
    """Compiling the symlink makes the debugger's two paths for a location disagree--`file` from the
       DWARF and `fullname`, its own realpath of it--and cppdbg navigates by `fullname`. Worse, the
       `sourceFileMap` that fixes the navigation applies in *both* directions, so the editor
       translates a breakpoint back to the real path before sending it; if the DWARF names the
       symlink, gdb can't place it and the breakpoint goes hollow. Observed exactly that.

       Compiling the real file makes `file` and `fullname` agree, which is what lets one explicit
       mapping handle display without disturbing binding."""
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)

    assert ctx.solution_link is not None  # the symlink exists; it is simply not what we compile
    for profile in ("run", "debug"):
        assert language.source_path_in_container(ctx, profile) == str(ctx.solution_file)  # type: ignore[attr-defined]
    # A plain host path: the mount root is bind-mounted at its own location, so nothing translates.
    assert language.source_path_in_container(ctx, "debug").startswith(str(ctx.mount_root))  # type: ignore[attr-defined]


# --- integration (real Docker) ------------------------------------------------------------------


@pytest.mark.docker
@requires_docker
async def test_cpp_builds_and_runs(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)

    build = await language.build(ctx, timeout=900)
    assert build.ok, build.output

    result = await language.run(ctx, "21\n")

    assert result.output == "42\n"
    assert result.returncode == 0


@pytest.mark.docker
@requires_docker
async def test_cpp_rebuild_is_cached_until_the_source_changes(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)

    assert (await language.build(ctx, timeout=900)).ok
    assert (await language.build(ctx, timeout=900)).up_to_date

    ctx.solution_file.write_text(ECHO_DOUBLE.replace("n * 2", "n * 3"))
    rebuilt = await language.build(ctx, timeout=900)

    assert rebuilt.ok
    assert not rebuilt.up_to_date
    assert (await language.run(ctx, "21\n")).output == "63\n"


@pytest.mark.docker
@requires_docker
async def test_cpp_compile_error_is_reported_not_raised(tmp_path: Path) -> None:
    """A compile error is a routine outcome to display--raising would make `cg puzzle play`, which
       doesn't wrap its loop in a try/except, traceback on a typo."""
    language = get_language("C++")
    ctx = _ctx(tmp_path, "int main() { this is not c++ }\n")

    result = await language.build(ctx, timeout=900)

    assert not result.ok
    assert "error" in result.output.lower()


@pytest.mark.docker
@requires_docker
async def test_cpp_repeated_compile_error_replays_identical_diagnostics(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, "int main() { this is not c++ }\n")

    first = await language.build(ctx, timeout=900)
    second = await language.build(ctx, timeout=900)

    assert not first.ok and not second.ok
    assert first.output.strip() == second.output.strip()


@pytest.mark.docker
@requires_docker
async def test_cpp_run_times_out_without_leaving_the_process_running(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, "int main() { for (;;) {} }\n")
    assert (await language.build(ctx, timeout=900)).ok

    result = await language.run(ctx, "", timeout=2.0)

    assert result.timed_out
    assert result.returncode == -1

    # Killing the local `docker exec` client does NOT kill the process inside the container--the
    # in-container `timeout` is what reaps it. It's deliberately set a second *beyond* the outer
    # timeout so the outer one wins the race and the user gets a clean `timed_out=True` rather than
    # an opaque exit code 124, which means cleanup lands shortly after rather than instantly. Poll
    # for it instead of asserting immediately.
    container = container_name_for(LANG_SLUG, ctx.mount_root)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        procs = subprocess.run(
                ["docker", "exec", container, "ps", "-eo", "comm", "--no-headers"],
                capture_output=True, text=True, timeout=30, check=False)
        if "solution" not in procs.stdout:
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"runaway solution still running in {container}: {procs.stdout!r}")


@pytest.mark.docker
@requires_docker
async def test_cpp_streams_output_progressively(tmp_path: Path) -> None:
    """Verifies the `stdbuf` requirement end to end: without it everything would arrive at exit."""
    from codingame_tools.language import CgRunOutputChunk

    language = get_language("C++")
    ctx = _ctx(tmp_path, """\
#include <iostream>
#include <chrono>
#include <thread>
int main() {
    std::cout << "first" << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(700));
    std::cout << "second" << std::endl;
}
""")
    assert (await language.build(ctx, timeout=900)).ok

    seen: list[str] = []
    async for event in language.run_streaming(ctx, "", timeout=30):
        if isinstance(event, CgRunOutputChunk):
            seen.append(event.text)
            if "first" in event.text:
                break

    assert seen and "first" in seen[-1]
    assert "second" not in "".join(seen)  # arrived before the program had finished


@pytest.mark.docker
@requires_docker
async def test_cpp_toolchain_files_are_generated_on_first_use(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, ECHO_DOUBLE)

    assert (await get_language("C++").build(ctx, timeout=900)).ok

    directory = ctx.toolchain_dir / LANG_SLUG
    assert (directory / BASE_DOCKERFILE_NAME).is_file()
    assert (directory / CUSTOM_DOCKERFILE_NAME).is_file()
    state = read_base_dockerfile_state(directory / BASE_DOCKERFILE_NAME, LANG_SLUG)
    assert state.version == TEMPLATE_VERSION
    assert not state.edited
    assert TEMPLATE_BODY.strip().splitlines()[0] in (directory / BASE_DOCKERFILE_NAME).read_text()


@pytest.mark.docker
@requires_docker
async def test_cpp_reports_cached_marker_on_the_fast_path(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    assert (await language.build(ctx, timeout=900)).ok

    again = await language.build(ctx, timeout=900)

    assert again.up_to_date
    assert CACHED_MARKER not in again.output  # the marker is machine-only, never user-facing


# --- debug session (pure) -----------------------------------------------------------------------


async def test_cpp_vscode_config_is_the_same_for_every_working_directory(tmp_path: Path) -> None:
    """The property the redesign exists for. Two working directories in one workspace must produce
       an identical configuration, or launch.json needs rewriting whenever you switch between
       them."""
    workspace = tmp_path / "workspace"
    first = _ctx(workspace / "a", ECHO_DOUBLE)
    second = _ctx(workspace / "b", ECHO_DOUBLE)

    language = get_language("C++")
    from_first = await language.build_vscode_provisioning(
            CgVsCodeRequest(ctx=first, workspace_root=workspace))
    from_second = await language.build_vscode_provisioning(
            CgVsCodeRequest(ctx=second, workspace_root=workspace))

    assert from_first is not None and from_second is not None
    assert from_first.configurations == from_second.configurations
    assert from_first.tasks == from_second.tasks
    # Including the container, since they share one.
    assert (from_first.configurations[0]["pipeTransport"]["pipeArgs"]
            == from_second.configurations[0]["pipeTransport"]["pipeArgs"])


async def test_cpp_debug_launch_has_gdb_run_the_program_itself(tmp_path: Path) -> None:
    """The property everything else follows from.

       gdbserver exists for targets that can't run gdb; here gdb is already *on* the target, so a
       second debugger-side process in the same container buys nothing and costs the thing that
       matters--whoever execs the program owns its descriptors. With gdbserver doing it, the
       program's output went to gdbserver's terminal and was never seen by the editor, and its stdin
       had to be arranged separately. With gdb doing it, the program's I/O is the debug session's."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    (config,) = provisioning.configurations
    assert config["type"] == "cppdbg"
    assert config["request"] == "launch"
    # No server to attach to: gdb launches the inferior.
    assert "miDebuggerServerAddress" not in config
    # But gdb still runs *in the container*, since the host can't debug a Linux binary.
    assert config["pipeTransport"]["pipeProgram"] == "docker"
    assert container_name_for(LANG_SLUG, tmp_path) in config["pipeTransport"]["pipeArgs"]
    # The only sourceFileMap entry undoes gdb's own symlink resolution (see _SOURCE_FILE_MAP); the
    # mount needs no path translation, since it is mounted at its own path.
    assert list(config["sourceFileMap"]) == ["${fileDirname}/data/solution.src"]
    # Relative to the launched file, not absolute--an absolute mapping would need one launch
    # configuration per working directory, which is what this whole design avoids.
    assert all("${fileDirname}" in v for v in config["sourceFileMap"].values())


async def test_cpp_debug_launch_declares_the_target_architecture(tmp_path: Path) -> None:
    """Without it cppdbg warns "TargetArchitecture not detected, assuming x86_64" and does exactly
       that--wrong on any ARM host, where the disassembly and register views silently misread.
       Breakpoints, stepping and variables all keep working, which is what makes it easy to miss."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    assert provisioning.configurations[0]["targetArchitecture"] == target_architecture()
    assert target_architecture() in ("arm64", "x64")  # on any host this suite runs on


def test_target_architecture_uses_cppdbgs_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    """`platform.machine()` and cppdbg disagree on names: aarch64 vs arm64, x86_64 vs x64."""
    for machine, expected in (
                ("arm64", "arm64"), ("aarch64", "arm64"),
                ("x86_64", "x64"), ("AMD64", "x64"),
            ):
        monkeypatch.setattr(platform, "machine", lambda m=machine: m)
        assert target_architecture() == expected

    # Unrecognized: say nothing rather than assert something false, and let cppdbg detect.
    monkeypatch.setattr(platform, "machine", lambda: "sparc64")
    assert target_architecture() is None


async def test_cpp_debug_launch_feeds_the_test_case_to_stdin(tmp_path: Path) -> None:
    """Without this the program blocks forever at its first read--which is exactly what happened
       when the adapter turned out to be launching its own inferior, bypassing the one we had set up
       with a redirect.

       The path is fixed rather than per-directory because the launch configuration names it and has
       to stay identical for every working directory in the workspace."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    commands = [c["text"] for c in provisioning.configurations[0]["setupCommands"]]
    # `2>&1` is not decoration: the adapter reads gdb's *stdout*, so the program's stderr is dropped
    # unless it is merged there. Observed exactly that--stdout arrived, the cerr diagnostics didn't.
    assert f"set args < {DEBUG_STDIN_CONTAINER_PATH} 2>&1" in commands
    # And unbuffered, or a stdout that isn't a terminal shows nothing until the program exits.
    assert any(c.startswith("set exec-wrapper stdbuf") for c in commands)


async def test_cpp_debug_needs_only_a_prepare_task(tmp_path: Path) -> None:
    """One task that prepares and exits--no debug server to start, so nothing to stop afterwards.

       The old pair is declared retired so an upgrade removes them rather than leaving a task
       wired to a command that no longer does anything."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    (task,) = provisioning.tasks
    assert task["command"] == (
            'cg debug start --file "${file}" --workspace-root "${workspaceFolder}"')
    assert task.get("isBackground") is not True
    config = provisioning.configurations[0]
    assert config["preLaunchTask"] == task["label"]
    assert "postDebugTask" not in config
    assert "CG C++: Start debug session" in provisioning.retired_names
    assert "CG C++: Stop debug session" in provisioning.retired_names


async def test_cpp_prepare_task_reports_compile_errors_and_nothing_else(tmp_path: Path) -> None:
    """A catch-all problem-matcher pattern is a trap: every line the task prints becomes a
       "problem", and VS Code then refuses to launch with "errors exist after preLaunchTask"--
       observed exactly that, with an ordinary progress line reported as an error."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    pattern = re.compile(provisioning.tasks[0]["problemMatcher"]["pattern"][0]["regexp"])
    for line in ("container: cg-cpp-abc123", "program: /build/debug/solution", "up to date"):
        assert pattern.match(line) is None, line
    match = pattern.match("/w/puzzle/solution.cpp:18:5: error: 'foo' was not declared in this scope")
    assert match is not None
    assert match.group(4) == "error"


async def test_debug_adapter_logging_is_opt_in(tmp_path: Path) -> None:
    """The adapter is the one component of this stack that can't be exercised from a terminal, so
       its own protocol exchange is where a misbehaving session has to be diagnosed. Off by default
       because it is loud and slow."""
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    language = get_language("C++")

    off = await language.build_vscode_provisioning(
            CgVsCodeRequest(ctx=ctx, workspace_root=tmp_path))
    on = await language.build_vscode_provisioning(
            CgVsCodeRequest(ctx=ctx, workspace_root=tmp_path, debug_adapter_logging=True))

    assert off is not None and on is not None
    assert "logging" not in off.configurations[0]
    assert on.configurations[0]["logging"]["engineLogging"] is True
    assert on.configurations[0]["logging"]["moduleLoad"] is False  # or it buries the exchange


async def test_devcontainer_references_the_stable_alias_not_a_content_hash(tmp_path: Path) -> None:
    """A devcontainer.json is written once and read by VS Code much later, so embedding the
       content-addressed tag would leave it naming an image that no longer exists after the next
       toolchain tweak."""
    request = CgVsCodeRequest(ctx=_ctx(tmp_path, ECHO_DOUBLE), workspace_root=tmp_path)

    provisioning = await get_language("C++").build_vscode_provisioning(request)

    assert provisioning is not None
    image = json.loads(provisioning.files[".meta/.devcontainer/devcontainer.json"])["image"]
    assert image == latest_alias_for(LANG_SLUG)
    assert image.endswith(":latest")


# --- debug session (real Docker) ------------------------------------------------------------------


@pytest.mark.docker
@requires_docker
async def test_cpp_debug_preparation_builds_and_stages_the_input(tmp_path: Path) -> None:
    """Despite the name this starts nothing--gdb launches the program. All it has to leave behind is
       a current debug build and the test case where the launch configuration expects it."""
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)

    session = await language.start_debug_session(ctx, "21", timeout=900)

    assert session.ok, session.output
    assert session.details["container"] == container_name_for(LANG_SLUG, ctx.mount_root)
    assert session.details["stdin"] == DEBUG_STDIN_CONTAINER_PATH

    # Staged from a copy holding exactly the bytes asked for--no terminator supplied, since the
    # caller's value didn't have one. Reading a contribution's own test-case file would have added
    # one, diverging from `play` and from CodinGame by a byte.
    assert (ctx.meta_dir / DEBUG_STDIN_FILE_NAME).read_text() == "21"
    staged = subprocess.run(
            ["docker", "exec", container_name_for(LANG_SLUG, ctx.mount_root),
             "cat", DEBUG_STDIN_CONTAINER_PATH],
            capture_output=True, text=True, timeout=60, check=False)
    assert staged.stdout == "21"

    # Nothing to tear down, but it must stay safe to call--including twice.
    await language.stop_debug_session(ctx)
    await language.stop_debug_session(ctx)


@pytest.mark.docker
@requires_docker
async def test_cpp_debug_build_records_the_real_source_path(tmp_path: Path) -> None:
    """The debug info must name `data/solution.src`, the file actually compiled, so that the path
       the debugger reports and its own realpath of it agree. When they disagree the editor
       navigates away from the file you set the breakpoint in, and the `sourceFileMap` that fixes
       that then breaks binding, because it applies in both directions."""
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    assert (await get_language("C++").build(ctx, profile="debug", timeout=900)).ok

    dwarf = subprocess.run(
            ["docker", "exec", container_name_for(LANG_SLUG, ctx.mount_root),
             "sh", "-c", "readelf --debug-dump=info /build/debug/solution | grep -m1 DW_AT_name"],
            capture_output=True, text=True, timeout=60, check=False)

    # The real file, and a *host* path -- which is why no mount translation is needed either.
    assert str(ctx.solution_file) in dwarf.stdout
    assert str(ctx.solution_link) not in dwarf.stdout


# --- cg docker clean ------------------------------------------------------------------------


async def test_clean_reports_docker_unavailable_rather_than_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Docker means there was, by definition, nothing to clean--not an error."""
    monkeypatch.setattr(
            "codingame_tools.language._docker.shutil.which", lambda _name: None)

    result = await clean_managed()

    assert not result.docker_available
    assert result.containers == []
    assert result.images == []


@pytest.mark.docker
@requires_docker
async def test_clean_removes_containers_and_images_and_they_rebuild(tmp_path: Path) -> None:
    """The safety claim behind `cg docker clean` not prompting: everything it removes is rebuilt
       from files on disk, so a clean is always recoverable."""
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    assert (await language.build(ctx, timeout=900)).ok
    assert any(name == container_name_for(LANG_SLUG, ctx.mount_root)
               for name, _root in await list_managed_containers())
    assert await list_managed_images()

    result = await clean_managed()

    assert result.docker_available
    assert result.containers
    assert result.images
    assert await list_managed_containers() == []
    assert await list_managed_images() == []

    # ...and the whole thing comes back.
    rebuilt = await language.build(ctx, timeout=900)
    assert rebuilt.ok
    assert not rebuilt.up_to_date  # artifacts lived in the container, so this is a real rebuild
    assert (await language.run(ctx, "21\n")).output == "42\n"


@pytest.mark.docker
@requires_docker
async def test_clean_is_a_no_op_on_an_already_clean_system() -> None:
    await clean_managed()

    result = await clean_managed()

    assert result.docker_available
    assert result.containers == []
    assert result.images == []


# --- one container per working directory ---------------------------------------------------------


@pytest.mark.docker
@requires_docker
async def test_changing_language_replaces_the_container_rather_than_orphaning_it(tmp_path: Path) -> None:
    """Container names are per-language, so a working directory that switches `solution_language`
       would otherwise leave the old language's container running and bind-mounted forever, never
       referenced again."""
    root = (tmp_path / "puzzle").resolve()
    root.mkdir()

    await ensure_container(root, "cpp", "alpine:latest")
    assert sorted(n for n, r in await list_managed_containers() if r == str(root)) == [
            container_name_for("cpp", root)]

    await ensure_container(root, "java", "alpine:latest")

    assert sorted(n for n, r in await list_managed_containers() if r == str(root)) == [
            container_name_for("java", root)]

    await remove_containers_for_root(root)


@pytest.mark.docker
@requires_docker
async def test_only_ever_one_container_per_working_directory(tmp_path: Path) -> None:
    """The general invariant: whatever sequence of languages a working directory goes through, it
       has at most one container at a time."""
    root = (tmp_path / "puzzle").resolve()
    root.mkdir()

    for lang in ("cpp", "java", "cpp", "rust"):
        await ensure_container(root, lang, "alpine:latest")
        active = [n for n, r in await list_managed_containers() if r == str(root)]
        assert active == [container_name_for(lang, root)], f"after {lang}: {active}"

    await remove_containers_for_root(root)


@pytest.mark.docker
@requires_docker
async def test_a_sibling_working_directorys_container_is_left_alone(tmp_path: Path) -> None:
    """One-per-directory must not become one-per-machine: two working directories keep their own."""
    a = (tmp_path / "a").resolve()
    b = (tmp_path / "b").resolve()
    a.mkdir()
    b.mkdir()

    await ensure_container(a, "cpp", "alpine:latest")
    await ensure_container(b, "cpp", "alpine:latest")

    names = {n for n, _r in await list_managed_containers()}
    assert container_name_for("cpp", a) in names
    assert container_name_for("cpp", b) in names

    await remove_containers_for_root(a)
    await remove_containers_for_root(b)


@pytest.mark.docker
@requires_docker
async def test_remove_containers_for_root_can_spare_one(tmp_path: Path) -> None:
    root = (tmp_path / "puzzle").resolve()
    root.mkdir()
    await ensure_container(root, "cpp", "alpine:latest")
    keep = container_name_for("cpp", root)

    removed = await remove_containers_for_root(root, except_name=keep)

    assert removed == []
    assert [n for n, r in await list_managed_containers() if r == str(root)] == [keep]
    await remove_containers_for_root(root)


# --- state lives on Docker objects, not beside them ---------------------------------------------


@pytest.mark.docker
@requires_docker
async def test_recovers_when_the_container_is_removed_out_of_band(tmp_path: Path) -> None:
    """The reason no toolchain state is cached between calls: the user is always free to remove a
       container behind cg's back (`docker rm`, `cg docker clean`, Docker Desktop). A lookaside
       table would keep handing out a name that no longer resolves."""
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    assert (await language.build(ctx, timeout=900)).ok
    assert (await language.run(ctx, "21\n")).output == "42\n"

    subprocess.run(
            ["docker", "rm", "-f", container_name_for(LANG_SLUG, ctx.mount_root)],
            capture_output=True, timeout=60, check=False)

    rebuilt = await language.build(ctx, timeout=900)
    assert rebuilt.ok
    # Artifacts lived in the container, so this really did have to compile again.
    assert not rebuilt.up_to_date
    assert (await language.run(ctx, "21\n")).output == "42\n"


@pytest.mark.docker
@requires_docker
async def test_recovers_when_the_image_is_removed_out_of_band(tmp_path: Path) -> None:
    language = get_language("C++")
    ctx = _ctx(tmp_path, ECHO_DOUBLE)
    assert (await language.build(ctx, timeout=900)).ok

    await clean_managed()  # removes the container and the image it was built from

    assert (await language.build(ctx, timeout=900)).ok
    assert (await language.run(ctx, "21\n")).output == "42\n"


@pytest.mark.docker
@requires_docker
async def test_container_state_is_read_back_from_labels(tmp_path: Path) -> None:
    """`cg.root` and `cg.spec` are what make the reuse decision, so they must actually be readable
       back off the container rather than assumed."""
    root = (tmp_path / "puzzle").resolve()
    root.mkdir()
    await ensure_container(root, "cpp", "alpine:latest")

    states = await containers_for_root(root)

    name = container_name_for("cpp", root)
    assert set(states) == {name}
    assert states[name].running
    assert states[name].spec == container_spec_hash(
            "alpine:latest", container_create_argv(root, name))

    await remove_containers_for_root(root)


@pytest.mark.docker
@requires_docker
async def test_a_spec_change_forces_recreation(tmp_path: Path) -> None:
    """Changing the image (or any creation flag) must invalidate an existing container, since its
       build artifacts belong to the old one."""
    root = (tmp_path / "puzzle").resolve()
    root.mkdir()
    await ensure_container(root, "cpp", "alpine:latest")
    before = (await containers_for_root(root))[container_name_for("cpp", root)].spec

    await ensure_container(root, "cpp", "busybox:latest")
    after = (await containers_for_root(root))[container_name_for("cpp", root)].spec

    assert before != after
    await remove_containers_for_root(root)

