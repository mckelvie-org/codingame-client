"""Docker plumbing shared by every containerized `CgLanguage`: resolving and building the toolchain
   image, and keeping one long-lived container per workspace alive to run things in.

   Sibling of `_process.py`/`vscode.py`--deliberately outside `languages/`, so the registry's
   discovery walk never sees it. Drives the `docker` CLI as a subprocess rather than a Docker SDK,
   matching how `git` is already used (`contribution_manager.git_repo`) and adding no dependency.

   **The container holds the build artifacts.** The workspace is bind-mounted read-only at its own
   path, and compiled output lives at `/build/<language>/<profile>/` inside the container's own
   writable layer--so the solution source is the only durable state outside the container. Two consequences:
   losing the container means losing the build (harmless--it just rebuilds), and the container must
   be validated on attach rather than trusted, since a stale one bind-mounted to a since-deleted
   directory would otherwise be silently reused.

   That the artifacts die *with* the container is a property worth keeping rather than an accident:
   it is what makes "the toolchain changed" and "the build is stale" the same event. Change the
   image or how cg creates containers and the spec hash changes, the container is replaced, and
   `/build` goes with it--so a binary linked against a toolchain you have since edited cannot
   survive to be reused. A named volume would outlive the image and need that coupling re-established
   by hand.

   **The container idles, and is `--rm`.** Nothing runs in it between invocations: `sleep infinity`
   only holds it open, because `docker exec` needs a running container. That is the *whole* reason
   it stays up--it is a filesystem we occasionally run a process in, not a service. Measured, the
   idling buys about 110ms per invocation over `docker run --rm` (41ms vs 152ms), which matters only
   on the many-exec path of running a full test suite.

   `--rm` is what makes that acceptable: a container that stops for any reason--`docker kill`, Docker
   Desktop quitting, a reboot--removes itself instead of lingering as a stopped husk that the next
   run has to reason about. Ephemeral by construction, and the next command simply builds a fresh
   one.

   **State lives on the Docker objects themselves, never beside them.** Everything cg needs to
   decide whether a container is reusable is a label on that container (`cg.root`, `cg.spec`) or a
   label on the image (`cg.managed`), read back with a `docker` query each time. Nothing is
   remembered between calls, and nothing is remembered *within* a call beyond what one query
   returned. That is deliberate: the user can remove a container or image at any moment--`docker
   rm`, Docker Desktop, `cg docker clean`--and any lookaside table would immediately be wrong, in a
   way that surfaces much later as a confusing "No such container". Build stamps follow the same
   rule by living inside the container at `/build/`, so they die exactly when the thing they
   describe does.

   Asking Docker every time is affordable because the common path is a *single* `docker ps`: it
   answers "does our container exist, was it built from the spec we want, is it running, and are
   there strays from an older image" at once, and a container that passes vouches for its own image
   still existing.

   **Two Dockerfiles, not one.** `base.dockerfile` is cg-owned and records the toolchain fragments it
   was composed from; `custom.dockerfile` is user-owned and appended verbatim. That split is what makes toolchain
   upgrades safe: the common customization ("install these libraries") is purely additive, so cg can
   replace the base whenever it ships a new template without ever touching--or needing to merge
   with--the user's edits.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ._process import CgCapturedRun, run_argv_capture

__all__ = [
    "CgDockerError",
    "CgDockerUnavailableError",
    "CgDockerfileState",
    "CgToolchain",
    "CgDockerCleanResult",
    "BUILD_DIR",
    "compose_dockerfile",
    "compose_with_base",
    "docker_exec_argv",
    "ensure_base_dockerfile",
    "ensure_container",
    "containers_for_root",
    "ensure_image",
    "ensure_toolchain",
    "buildx_available",
    "build_image_content",
    "tag_image",
    "image_tag_for",
    "latest_alias_for",
    "container_name_for",
    "remove_container",
    "remove_containers_for_root",
    "clean_managed",
    "list_managed_containers",
    "list_managed_images",
    "resolve_toolchain_dir",
]

# Mount root: a cg container bind-mounts one host directory read-only **at its own path**, so
# `/home/me/work` inside the container is `/home/me/work` on the host. There is deliberately no
# `/src`-style constant, because there is no translation to do: a host path under the mount root is
# already the in-container path.
#
# That identity is what removes `sourceFileMap` from the generated debug configuration. gdb records
# whatever path it compiled, so if that path is also valid on the host, the debug adapter can open
# the file the user already has open and breakpoints bind with nothing to configure.
#
# The directory mounted is the **VS Code workspace root** (see
# `codingame_tools.language.vscode.find_workspace_root`), not the working directory: a
# `solution.<ext>` symlink is often viewed from elsewhere in the workspace, and a debugger must be
# able to see it. It also makes one container per workspace serve every working directory in that
# workspace, in every language--which is what lets the generated launch configuration, which has to
# name the container, be static.
#
# Whole-directory rather than single-file: a single-file bind mount breaks the moment an editor
# saves atomically (write-temp + rename leaves the container holding the old inode). Mounting a
# directory also lets the relative `solution.<ext>` -> `data/solution.src` symlink resolve, and makes
# test-case inputs visible for debugging.
#
# Assumes host paths are valid Linux paths, which holds on macOS and Linux. A Windows host would
# need real translation and a `sourceFileMap` to go with it.

BUILD_DIR = "/build"
"""Where build artifacts live--inside the container, never on the host."""

_DOCKER = "docker"
_LABEL_SPEC = "cg.spec"
_LABEL_ROOT = "cg.root"
_LABEL_MANAGED = "cg.managed"
"""Applied to every image cg builds, so `clean_managed()` can identify them by label instead of by
   tag name. Containers are found by `cg.root` instead, which they all carry."""
_IDLE_COMMAND = ["sleep", "infinity"]
_DEBUG_CREATE_FLAGS = ["--cap-add=SYS_PTRACE", "--security-opt", "seccomp=unconfined"]
"""Needed for `gdbserver`/`gdb` to ptrace the solution. Docker drops `SYS_PTRACE` and its default
   seccomp profile blocks `ptrace` outright, so without these debugging fails on Linux (it happens
   to work on Docker Desktop for macOS, which makes this an easy thing to miss). Applied to the one
   shared container rather than a separate debug-only one, so a debug session doesn't have to
   rebuild artifacts the run container already has."""

IMAGE_REPOSITORY = "cg-toolchain"
"""Repository name for the image and the container derived from it.

   No longer per language. One image carries every language cg supports, so one container per
   *workspace* serves them all -- see `codingame_tools.language.toolchain`. The previous
   `cg-<lang>:<hash>` scheme meant a workspace with two languages ran two containers, each with the
   whole workspace bind-mounted, for no reason once the toolchains could coexist."""

BASE_DOCKERFILE_NAME = "base.dockerfile"
CUSTOM_DOCKERFILE_NAME = "custom.dockerfile"

_TEMPLATE_HEADER_RE = re.compile(
        r"^# cg-toolchain:[ \t]*fragments=(?P<fragments>\S*)[ \t]+"
        r"body-sha256=(?P<hash>[0-9a-f]+)[ \t]*$",
        re.MULTILINE,
    )
"""`[ \\t]` rather than `\\s` deliberately: `\\s*$` in MULTILINE mode can consume the header's own
   trailing newline and still match `$` at the *next* line's end, which pushes `match.end()` one
   character too far. Any body starting with a blank line then hashes differently than it was
   written and a freshly-generated file reads back as "edited"."""

_CUSTOM_DOCKERFILE_TEMPLATE = """\
# Your own additions to the cg-managed toolchain image, appended verbatim to
# {base_name} (which cg owns and may replace wholesale when it ships a new template--
# so put your changes *here*, never there).
#
# The usual reason to edit this is making a library available to your solution at build time:
#
#   RUN apt-get update && apt-get install -y --no-install-recommends libfoo-dev \\
#       && rm -rf /var/lib/apt/lists/*
#
# Changing anything here changes the image tag, so the image rebuilds automatically.
"""


class CgDockerError(Exception):
    """A `docker` command failed. Carries the command's own output, which is almost always the
       actually-useful part."""


class CgDockerUnavailableError(CgDockerError):
    """Docker isn't usable--not installed, or the daemon isn't running/reachable. Kept distinct
       from `CgDockerError` so a caller can tell "your setup isn't ready" from "the thing you asked
       for went wrong"."""


@dataclass(frozen=True)
class CgDockerfileState:
    """What's currently on disk for a cg-managed `base.dockerfile`."""

    path: Path
    exists: bool
    fragments: str | None
    """The fragment manifest recorded in its header (`gcc11@1,cpp@2,...`), or `None` if absent or
       unparseable -- which means a hand-written file, treated the same as edited.

       A manifest rather than a single integer because one image is composed from many independently
       versioned fragments; "is this stale?" is `recorded != wanted`, which is both simpler and more
       precise than comparing version numbers."""

    edited: bool
    """Whether the body differs from the hash its own header records--i.e. the user changed it. cg
       must never overwrite an edited base; that's the escape hatch for swapping `FROM` outright."""


@dataclass(frozen=True)
class CgToolchain:
    """A ready-to-use containerized toolchain for one working directory."""

    image_tag: str
    container_name: str
    warnings: list[str]
    """Non-fatal things worth telling the user once, e.g. "your edited base.dockerfile is based on
       an older cg template"."""


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_") or "lang"


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def image_tag_for(dockerfile_content: str) -> str:
    """Content-addressed image tag. Keying on the Dockerfile's *content* rather than on the working
       directory means every root sharing the global toolchain shares one image, and any change--a
       cg template bump or a user tweak--produces a new tag automatically, so nothing ever runs
       against a stale image."""
    return f"{IMAGE_REPOSITORY}:{_short_hash(dockerfile_content)}"


def container_name_for(mount_root: Path) -> str:
    """One container per (mount root x language)--i.e. per workspace, not per working directory,
       since the mount root is the workspace root.

       Sharing one container across a workspace's working directories is deliberate: it is what
       makes the container name a constant a static launch configuration can name, and it means a
       workspace pays for one image pull and one container rather than one per puzzle. Builds don't
       collide because artifacts are per-source-path under `BUILD_DIR`.

       Hashed because Docker names can't contain `/`; the mount root is `.resolve()`d, so the name is
       stable and two paths pointing at the same real directory correctly share a container."""
    return f"{IMAGE_REPOSITORY}-{_short_hash(str(mount_root))}"


def fragment_manifest(text: str) -> str | None:
    """The `fragments=` manifest recorded in a rendered Dockerfile, or `None` if it has no cg header.

       Lets `ensure_base_dockerfile` compare what is on disk against what the current fragments would
       produce, without re-deriving either."""
    match = _TEMPLATE_HEADER_RE.search(text)
    return None if match is None else match.group("fragments")


def read_base_dockerfile_state(path: Path) -> CgDockerfileState:
    """Inspect an on-disk `base.dockerfile` without modifying it."""
    if not path.is_file():
        return CgDockerfileState(path=path, exists=False, fragments=None, edited=False)
    text = path.read_text(encoding="utf-8")
    match = _TEMPLATE_HEADER_RE.search(text)
    if match is None:
        # No recognizable header: a hand-written file. Treated as edited so it's never clobbered.
        return CgDockerfileState(path=path, exists=True, fragments=None, edited=True)
    # Exactly one newline separates the header line from the body--strip that one only.
    # `lstrip("\n")` would also eat a leading blank line belonging to the body itself, making
    # a freshly-written file hash as "edited".
    body = text[match.end():]
    body = body[1:] if body.startswith("\n") else body
    recorded = match.group("hash")
    actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return CgDockerfileState(
            path=path, exists=True, fragments=match.group("fragments"), edited=actual != recorded)


def ensure_base_dockerfile(directory: Path, rendered: str) -> tuple[Path, list[str]]:
    """Make sure `directory` holds the current `base.dockerfile` (and a commented starter
       `custom.dockerfile`), regenerating the base when that's safe.

       - Missing -> write it.
       - Present, unmodified, but composed from different fragments -> silently regenerate. The
         normal upgrade path; asks nothing of the user.
       - Present and edited -> **never** overwritten; a stale one produces a warning instead. That
         is the escape hatch for swapping `FROM` or pinning a toolchain outright.

    Args:
        rendered: What the current fragments produce -- see
                   `codingame_tools.language.toolchain.render_dockerfile`.

    Returns:
        The base file's path, and any warnings to surface once.
    """
    directory.mkdir(parents=True, exist_ok=True)
    base_path = directory / BASE_DOCKERFILE_NAME
    custom_path = directory / CUSTOM_DOCKERFILE_NAME
    warnings: list[str] = []

    wanted = fragment_manifest(rendered)
    state = read_base_dockerfile_state(base_path)
    if not state.exists or (not state.edited and state.fragments != wanted):
        base_path.write_text(rendered, encoding="utf-8")
    elif state.edited and state.fragments != wanted:
        warnings.append(
                f"{base_path} has local edits and was composed from different toolchain fragments"
                f"{'' if state.fragments is None else f' ({state.fragments}, current {wanted})'}"
                f"--leaving it alone. Move your changes to {CUSTOM_DOCKERFILE_NAME} and delete the "
                "base to pick up the new one."
            )

    if not custom_path.exists():
        custom_path.write_text(
                _CUSTOM_DOCKERFILE_TEMPLATE.format(base_name=BASE_DOCKERFILE_NAME),
                encoding="utf-8",
            )
    return base_path, warnings


def resolve_toolchain_dir(meta_dir: Path, toolchain_dir: Path) -> Path:
    """Where the toolchain Dockerfiles live: a per-working-directory override (`<meta>/docker/`) if
       one exists, else the shared per-user location (`<toolchain_dir>/`).

       Global by default on purpose--the toolchain isn't puzzle-specific, so tweaking it once should
       apply everywhere rather than needing to be redone per puzzle. There is one directory rather
       than one per language, matching the one image that now carries them all."""
    override = meta_dir / "docker"
    if (override / BASE_DOCKERFILE_NAME).is_file() or (override / CUSTOM_DOCKERFILE_NAME).is_file():
        return override
    return toolchain_dir


def compose_dockerfile(directory: Path) -> str:
    """The effective Dockerfile: cg's base with the user's additions appended. Never written to
       disk--it's piped straight to `docker build`."""
    return compose_with_base(directory, (directory / BASE_DOCKERFILE_NAME).read_text(encoding="utf-8"))


def compose_with_base(directory: Path, base: str) -> str:
    """`compose_dockerfile`, but for a base that has not been written to `directory` yet.

       Exists so a read-only question--"what tag would these languages produce?"--can be answered
       without the side effect of replacing the user's base.dockerfile. The tag has to cover the
       *composed* content, since custom.dockerfile is part of what gets built; computing it from the
       base alone would report a tag no image ever has."""
    custom_path = directory / CUSTOM_DOCKERFILE_NAME
    if not custom_path.is_file():
        return base
    custom = custom_path.read_text(encoding="utf-8")
    if not custom.strip():
        return base
    return f"{base}\n# --- {CUSTOM_DOCKERFILE_NAME} ---\n{custom}"


async def _docker(argv: list[str], *, timeout: float, **kwargs: object) -> CgCapturedRun:
    if shutil.which(_DOCKER) is None:
        raise CgDockerUnavailableError(
                "docker isn't on PATH. Running or debugging a compiled language needs Docker--"
                "install Docker Desktop (or the docker CLI plus a running daemon) and try again."
            )
    return await run_argv_capture([_DOCKER, *argv], timeout=timeout, **kwargs)  # type: ignore[arg-type]


async def ensure_image(
            directory: Path, *, timeout: float, quiet: bool = False,
        ) -> str:
    """Build (or reuse) the toolchain image for the Dockerfiles in `directory`, returning its tag.

       Uses an **empty build context** (`docker build -f - -`): nothing is ever `COPY`'d in, since
       the solution is bind-mounted at run time instead. That keeps builds fast and means editing a
       solution never invalidates the image.

       Docker's own layer cache makes a rebuild of an unchanged Dockerfile nearly free, so this is
       cheap to call before every build; the image is only genuinely rebuilt when its content-
       addressed tag changes.

    Args:
        quiet: Capture `docker build` output instead of letting it through to stderr. Off by
                default because a cold build is slow and its progress is the only feedback.
    """
    content = compose_dockerfile(directory)
    tag = image_tag_for(content)

    exists = await _docker(["image", "inspect", tag], timeout=30.0)
    if exists.ok:
        # Re-point the alias even when the image is already built: switching between two existing
        # images (e.g. undoing a custom.dockerfile edit) hits this path, and :latest must follow.
        await _tag_latest(tag)
        return tag

    # `docker build -` (a bare `-`, never `-f - -`) reads the Dockerfile from stdin and uses an
    # *empty* context--docker rejects using stdin for both. An empty context is exactly right here:
    # nothing is ever COPY'd in, so editing a solution can't invalidate the image.
    result = await _docker(
            # --label is applied to the built image regardless of what the Dockerfile says, which is
            # what makes `cg docker clean` able to find cg's own images without guessing from tag
            # names (and without ever touching an unrelated image that happens to be named "cg-*").
            ["build", "--label", f"{_LABEL_MANAGED}=1", "-t", tag, "-"],
            timeout=timeout, input_text=content, inherit_stderr=not quiet,
        )
    if result.timed_out:
        raise CgDockerError(
                f"building the toolchain image timed out after {timeout}s. A cold build "
                "pulls a base image and can take a while--retry, or raise --build-timeout."
            )
    if not result.ok:
        detail = result.combined.strip()
        # With inherit_stderr, docker's own diagnostics already went straight to the terminal--say
        # so rather than reporting a failure with a suspiciously empty explanation.
        detail = f"\n{detail}" if detail else " (see the docker build output above)"
        raise CgDockerError(
                f"failed to build the toolchain image from {directory}:{detail}")
    await _tag_latest(tag)
    return tag


def latest_alias_for() -> str:
    """The stable, *non*-content-addressed tag kept pointing at the current toolchain image.

       Generated `devcontainer.json` files reference this rather than the real content-addressed
       tag: a devcontainer.json is written once and read by VS Code much later, so embedding a hash
       that changes on the next toolchain tweak would leave it pointing at an image that no longer
       exists. cg's own build/run/debug paths always use the exact tag--this alias exists purely for
       tools that need a name stable across rebuilds."""
    return f"{IMAGE_REPOSITORY}:latest"


async def tag_image(source: str, target: str) -> None:
    """Point `target` at the image `source` already names. Both must be local."""
    await _docker(["tag", source, target], timeout=60.0)


async def _tag_latest(tag: str) -> None:
    await tag_image(tag, latest_alias_for())


async def buildx_available() -> bool:
    """Whether `docker buildx` is usable. Needed only for multi-platform builds--the ordinary
       single-platform path uses plain `docker build`, which every Docker install has."""
    try:
        return (await _docker(["buildx", "version"], timeout=60.0)).ok
    except CgDockerUnavailableError:
        return False


async def build_image_content(
            content: str,
            *,
            tag: str,
            platforms: Sequence[str] = (),
            push: bool = False,
            timeout: float,
            quiet: bool = False,
        ) -> None:
    """Build a Dockerfile given as text, unconditionally--no "is it already built?" check.

       Distinct from `ensure_image`, which is the hot path called before every run and skips the
       build whenever the content-addressed tag already exists. This is the explicit
       `cg docker toolchain build`: the user asked for a build, so they get one, and they may ask
       for architectures the local daemon can't even load.

       Uses the same **empty build context** as `ensure_image` (see there): nothing is ever COPY'd
       in, because solutions are bind-mounted at run time.

    Args:
        platforms: e.g. `["linux/amd64", "linux/arm64"]`. Empty means the host's own architecture
                    via plain `docker build`. Anything else requires buildx.
        push:      Push to a registry instead of loading into the local daemon.

    Raises:
        CgDockerError: if buildx is needed but missing, if more than one platform is requested
                        without `push` (a hard Docker limitation--see below), or if the build fails.
    """
    if len(platforms) > 1 and not push:
        # Not a cg restriction: `docker buildx build --load` can only load a *single* platform into
        # the local image store, because the daemon's image format has no place to put a manifest
        # list. A multi-arch build therefore has to go somewhere that does understand one, i.e. a
        # registry. Caught here with an explanation rather than letting buildx fail obscurely.
        raise CgDockerError(
                f"cannot build {len(platforms)} platforms ({', '.join(platforms)}) into the local "
                "Docker daemon: a multi-platform image is a manifest list, which `--load` cannot "
                "represent. Either build one platform at a time, or add --push to publish the "
                "multi-arch image to a registry."
            )

    if platforms and not await buildx_available():
        raise CgDockerError(
                "multi-platform builds need `docker buildx`, which isn't available. It ships with "
                "Docker Desktop and recent Docker Engine; without it, omit --platform to build for "
                "this machine's own architecture."
            )

    # --label is applied to the built image whatever the Dockerfile says, which is what lets
    # `cg docker clean` find cg's own images without guessing from tag names.
    label = ["--label", f"{_LABEL_MANAGED}=1"]
    if platforms or push:
        argv = ["buildx", "build", *label]
        if platforms:
            argv += ["--platform", ",".join(platforms)]
        # --load puts the result in the local daemon (buildx otherwise leaves it in its own cache
        # and the image would appear not to exist); --push sends it to a registry instead.
        argv += ["-t", tag, "--push" if push else "--load", "-"]
    else:
        argv = ["build", *label, "-t", tag, "-"]

    result = await _docker(argv, timeout=timeout, input_text=content, inherit_stderr=not quiet)
    if result.timed_out:
        raise CgDockerError(
                f"building the toolchain image timed out after {timeout}s. A cold multi-language "
                "build pulls a base image and several toolchains--retry, or raise the timeout."
            )
    if not result.ok:
        detail = result.combined.strip()
        detail = f"\n{detail}" if detail else " (see the docker build output above)"
        raise CgDockerError(f"failed to build the toolchain image:{detail}")


@dataclass(frozen=True)
class _ContainerState:
    """What one `docker ps` row tells us about a cg container."""

    name: str
    spec: str
    running: bool


async def containers_for_root(root: Path) -> dict[str, _ContainerState]:
    """Every cg container bound to `root`, keyed by name, from a **single** `docker ps`.

       One query deliberately answers every question `ensure_toolchain` has--does our container
       exist, was it created from the spec we now want, is it running, and are there containers for
       a previous language still around. Asking Docker each time (rather than remembering the answer
       in a lookaside table) is what keeps this correct when the user removes a container or image
       out-of-band, which they're always free to do."""
    if shutil.which(_DOCKER) is None:
        return {}
    listed = await run_argv_capture(
            [
                _DOCKER, "ps", "-a", "--filter", f"label={_LABEL_ROOT}={root}",
                "--format",
                '{{.Names}}\t{{.Label "' + _LABEL_SPEC + '"}}\t{{.State}}',
            ],
            timeout=60.0,
        )
    if not listed.ok:
        return {}
    states: dict[str, _ContainerState] = {}
    for line in listed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].strip():
            continue
        name = parts[0].strip()
        states[name] = _ContainerState(
                name=name, spec=parts[1].strip(), running=parts[2].strip().lower() == "running")
    return states


async def remove_container(name: str) -> None:
    """Force-remove a container, ignoring "no such container". Called when a working directory is
       deleted, and when a stale container has to be replaced.
"""
    await _docker(["rm", "-f", name], timeout=60.0)


@dataclass(frozen=True)
class CgDockerCleanResult:
    """What `clean_managed()` tore down."""

    containers: list[str]
    images: list[str]
    docker_available: bool
    """False when Docker isn't installed or the daemon isn't reachable--in which case there was, by
       definition, nothing to clean, and that isn't an error."""


async def list_managed_containers() -> list[tuple[str, str]]:
    """Every cg-created container on this machine, as `(name, root)` pairs.

       Found by the `cg.root` label every cg container carries, so this catches containers for
       languages this build doesn't know about and for working directories that no longer exist."""
    if shutil.which(_DOCKER) is None:
        return []
    listed = await run_argv_capture(
            [
                _DOCKER, "ps", "-a", "--filter", f"label={_LABEL_ROOT}",
                "--format", '{{.Names}}\t{{.Label "' + _LABEL_ROOT + '"}}',
            ],
            timeout=60.0,
        )
    if not listed.ok:
        return []
    pairs: list[tuple[str, str]] = []
    for line in listed.stdout.splitlines():
        name, _, root = line.partition("\t")
        if name.strip():
            pairs.append((name.strip(), root.strip()))
    return pairs


async def list_managed_images() -> list[str]:
    """Image IDs cg built, found by the `cg.managed` label applied at build time."""
    if shutil.which(_DOCKER) is None:
        return []
    listed = await run_argv_capture(
            [_DOCKER, "images", "--filter", f"label={_LABEL_MANAGED}", "--format", "{{.ID}}", "-q"],
            timeout=60.0,
        )
    if not listed.ok:
        return []
    # One image can carry several tags (the content-addressed one plus the :latest alias), and
    # `docker images` lists a row per tag--dedupe so it isn't removed twice.
    seen: list[str] = []
    for image_id in listed.stdout.split():
        if image_id and image_id not in seen:
            seen.append(image_id)
    return seen


async def clean_managed() -> CgDockerCleanResult:
    """Remove every container and image cg created.

       Always safe: a container holds nothing but build artifacts, and an image is rebuilt from
       Dockerfiles that live on disk--so there is no user work here to lose, and everything is
       recreated on the next build. That's why this neither prompts nor needs a --force.

       Containers go first: an image still in use by a container can't be removed."""
    if shutil.which(_DOCKER) is None:
        return CgDockerCleanResult(containers=[], images=[], docker_available=False)

    containers = [name for name, _root in await list_managed_containers()]
    for name in containers:
        await remove_container(name)

    images = await list_managed_images()
    removed_images: list[str] = []
    for image_id in images:
        # --force because an image usually carries both its content-addressed tag and the :latest
        # alias, and docker refuses an untagged removal of a multi-tag image otherwise.
        result = await _docker(["rmi", "--force", image_id], timeout=120.0)
        if result.ok:
            removed_images.append(image_id)
    return CgDockerCleanResult(
            containers=containers, images=removed_images, docker_available=True)


async def remove_containers_for_root(root: Path, *, except_name: str | None = None) -> list[str]:
    """Remove every cg container bound to `root`, whatever language--for use when a working
       directory is being deleted, and to enforce one-container-per-working-directory.

       Matches on the `cg.root` label rather than recomputing the name, so it catches
       containers for languages this build doesn't know about. Silently does nothing when Docker
       isn't installed or the daemon is down: failing to tidy up a container must never block
       deleting a directory.

    Args:
        except_name: Leave this one alone. Used by `ensure_container` to sweep away containers for
                      a working directory's *previous* language while keeping the current one.

    Returns:
        The names removed (empty if none, or if Docker is unavailable).
    """
    if shutil.which(_DOCKER) is None:
        return []
    listed = await run_argv_capture(
            [_DOCKER, "ps", "-a", "--filter", f"label={_LABEL_ROOT}={root}", "--format", "{{.Names}}"],
            timeout=60.0,
        )
    if not listed.ok:
        return []
    names = [n for n in listed.stdout.split() if n and n != except_name]
    for name in names:
        await remove_container(name)
    return names


def container_create_argv(mount_root: Path, name: str) -> list[str]:
    """The `docker run` argv (minus image/command/spec label) used to create a cg container.

       Split out so the spec hash can cover it: the hash includes every creation flag, not just the
       image, so a change to *how* cg creates containers invalidates existing ones instead of
       silently reusing one built the old way."""
    return [
            "run", "--detach", "--name", name,
            # Auto-remove on exit, so a container that stops for *any* reason--`docker kill`, Docker
            # Desktop quitting, a reboot--leaves nothing behind rather than a stopped husk. Verified:
            # without it, killing one leaves `Exited (137)` sitting in `docker ps -a` forever.
            #
            # Safe precisely because the container holds only build artifacts (see the module
            # docstring): losing it costs a rebuild and nothing else. It also makes the "is this
            # container reusable?" question simpler, since a container that failed is never around
            # to be asked about.
            "--rm",
            # --init runs a real init as PID 1, which reaps orphans. Without it the idle `sleep`
            # is PID 1 and never reaps, so every debug session's detached gdbserver lingers as a
            # zombie in a container that's meant to live for the whole working directory's life.
            "--init",
            *_DEBUG_CREATE_FLAGS,
            "--label", f"{_LABEL_ROOT}={mount_root}",
            # Mounted at its own path--see the mount-root comment above.
            "--volume", f"{mount_root}:{mount_root}:ro",
            "--workdir", BUILD_DIR,
        ]


def container_spec_hash(image_tag: str, create_argv: list[str]) -> str:
    """Identity of everything that would have to be true for an existing container to be reusable.
       Recorded on the container as the `cg.spec` label, so the check is a label comparison rather
       than remembered state."""
    return _short_hash(image_tag + "\0" + "\0".join(create_argv))


async def ensure_container(root: Path, image_tag: str) -> str:
    """Make sure a container for `root` exists, is running, matches `image_tag`, and is the *only*
       cg container bound to `root`; return its name.

       Everything is decided from labels read back off Docker--see `containers_for_root`. Two things
       would otherwise leave a stale container in play:

       - *Drift.* A container whose recorded `cg.spec` no longer matches (different image, or a
         change to how cg creates containers) is removed and recreated, so a working directory
         deleted and recreated at the same path, or an edited Dockerfile, never silently keeps
         running against the old one--and, since artifacts live *inside* the container, against a
         stale build.
       - *Containers this cg would never name.* One container now serves every language in a
         workspace, but an older cg named them per language (`cg-cpp-<hash>`, `cg-java-<hash>`), and
         a future naming change would be no different. Those are still running and still
         bind-mounted, but nothing will ever reference them again, so they are swept by `cg.root`
         label rather than by name--which is why the sweep can retire a scheme it doesn't know.
    """
    name = container_name_for(root)
    create_argv = container_create_argv(root, name)
    spec = container_spec_hash(image_tag, create_argv)

    existing = (await containers_for_root(root)).get(name)
    await remove_containers_for_root(root, except_name=name)
    if existing is not None and existing.spec != spec:
        await remove_container(name)
        existing = None
    elif existing is not None and not existing.running:
        started = await _docker(["start", name], timeout=60.0)
        if not started.ok:
            # A container that won't start is worth replacing rather than reporting--it's a
            # disposable cache, not user data.
            await remove_container(name)
            existing = None
    if existing is None:
        created = await _docker(
                [*create_argv, "--label", f"{_LABEL_SPEC}={spec}", image_tag, *_IDLE_COMMAND],
                timeout=120.0,
            )
        if not created.ok:
            raise CgDockerError(f"failed to create container {name}:\n{created.combined}")
    return name


async def ensure_toolchain(
            *,
            root: Path,
            meta_dir: Path,
            toolchain_dir: Path,
            languages: list[str] | None = None,
            image: str | None = None,
            timeout: float,
        ) -> CgToolchain:
    """Everything needed before running anything: the Dockerfile current, image built, container up,
       validated, and the only one for this working directory.

       One toolchain serves **every** language, so this no longer takes a language at all -- see
       `IMAGE_REPOSITORY`. Two working directories in one workspace, in different languages, now
       share a container instead of running one each.

       Holds **no cached state between calls**: every answer is read back off Docker's own labels.
       That matters because this runs once per test case -- a lookaside table would be faster but
       would drift the moment the user removed a container or image out-of-band, which they may do at
       any time (and which `cg docker clean` does).

       Speed comes from asking *once* rather than remembering: the common path is a single
       `docker ps`. When a container for this root already exists with a matching spec, the image it
       was created from necessarily still exists, so the image check and `:latest` re-tag are skipped.

    Args:
        languages: CodinGame language names to compose the image from. `None` means every language
                    cg supports, which is the intended default -- the whole set is ~1.9 GB because
                    the big toolchains share one Debian base.
        image:     A prebuilt image tag to use instead of composing and building one. Skips the
                    Dockerfile entirely, which is the point of a published image: a pull rather than
                    a multi-gigabyte local build.
    """
    # Imported here, not at module scope: the toolchain registry reaches the language plugins, each
    # of which imports this module.
    from .toolchain import (
        BASE_IMAGE,
        PREAMBLE,
        default_languages,
        fragments_for_languages,
        render_dockerfile,
    )

    warnings: list[str] = []
    if image is not None:
        image_tag = image
    else:
        directory = resolve_toolchain_dir(meta_dir, toolchain_dir)
        rendered = render_dockerfile(
                fragments_for_languages(languages if languages is not None else default_languages()),
                base_image=BASE_IMAGE, preamble=PREAMBLE,
            )
        _, warnings = ensure_base_dockerfile(directory, rendered)
        image_tag = image_tag_for(compose_dockerfile(directory))

    name = container_name_for(root)
    spec = container_spec_hash(image_tag, container_create_argv(root, name))
    states = await containers_for_root(root)
    ours = states.get(name)
    if ours is not None and ours.running and ours.spec == spec and len(states) == 1:
        return CgToolchain(image_tag=image_tag, container_name=name, warnings=warnings)

    if image is None:
        await ensure_image(directory, timeout=timeout)
    container_name = await ensure_container(root, image_tag)
    return CgToolchain(image_tag=image_tag, container_name=container_name, warnings=warnings)


def docker_exec_argv(container_name: str, script: str, *, interactive: bool = False) -> list[str]:
    """argv running `script` inside `container_name` via `sh -c`.

       The script is passed in **argv**, never on stdin, so stdin stays free for the solution's own
       input. `interactive` adds `-i` to forward this process's stdin into the container--needed
       when running a solution, pointless (and a stray open pipe) when building."""
    argv = [_DOCKER, "exec"]
    if interactive:
        argv.append("-i")
    argv.extend([container_name, "sh", "-c", script])
    return argv
