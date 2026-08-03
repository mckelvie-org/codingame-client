# Debugging solutions

Set a breakpoint in your solution, run a test case, and step through it — including for compiled
languages you have no local toolchain for.

## Generate the VS Code configuration

```bash
cg puzzle vscode
cg contribution vscode
```

This writes into your **workspace root's** `.vscode/`, merging with what's already there and
replacing only this working directory's own entries. Workspace root, not the working directory,
because VS Code only reads `launch.json` from the workspace root — a `.vscode/` inside a
subdirectory is ignored.

The test-case dropdown is built from the test cases actually on disk, so re-run this after
`import` or `repair` to refresh it. Entries `cg` owns are prefixed so they're recognisable and so
regeneration replaces them instead of accumulating duplicates. If it can't safely merge — a
`launch.json` with comments, say — it says so rather than mangling your file.

## Python

The debugger launches your solution in-process, so a breakpoint set directly in `solution.py` is
hit. Pick a test case from the dropdown, run, and stdin is bound to that test's input.

It works through the symlink too: whether you have `solution.py` or `data/solution.src` open, the
breakpoint matches. The target is run at exactly the path you had focused, so there's no
symlink-resolution mismatch to work around.

## C++ (and other containerised languages)

No local compiler, no local gdb, no local anything except Docker.

`cg` builds a debug profile in the container, starts a stopped `gdbserver`, and VS Code attaches
through `docker exec`. Stdin is redirected from the test case inside the container, which sidesteps
the debug adapter's own unreliable stdin handling entirely.

Normally you never invoke these by hand — the generated tasks do — but they exist:

```bash
cg contribution debug start 1 local
cg contribution debug stop
cg puzzle debug start 1
cg puzzle debug stop
```

`stop` always succeeds, including when nothing is running: it's wired to a post-debug task, which
fires even for a session that never really started.

### First run is slow

Building the image the first time takes minutes. Afterwards it's cached and effectively instant.
To get it over with before you start:

```bash
cg puzzle build
```

### Tweaking the toolchain

The image is defined by a Dockerfile in a shared per-user location, split in two: a `cg`-owned base
that's regenerated when the tool updates, and a file of your own that's appended and never touched.
Put extra packages in the second one. Because it's shared, tweaking a language once applies to every
puzzle and contribution using it.

### Cleaning up

```bash
cg docker clean
```

Removes every container and image `cg` created. Always safe, no prompt, no `--force` — no user work
ever lives in one. Your source is bind-mounted read-only from disk and all build artifacts are
disposable, so the worst case is one slow rebuild.

## What gets debugged with what stdin

A detail that matters if you're comparing local behaviour against the server: the debugger feeds
exactly the same bytes as `cg ... play` and as CodinGame itself. For contributions that means the
final newline this client adds to test-case files on disk is stripped back off before it reaches
your program. See [final newlines](../design/final-newlines.md) — this was a real bug, and it's
one byte.
