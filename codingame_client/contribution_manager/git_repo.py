"""Low-level git plumbing wrapper backing the git-based contribution repo (`main`/`server`/
   `version-data` branches, in a decoupled `--git-dir`/`--work-tree` layout--see
   `codingame_client.contribution_manager.manager` for how these are used, and `layout.py` for the
   branch/tag naming constants).

   The only module in this package that shells out to `git` (subprocess, not GitPython--matches
   the plain `subprocess.run` pattern already used elsewhere in this codebase for external tools,
   e.g. the old `tree_diff.compute_diff3_merge`/`merge_tools.launch_merge_tool`, both superseded by
   this). Every invocation passes `--git-dir`/`--work-tree` explicitly (and sets `cwd` to the work
   tree too, for git versions/commands sensitive to it)--cwd-based discovery is never relied on,
   since the whole point of this layout is that `data/` itself carries no `.git` marker a human's
   plain `git` command could ever find (see `cg contribution git`, in the CLI, for how a human
   reaches this repo directly).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

__all__ = [
    "CgGitError",
    "is_inside_existing_repo",
    "init_repo",
    "CgGitRepo",
]


class CgGitError(Exception):
    """Raised when a `git` invocation fails (non-zero exit)--wraps the exact argv and stderr for
       introspection, structured enough to be useful without needing a library for it."""

    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{' '.join(argv)!r} failed (exit {returncode}): {stderr.strip()}")


def is_inside_existing_repo(path: Path) -> bool:
    """Whether `path` is already inside some other git repository's working tree--checked purely
       via plain cwd-based discovery (deliberately: this is the one place that's appropriate,
       since we're asking "if I ran plain `git` here, would it find something"). Used once, at
       `import_()` time, to decide where this contribution's own (unrelated) git-dir should live--
       see the module docstring and `codingame_client.contribution_manager.layout`.

       `path` itself usually doesn't exist yet (a brand-new `cg contribution import` target)--the
       check walks up to the nearest existing ancestor first, since `cwd` has to be a real
       directory."""
    existing = path
    while not existing.is_dir():
        parent = existing.parent
        if parent == existing:
            return False  # walked all the way to the filesystem root without finding anything real
        existing = parent
    result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=existing, capture_output=True, text=True, check=False,
        )
    return result.returncode == 0 and result.stdout.strip() == "true"


def init_repo(git_dir: Path, work_tree: Path) -> None:
    """Initialize a new, non-bare git repository whose metadata lives at `git_dir` and whose
       working tree is `work_tree`--the two need not be related in any way on disk (no `.git`
       entry is ever created inside `work_tree`)."""
    git_dir.mkdir(parents=True, exist_ok=True)
    work_tree.mkdir(parents=True, exist_ok=True)
    argv = ["git", f"--git-dir={git_dir}", f"--work-tree={work_tree}", "init", "--quiet"]
    result = subprocess.run(argv, cwd=work_tree, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CgGitError(argv, result.returncode, result.stderr)


class CgGitRepo:
    """One git repository, addressed by its (possibly work-tree-external) `git_dir`/`work_tree`
       pair. `work_tree` is always the contribution's `data/` directory in practice--the checkout
       of the `main` branch. `server`/`version-data` are never checked out; every method that
       writes to them does so via plumbing (a scratch index, or a single-blob tree for
       `version-data`), never touching `HEAD`, the real index, or anything under `work_tree`.
    """

    git_dir: Path
    work_tree: Path

    def __init__(self, git_dir: Path, work_tree: Path) -> None:
        self.git_dir = git_dir
        self.work_tree = work_tree

    # --- low-level -----------------------------------------------------------------------------

    def _run(
                self, args: list[str], *, index_file: Path | None = None,
                work_tree: Path | None = None, input: bytes | None = None, check: bool = True,
            ) -> subprocess.CompletedProcess[bytes]:
        """Run `git <args>` in raw bytes mode throughout (stdin/stdout/stderr)--deliberately never
           `text=True`: `write_blob`'s input can be arbitrary binary content (e.g. `cover.png`),
           and a text-mode round-trip through subprocess's own encoding would corrupt it. Callers
           that know their own input/output is text (commit messages, SHAs, diff output) encode/
           decode UTF-8 themselves at that call site.

           `work_tree`, if given, overrides `self.work_tree` for this one invocation--used together
           with `index_file` (a scratch index) to build a tree from some *other* directory
           entirely (e.g. a temp dir holding freshly-fetched content) without ever touching the
           real working tree--same underlying object database (`--git-dir` is never overridden),
           just a different set of files to read for this one operation."""
        effective_work_tree = work_tree if work_tree is not None else self.work_tree
        argv = ["git", f"--git-dir={self.git_dir}", f"--work-tree={effective_work_tree}", *args]
        env = dict(os.environ, GIT_INDEX_FILE=str(index_file)) if index_file is not None else None
        result = subprocess.run(
                argv, cwd=effective_work_tree, capture_output=True, check=False,
                input=input, env=env,
            )
        if check and result.returncode != 0:
            raise CgGitError(argv, result.returncode, result.stderr.decode("utf-8", errors="replace"))
        return result

    def _run_interactive(self, args: list[str]) -> int:
        """Run `git <args>` with inherited stdio (no capture)--for commands the user needs to see
           and interact with directly, e.g. `mergetool` launching an external GUI or terminal
           tool. Returns the exit code; never raises on a non-zero exit (the caller decides what
           that means)."""
        argv = ["git", f"--git-dir={self.git_dir}", f"--work-tree={self.work_tree}", *args]
        return subprocess.run(argv, cwd=self.work_tree, check=False).returncode

    def set_head(self, branch: str) -> None:
        """Point `HEAD` at `refs/heads/<branch>`--used once, right after `init_repo()`, so a fresh
           repo's "currently checked out branch" is unambiguously `MAIN_BRANCH_NAME` regardless of
           git's own `init.defaultBranch` configuration."""
        self._run(["symbolic-ref", "HEAD", f"refs/heads/{branch}"])

    def rev_parse(self, *args: str, check: bool = True) -> str | None:
        """`git rev-parse <args>`, stripped. Returns None (rather than raising) if `check=False`
           and the command fails--used for existence checks like `rev_parse("--verify",
           "MERGE_HEAD", check=False)`."""
        result = self._run(["rev-parse", *args], check=check)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8").strip()

    def resolve_ref(self, ref: str) -> str | None:
        """The commit SHA `ref` (a branch/tag name) currently points at, or None if it doesn't
           exist."""
        return self.rev_parse(ref, check=False)

    def update_ref(self, ref: str, sha: str) -> None:
        self._run(["update-ref", ref, sha])

    def reset_index_to(self, sha: str) -> None:
        """Move the branch `HEAD` currently points at (always `main`, by construction) to `sha`,
           and reset the real index to match its tree--leaving the working tree untouched (`git
           reset <sha>`, a "mixed" reset). Used after directly building a commit whose tree
           already matches what's on disk (`import_()`/`commit()`, both of which build their tree
           via a scratch index--see `write_tree_from_dir`--that never touches the real index at
           all). Without this, the real index is left stale (empty, for a fresh repo) relative to
           `main`'s new tip; that doesn't matter for anything routed through `checkout_all()`
           (`read-tree --reset -u` resyncs it), but a later real `git merge` reads the index
           directly and misbehaves against a stale one--confirmed by direct testing."""
        self._run(["reset", sha])

    def tag(self, name: str, target: str) -> None:
        """Create (or overwrite) a lightweight tag--used for `server.<version>`/
           `version-data.<version>`, both purely informational/addressing conveniences, not
           something that needs annotation."""
        self._run(["tag", "-f", name, target])

    def merge_base(self, a: str, b: str) -> str | None:
        """The best common ancestor of `a` and `b`, or None if they share no history (shouldn't
           happen for `main`/`server`, which always share `import_()`'s initial commit)."""
        result = self._run(["merge-base", a, b], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8").strip()

    # --- building commits without checkout ------------------------------------------------------

    def write_blob(self, content: bytes) -> str:
        result = self._run(["hash-object", "-w", "--stdin", "-t", "blob"], input=content)
        return result.stdout.decode("utf-8").strip()

    def write_tree_from_dir(self, source_dir: Path) -> str:
        """Snapshot whatever's currently on disk at `source_dir` into a tree object, via a scratch
           index--never touches the real index, `HEAD`, or (unless `source_dir is self.work_tree`)
           the real working tree. Used both to build `server`'s tree from `main`'s live content
           after a successful push (`source_dir=self.work_tree`, i.e. `write_tree_from_worktree()`)
           and to build it from freshly-*fetched* content that was never materialized into the
           real working tree at all (`source_dir` is a throwaway temp dir--see `fetch()`)."""
        with tempfile.TemporaryDirectory() as tmp:
            index_file = Path(tmp) / "index"
            self._run(["add", "-A"], index_file=index_file, work_tree=source_dir)
            result = self._run(["write-tree"], index_file=index_file, work_tree=source_dir)
            return result.stdout.decode("utf-8").strip()

    def write_tree_from_worktree(self) -> str:
        """`write_tree_from_dir(self.work_tree)`--see there."""
        return self.write_tree_from_dir(self.work_tree)

    def write_tree_single_file(self, filename: str, blob_sha: str) -> str:
        """Build a tree containing exactly one file (`filename` -> `blob_sha`)--used for
           `version-data`'s commits, which are never more than `contribution-version-data.json`."""
        result = self._run(["mktree"], input=f"100644 blob {blob_sha}\t{filename}\n".encode())
        return result.stdout.decode("utf-8").strip()

    def commit_tree(
                self, tree: str, parents: list[str], message: str, *, trailers: dict[str, str] | None = None,
            ) -> str:
        full_message = message
        if trailers:
            trailer_lines = "\n".join(f"{k}: {v}" for k, v in trailers.items())
            full_message = f"{message}\n\n{trailer_lines}"
        args = ["commit-tree", tree]
        for parent in parents:
            args += ["-p", parent]
        result = self._run(args, input=full_message.encode())
        return result.stdout.decode("utf-8").strip()

    def read_file_at(self, ref: str, path: str) -> bytes | None:
        """The content of `path` as it exists in `ref`'s tree (e.g. `read_file_at("server",
           "cover.png")`), or None if `path` doesn't exist there. Used to reuse a previously-fetched
           cover image's bytes straight from the object database, without needing a live cached
           file anywhere on disk (see `fetch()`'s cover-reuse logic)."""
        result = self._run(["cat-file", "-e", f"{ref}:{path}"], check=False)
        if result.returncode != 0:
            return None
        return self._run(["show", f"{ref}:{path}"]).stdout

    def read_trailers(self, commit: str) -> dict[str, str]:
        """The git trailers (`Key: Value` lines) on `commit`'s message--via `git interpret-
           trailers --parse`, robust to trailer-format edge cases (folding, repeated keys, etc.)
           we don't want to hand-parse ourselves."""
        message = self._run(["log", "-1", "--format=%B", commit]).stdout
        parsed = self._run(["interpret-trailers", "--parse"], input=message).stdout.decode("utf-8")
        trailers: dict[str, str] = {}
        for line in parsed.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                trailers[key.strip()] = value.strip()
        return trailers

    # --- porcelain against the real `main` checkout (`work_tree`) --------------------------------

    def commit_worktree(self, message: str) -> str:
        """`add -A && commit -m <message>` against the real working tree--the only method here
           that touches the real index/`HEAD`, always on whatever branch is currently checked out
           (always `main`, by construction--`server`/`version-data` are never checked out)."""
        self._run(["add", "-A"])
        self._run(["commit", "-m", message, "--allow-empty"])
        result = self._run(["rev-parse", "HEAD"])
        return result.stdout.decode("utf-8").strip()

    def checkout_all(self, ref: str) -> None:
        """Reset the index, the working tree, *and* remove untracked files/directories, so the
           working tree ends up matching `ref`'s content *exactly*--without moving `HEAD` or
           creating a commit. Used by `revert()`/`rebase()`'s fast-forward/`merge_discard_local()`.

           Two things confirmed necessary by direct testing, not just one: `read-tree --reset -u`
           (rather than `checkout <ref> -- .`, which only adds/updates paths present in `ref`, and
           never removes a *tracked* path that's absent there) handles files that are tracked but
           shouldn't be anymore--but it leaves untracked files (never `git add`-ed at all) alone
           entirely, since that's simply outside its scope. `clean -fd` handles that remaining
           case. Together, nothing extra survives, tracked or not."""
        self._run(["read-tree", "--reset", "-u", ref])
        self._run(["clean", "-fd"])

    def merge_branch(self, branch: str) -> bool:
        """`git merge <branch>` against the real working tree.

        Returns:
            True if the merge completed cleanly (a new merge commit was made, or it was already
            up to date/fast-forwarded); False if it stopped with conflicts (`MERGE_HEAD` now
            exists--resolve and call `merge_continue()`, or `merge_abort()`).
        """
        result = self._run(["merge", "--no-edit", branch], check=False)
        return result.returncode == 0

    def merge_head_exists(self) -> bool:
        return self.rev_parse("--verify", "-q", "MERGE_HEAD", check=False) is not None

    def merge_continue(self) -> None:
        """Finish an in-progress merge: stage everything currently on disk (`add -A`--so hand-
           editing a conflicted file and running this directly, without `git mergetool`/manually
           `git add`-ing it first, works the same way it always did in the old marker-scan-based
           design) and commit.

           Whether a path is conflicted at all is still git's own authoritative index-stage
           tracking (`status_conflicts()`), not content-scanning--but `add -A` blindly stages
           whatever's on disk regardless of content, so a leftover `<<<<<<<` marker in a path git
           *does* consider conflicted would otherwise get silently committed as real content if
           the user forgot to actually resolve it (only relevant for hand-editing; `git mergetool`
           itself already only stages a path once its own diff view reports no conflict left).
           So: check current content of just the *still-unmerged* paths for a leftover marker
           first, before staging anything--narrower and cheaper than the old design's whole-tree
           content scan, and it can't false-positive on a path that was never conflicted.

        Raises:
            CgGitError: if unresolved conflict markers remain in a still-unmerged path, or (from
                        git itself) if `commit` refuses for any other reason.
        """
        conflicted = self.status_conflicts()
        for rel_path in conflicted:
            content = (self.work_tree / rel_path).read_bytes()
            if b"<<<<<<<" in content:
                raise CgGitError(
                        ["<merge_continue>"], 1,
                        f"{rel_path} still has an unresolved conflict marker--resolve it, then run "
                        "`cg contribution merge continue` again.",
                    )
        self._run(["add", "-A"])
        self._run(["commit", "--no-edit"])

    def merge_abort(self) -> None:
        self._run(["merge", "--abort"])

    def status_conflicts(self) -> list[str]:
        """Paths with unresolved merge conflicts (unmerged index stages)--authoritative, unlike
           the old content-based `<<<<<<<` marker scan it replaces."""
        result = self._run(["diff", "--name-only", "--diff-filter=U"])
        return [line for line in result.stdout.decode("utf-8").splitlines() if line]

    def diff_text(self, *refs: str) -> str:
        """`git diff <refs...>`--one ref diffs it against the working tree, two diffs between
           them."""
        return self._run(["diff", *refs]).stdout.decode("utf-8", errors="replace")

    def diff_name_status(self, *refs: str) -> list[tuple[str, str]]:
        result = self._run(["diff", "--name-status", *refs])
        pairs: list[tuple[str, str]] = []
        for line in result.stdout.decode("utf-8").splitlines():
            if not line:
                continue
            status, _, path = line.partition("\t")
            pairs.append((status, path))
        return pairs

    def mergetool(self, tool: str | None = None) -> int:
        args = ["mergetool"]
        if tool is not None:
            args += ["-t", tool]
        return self._run_interactive(args)
