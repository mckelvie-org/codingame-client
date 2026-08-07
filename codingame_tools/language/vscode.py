"""Generating VS Code run/debug configuration for a puzzle/contribution working directory.

   A language plugin describes *what* it needs (`CgLanguage.build_vscode_provisioning` ->
   `CgVsCodeProvisioning`); this module owns *where it goes* and *how it merges* with whatever the
   user already has. Sibling of `_process.py`/`_docker.py`--deliberately outside `languages/`, so
   the registry's discovery walk never sees it.

   Two things here are less obvious than they look:

   **VS Code only reads `.vscode/launch.json` from the workspace root folder**, never from a
   subdirectory. A puzzle working directory is very often a subdirectory of the user's real
   workspace (this repo's own `puzzle/` and `contribution/` are exactly that), so writing
   `<root>/.vscode/launch.json` would be silently ignored. Everything therefore targets a
   *resolved workspace root* (see `find_workspace_root`), and every generated path that refers to
   the working directory is **absolute**--`${workspaceFolder}` is the wrong answer whenever the
   workspace root isn't the working directory, which is the common case.

   **`launch.json`/`tasks.json` are JSONC**, not JSON: VS Code allows `//` comments and trailing
   commas, and plenty of real files use them. `json.loads` raises on those, so rather than risk
   corrupting a hand-edited file this module refuses to merge into anything it can't parse strictly
   (see `CgVsCodeMergeError`) unless explicitly told to overwrite.

   **Generated entries are owned by the language, not by the working directory.** One entry per
   language serves every puzzle and contribution in the workspace, because everything that used to
   vary per directory is now resolved at launch time instead of baked in: which directory, from
   VS Code's `${file}`; which test, from that directory's `.meta/selected-test.json`. So provisioning
   a second working directory *replaces* the first's entries rather than adding to them, and
   `launch.json` never needs regenerating after an import, a language change, or a new directory.

   Versions through 1.0.x named entries per directory (`"CG puzzle: ..."`, input ids `cg_puzzle_*`)
   and carried a `pickString` list of test cases that went stale the moment tests changed.
   `_OWNED_NAME_RE`/`_OWNED_INPUT_RE` match both spellings, so those are cleaned out on the next
   provisioning run rather than accumulating forever.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "CgVsCodeKind",
    "CgVsCodeRequest",
    "CgVsCodeProvisioning",
    "CgVsCodeMergeError",
    "find_workspace_root",
    "MANAGED_PREFIX",
    "ACTION_DEBUG",
    "ACTION_PREPARE_DEBUG",
    "entry_name",
    "PRESENTATION",
    "check_provisioning",
    "write_provisioning",
]

CgVsCodeKind = Literal["puzzle", "contribution"]

_WORKSPACE_MARKER_DIRS = (".vscode", ".git", ".hg", ".svn")

_LAUNCH_FILE_NAME = "launch.json"
_TASKS_FILE_NAME = "tasks.json"
_EXTENSIONS_FILE_NAME = "extensions.json"
_VSCODE_DIR_NAME = ".vscode"


@dataclass(frozen=True)
class CgVsCodeRequest:
    """What a language plugin is being asked to generate configuration for.

       Deliberately thin. It used to also carry the working directory's `kind` and its full list of
       test cases, because a generated debug configuration had to name both; now `${file}` and
       `.meta/selected-test.json` answer those at launch time, so a plugin needs neither and the
       configuration it produces is the same for every working directory in the workspace."""

    ctx: Any
    """The `CgLanguageContext` for the working directory (typed loosely to avoid a circular import
       with `base`--see `codingame_tools.language.base.CgLanguageContext`).

       Present for the language's own needs (its toolchain paths, say), **not** so generated entries
       can bake in this directory--see the module docstring."""

    workspace_root: Path
    """Where `.vscode/` will be written--see `find_workspace_root`. Often *not* `ctx.root`.

       Also the directory a containerized language must mount, so that paths inside the container
       match the paths VS Code has open--see `codingame_tools.language._docker`."""

    debug_adapter_logging: bool = False
    """Generate a configuration that logs the debug adapter's own conversation with the debugger.

       Off by default because it is loud and slows a session down. It exists because the debug
       adapter is the one component of the stack that can't be exercised from a terminal: gdbserver,
       stdin redirection, stepping and symbol resolution can all be driven by hand and checked, but
       what VS Code's adapter actually sends and receives can only be observed from inside a real
       session. When a session misbehaves and everything underneath it demonstrably works, this is
       the remaining place to look.

       A plugin should turn on whatever its adapter offers, and quieten anything so voluminous it
       would bury the exchange."""


@dataclass(frozen=True)
class CgVsCodeProvisioning:
    """What a language plugin wants written. Everything is optional--a plugin supplies only the
       pieces it actually has."""

    configurations: list[dict[str, Any]] = field(default_factory=list)
    """Entries for `launch.json`'s `configurations`. Each `name` must come from `entry_name()`, so
       re-provisioning replaces exactly cg's own entries for this language and leaves everything
       else--the user's, and other languages'--alone.

       Must not bake in anything specific to `request.ctx.root`: one entry serves every working
       directory in the workspace (see the module docstring)."""

    inputs: list[dict[str, Any]] = field(default_factory=list)
    """Entries for `launch.json`'s `inputs`. Each `id` must start with `cg_` (see
       `_OWNED_INPUT_RE`), for the same reason.

       Nothing populates this today: the `pickString` test-case pickers it existed for are what the
       `.meta/`-based selection replaced. Kept because it is a real `launch.json` capability a future
       plugin may need, and because `write_provisioning` must go on pruning 1.0.x leftovers."""

    tasks: list[dict[str, Any]] = field(default_factory=list)
    """Entries for `tasks.json`'s `tasks`. Each `label` must come from `entry_name()`, and the same
       "nothing per-directory" rule applies."""

    files: dict[str, str] = field(default_factory=dict)
    """Extra files to write, keyed by path **relative to the working directory root** (not the
       workspace root)--e.g. `.meta/.devcontainer/devcontainer.json`.

       Belongs under `.meta/`. These files are generated and not the user's to maintain, and
       `.meta/` is the only part of a working directory that is gitignored, so anywhere else they'd
       be committed into whatever repository tracks the directory. That also rules out `data/`
       specifically, which for a contribution is a git work tree where a stray generated file would
       be swept into the server tree by `git add -A` or deleted by `git clean -fd`."""

    retired_names: list[str] = field(default_factory=list)
    """Configuration names / task labels *earlier versions of this plugin* generated and no longer
       do, so they are removed rather than orphaned.

       Mostly a backstop. `_is_owned_by_this_run` already replaces everything in this language's
       namespace, so renaming an *action* is handled with no declaration at all. This is for the
       rarer change that moves an entry out of that namespace--a language's `cg_id` changing, say--
       where nothing else would connect the old name to the new one.

       The `files` equivalent is `obsolete_files`. Both exist for the same reason: what cg generated
       is cg's to clean up, and nothing else's."""

    obsolete_files: list[str] = field(default_factory=list)
    """Paths (relative to the working directory root, like `files`) that *earlier versions* of this
       plugin generated and that should now be deleted.

       Generated files are cg's to clean up: a user who upgrades shouldn't be left with a stale
       `devcontainer.json` in a location nothing writes to any more, silently offering VS Code a
       "Reopen in Container" that no longer reflects anything. The `launch.json` equivalent is
       `_OWNED_NAME_RE`.

       Only ever names specific files, never directories, and a containing directory is removed only
       if deleting the file leaves it empty--so a path the user has since put their own work in is
       left alone."""

    recommended_extensions: list[str] = field(default_factory=list)
    """Extension IDs to merge into `extensions.json`'s `recommendations` (union, never removing the
       user's own--there's no reliable way to tell which ones cg previously added)."""


class CgVsCodeMergeError(Exception):
    """Raised when an existing VS Code config file can't be safely merged into--almost always
       because it's JSONC (comments/trailing commas) rather than strict JSON. Refusing is
       deliberate: silently rewriting would drop the user's comments and any content our parser
       didn't understand."""


def find_workspace_root(root: Path) -> Path:
    """Best guess at the VS Code workspace root folder that contains `root`.

       Walks up from `root` looking for a directory that already has `.vscode/`, then for a VCS
       marker (`.git`/`.hg`/`.svn`), stopping at the filesystem root. Falls back to `root` itself,
       which is correct when the user opens the working directory directly as their folder.

       This matters because VS Code reads `launch.json` only from the workspace root--see the
       module docstring."""
    root = root.resolve()
    candidates = [root, *root.parents]
    for marker in _WORKSPACE_MARKER_DIRS:
        for candidate in candidates:
            if (candidate / marker).is_dir():
                return candidate
    return root


MANAGED_PREFIX = "CG "
"""Marks every `launch.json` configuration name and `tasks.json` label cg has *ever* generated, in
   any version. Stable forever--changing it would strand every entry written by an older release.

   Level one of a three-level name (see `entry_name`). Its job is to make cg's entries identifiable
   as a set, so all of them can be swept in one go regardless of language or version--which is what
   makes an unrecognized leftover recoverable rather than permanent clutter."""

_MANAGED_NAME_RE = re.compile(r"^CG(?: ([^:]+))?: ")
"""Parses a managed name, capturing its middle segment (`None` if there isn't one).

   Matches **every shape cg has ever written**, which is the entire point of having a managed
   prefix--an entry only stays recoverable if the rule that recognizes it is broader than the rule
   that writes it:

   | Shape | Written by | Segment |
   | --- | --- | --- |
   | `CG puzzle: Debug ...` | 1.0.x, one per working directory | the directory name |
   | `CG: Debug C++ solution ...` | the intermediate static spelling | none |
   | `CG C++: Debug solution` | current | the language |

   Only the last is generated now; the other two are recognized purely so they can be cleaned up.
   Requiring the trailing `": "` in all cases is what keeps a user's own `"CG is my favourite"` or
   `"CGI: render"` from being mistaken for ours."""


def entry_name(language: str, action: str) -> str:
    """The name of a generated `launch.json` configuration or `tasks.json` label.

       Three levels, each doing a distinct job:

       ```
       CG C++: Debug solution
       └┬┘ └┬┘  └─────┬─────┘
        │   │         └─ 3. a well-known action, from the ACTION_* constants below
        │   └─────────── 2. the language, partitioning ownership
        └─────────────── 1. MANAGED_PREFIX, marking the whole set as cg's
       ```

       - **Level 1** makes every cg entry, of any language and any version, identifiable as a set.
       - **Level 2** keeps languages independent. A provisioning run only ever generates for one
         language, so without this partition, provisioning a C++ directory would delete the Python
         entry in the same workspace--and whichever you provisioned last would be the only one that
         worked.
       - **Level 3** is drawn from a fixed vocabulary rather than free text, so an entry keeps its
         identity across releases and re-provisioning replaces it instead of adding a second one.
         When one genuinely has to change, the old spelling goes in
         `CgVsCodeProvisioning.retired_names`.

       Nothing here encodes a working directory. One entry per (language, action) serves the whole
       workspace--see the module docstring."""
    return f"{MANAGED_PREFIX}{language}: {action}"


PRESENTATION = {"group": "cg"}
"""`presentation` for every generated launch configuration, which clusters cg's entries together in
   VS Code's Run and Debug dropdown instead of scattering them among the user's.

   Worth having because **F5 runs whatever configuration is selected, never the one matching the
   file you have open**. Debugging a solution therefore means picking the `CG <language>: ...` entry
   first, and the commonest way to get a solution that hangs at its first read is to press F5 with
   someone's own "Python: Current File" still selected--that runs the solution directly, with stdin
   attached to the terminal rather than to a test case. Grouping can't prevent that, but it makes
   the right entry easy to find.

   Deliberately does *not* set `order` to push cg above the user's own entries: their configurations
   are theirs to rank."""

ACTION_DEBUG = "Debug solution"
"""Launch configuration: debug the solution the active editor tab belongs to, against that working
   directory's selected test case."""

ACTION_PREPARE_DEBUG = "Prepare debug session"
"""Task: get everything in place for a debug launch--build the debug profile, stage the selected
   test case's input--and exit. A `preLaunchTask`.

   Deliberately *prepares* rather than *starts*: the debugger launches the program itself, as it does
   for any ordinary local target. An earlier design had this task start a debug server for the
   adapter to attach to, which is what forced the program's output somewhere the editor could not
   see it."""

_OWNED_INPUT_RE = re.compile(r"^cg_")
"""Matches a `launch.json` input id cg generated. Nothing generates inputs any more--the `pickString`
   test-case pickers they existed for are gone--so this now only cleans 1.0.x leftovers, which would
   otherwise prompt for a test case that no configuration reads."""


def _read_json_object(path: Path, *, force: bool) -> dict[str, Any]:
    """Existing config as a dict, `{}` if absent. Raises `CgVsCodeMergeError` if present but not
       strict JSON, unless `force` (in which case it's discarded and overwritten)."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as e:
        if force:
            return {}
        raise CgVsCodeMergeError(
                f"{path} isn't strict JSON ({e})--VS Code allows comments and trailing commas "
                "there, but merging into such a file would silently drop them. Re-run with "
                "--force to overwrite it, or remove the comments first."
            ) from e
    if not isinstance(loaded, dict):
        if force:
            return {}
        raise CgVsCodeMergeError(f"{path} doesn't contain a JSON object at the top level.")
    return loaded


def _is_owned_by_this_run(name: str, *, language: str, retired: set[str]) -> bool:
    """Whether a managed entry named `name` is this provisioning run's to replace or remove.

       Three ways to qualify, which between them cover every entry cg has ever written without ever
       claiming one of the user's:

       1. **Its language segment is this run's language.** Everything cg generates for a language is
          replaced wholesale, so an entry a *previous version* wrote under a name we no longer
          produce is cleaned up automatically--no bookkeeping to remember, which is the failure mode
          a declared list alone has.
       2. **It is explicitly retired.** For the rarer case of a name changing in a way rule 1 can't
          see, e.g. an action renamed at the same time as the language segment.
       3. **Its language segment is missing, or isn't a language cg knows.** This is what removes
          names from earlier schemes--1.0.x's, which put a *directory* where the language now goes
          (`"CG puzzle: ..."`), and the intermediate `"CG: ..."` spelling, which had no segment at
          all--without needing a dated regex per scheme. It also collects entries for a language
          that has since been dropped.

       Rule 3 has one known edge: provisioning with an *older* cg, in a workspace an newer cg has
       already provisioned, removes entries for languages the older one hasn't heard of. Re-running
       the newer cg restores them, and the reverse (leaving unknown managed entries forever) is the
       worse failure."""
    # Imported here, not at module scope: the registry imports every language plugin, each of which
    # imports this module. At module scope that is a cycle.
    from .registry import list_language_cg_ids

    match = _MANAGED_NAME_RE.match(name)
    if match is None:
        return False
    if name in retired:
        return True
    segment = match.group(1)
    return segment is None or segment == language or segment not in list_language_cg_ids()


def _merge_by_key(
            existing: list[Any],
            generated: list[dict[str, Any]],
            *,
            key: str,
            language: str,
            retired: Iterable[str] = (),
        ) -> list[dict[str, Any]]:
    """Replace the entries this run owns (see `_is_owned_by_this_run`), preserving everything else
       in its original order, then append any generated entry that wasn't already present.

       Duplicates are impossible by construction: every generated name is, by definition, in this
       run's own language namespace, so it is removed before being re-added."""
    by_name = {e[key]: e for e in generated if isinstance(e.get(key), str)}
    retired_names = set(retired)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in existing:
        name = entry.get(key) if isinstance(entry, dict) else None
        if not isinstance(name, str):
            merged.append(entry)
            continue
        if name in by_name:
            # Replaced **in place**, not removed and re-appended: re-provisioning a workspace with
            # two languages would otherwise reshuffle the order on every run, churning a file the
            # user reads and version-controls for no semantic change.
            merged.append(by_name[name])
            seen.add(name)
        elif not _is_owned_by_this_run(name, language=language, retired=retired_names):
            merged.append(entry)
    merged.extend(e for name, e in by_name.items() if name not in seen)
    return merged


def _merge_by_key_by_pattern(
            existing: list[Any], generated: list[dict[str, Any]], *, key: str,
            owned: re.Pattern[str],
        ) -> list[dict[str, Any]]:
    """`_merge_by_key`, but owning everything matching a pattern rather than a declared set.

       Used only for `launch.json` inputs, where nothing is generated any more and the entire job is
       sweeping up 1.0.x's orphaned `cg_*` pickers. There is no per-language partition to respect,
       because there are no current entries to partition."""
    kept = [
            e for e in existing
            if not (isinstance(e, dict) and isinstance(e.get(key), str) and owned.match(e[key]))
        ]
    return [*kept, *generated]


def _write_text_if_changed(path: Path, content: str, *, dry_run: bool) -> bool:
    """Write `content` to `path` unless it is already exactly that. Returns whether it differed.

       Never rewriting an unchanged file is the whole basis of `check_provisioning`, and it is also
       a courtesy: `.vscode/` files are usually version-controlled, and re-provisioning shouldn't
       show up as a diff, a modified timestamp, or a reload prompt when nothing actually changed."""
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def _write_json_if_changed(path: Path, data: dict[str, Any], *, dry_run: bool) -> bool:
    return _write_text_if_changed(path, json.dumps(data, indent=2) + "\n", dry_run=dry_run)


def write_provisioning(
            provisioning: CgVsCodeProvisioning,
            *,
            root: Path,
            workspace_root: Path,
            language: str,
            force: bool = False,
            dry_run: bool = False,
        ) -> list[Path]:
    """Write `provisioning` into `<workspace_root>/.vscode/` (and `provisioning.files` into
       `root`), merging with whatever is already there.

       Only files whose content would actually change are touched, so re-running when everything is
       already current is a no-op on disk--no diffs, no timestamps, no editor reload prompts.

    Args:
        provisioning:    What the language plugin produced.
        root:            The working directory root. Only the base for `provisioning.files`
                          now--entries are owned by declared name, not by a directory.
        workspace_root:  Where `.vscode/` lives--see `find_workspace_root`.
        language:        The `cg_id` of the language being provisioned for. Scopes which existing
                          entries this run owns--see `_is_owned_by_this_run`--so provisioning one
                          language never disturbs another's.
        force:           Overwrite an existing config file that isn't strict JSON instead of
                          refusing.
        dry_run:         Work out what would change without touching anything. See
                          `check_provisioning`.

    Returns:
        Every path that changed (or, under `dry_run`, would change), in write order. Empty means
        everything was already up to date.

    Raises:
        CgVsCodeMergeError: if an existing file can't be parsed and `force` is False.
    """
    written: list[Path] = []
    vscode_dir = workspace_root / _VSCODE_DIR_NAME

    if provisioning.configurations or provisioning.inputs:
        path = vscode_dir / _LAUNCH_FILE_NAME
        data = _read_json_object(path, force=force)
        data.setdefault("version", "0.2.0")
        inputs = _merge_by_key_by_pattern(
                data.get("inputs") or [], provisioning.inputs, key="id", owned=_OWNED_INPUT_RE)
        if inputs:
            data["inputs"] = inputs
        else:
            # Nothing generates inputs any more. Leaving an empty list behind would be a puzzling
            # relic in a file the user reads.
            data.pop("inputs", None)
        data["configurations"] = _merge_by_key(
                data.get("configurations") or [], provisioning.configurations,
                key="name", language=language, retired=provisioning.retired_names)
        if _write_json_if_changed(path, data, dry_run=dry_run):
            written.append(path)

    if provisioning.tasks:
        path = vscode_dir / _TASKS_FILE_NAME
        data = _read_json_object(path, force=force)
        data.setdefault("version", "2.0.0")
        data["tasks"] = _merge_by_key(
                data.get("tasks") or [], provisioning.tasks, key="label",
                language=language, retired=provisioning.retired_names)
        if _write_json_if_changed(path, data, dry_run=dry_run):
            written.append(path)

    if provisioning.recommended_extensions:
        path = vscode_dir / _EXTENSIONS_FILE_NAME
        data = _read_json_object(path, force=force)
        # Union rather than replace: there's no marker distinguishing recommendations cg added
        # previously from ones the user added, so removing any would eventually delete theirs.
        existing = [e for e in (data.get("recommendations") or []) if isinstance(e, str)]
        data["recommendations"] = existing + [
                e for e in provisioning.recommended_extensions if e not in existing]
        if _write_json_if_changed(path, data, dry_run=dry_run):
            written.append(path)

    for relative, content in provisioning.files.items():
        path = root / relative
        if _write_text_if_changed(path, content, dry_run=dry_run):
            written.append(path)

    for relative in provisioning.obsolete_files:
        stale = root / relative
        if not stale.is_file():
            continue
        written.append(stale)
        if dry_run:
            continue
        stale.unlink()
        # Only when it's left empty--never a recursive delete of something the user may have added
        # to. `rmdir` failing on a non-empty directory is exactly the check wanted.
        with suppress(OSError):
            stale.parent.rmdir()

    return written


def check_provisioning(
            provisioning: CgVsCodeProvisioning,
            *,
            root: Path,
            workspace_root: Path,
            language: str,
        ) -> list[Path]:
    """Every path `write_provisioning` would change, without changing anything.

       This is how a user finds out their VS Code configuration has gone stale. Generated entries
       carry no version stamp and need none: the generated content *is* the version, so "would
       writing it change anything?" answers the question exactly, and keeps answering it correctly
       when a future release alters what gets generated.

       `force` is deliberately absent. A config file that can't be parsed raises
       `CgVsCodeMergeError` here just as it would on a real run, because "I would have to overwrite
       your hand-edited file" is precisely what a check should report."""
    return write_provisioning(
            provisioning, root=root, workspace_root=workspace_root, language=language,
            dry_run=True)
