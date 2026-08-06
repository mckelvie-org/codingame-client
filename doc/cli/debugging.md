# Debugging solutions

Set a breakpoint in your solution, run a test case, and step through it — including for compiled
languages you have no local toolchain for.

## Generate the VS Code configuration

```bash
cg vscode install
```

One command for puzzles and contributions alike — with no arguments it sets up every working
directory it can find: the one you're standing in, plus your active puzzle and active contribution.
Pass `--file` to limit it to one.

It writes into your **workspace root's** `.vscode/`, merging with what's already there. Workspace
root, not the working directory, because VS Code only reads `launch.json` from the workspace root —
a `.vscode/` inside a subdirectory is ignored.

**Run it once per language, not once per working directory.** The generated entries contain nothing
specific to a puzzle or contribution, so a single `CG C++: Debug solution` serves every C++ working
directory in the workspace, now and in the future. You do not need to re-run it after an `import`, a
`repair`, a `set-language`, or when you start a new puzzle.

Nothing is written unless you ask: `import`, `create` and `repair` never touch `.vscode/`.

That works because both questions a debug launch has to answer are deferred to launch time:

| Question | Answered by |
| --- | --- |
| Which working directory? | VS Code's `${file}` — whichever tab you have focused |
| Which test case? | that directory's [selected test](#choosing-which-test-to-debug) |

### What it will and won't touch

Generated entries are named in three parts:

```
CG C++: Debug solution
└┬┘ └┬┘  └─────┬─────┘
 │   │         └─ a well-known action name
 │   └─────────── the language
 └─────────────── marks the entry as cg-managed
```

Each level earns its place:

- **`CG `** identifies every entry `cg` has ever written, in any version, so none of them can become
  permanent clutter you'd have to find and delete by hand.
- **The language** keeps languages independent. Provisioning your C++ puzzle will never disturb the
  Python entry in the same workspace.
- **The action** comes from a fixed vocabulary, so re-provisioning replaces an entry rather than
  adding a second one beside it.

Everything else in the file is yours and is left exactly as it was — including anything of your own
that merely starts with `CG`, since only the full `CG …: ` shape counts. Entries are replaced *in
place*, so re-provisioning doesn't reshuffle your file, and a file whose content wouldn't change
isn't rewritten at all. If it can't safely merge — a `launch.json` with comments, say — it says so
rather than mangling your file.

Upgrading picks up after older versions automatically: anything in the `CG …: ` namespace that this
version doesn't generate is removed, whatever it was called. That covers 1.0.x's one-per-working-
directory entries (`CG puzzle: …`) and their `pickString` test-case inputs.

### Checking whether it's current

```bash
cg vscode install --check
```

Reports what would change and exits non-zero if anything would, without writing. Useful after
upgrading `cg`, or in a pre-commit hook if you keep `.vscode/` in version control. There's no
version stamp to compare against — the generated content *is* the version, so "would rewriting
change anything?" is exactly the right question.

## Choosing which test to debug

Running executes every test case; debugging needs exactly one, because there's only one stdin.

```bash
cg puzzle select-test 3
cg contribution select-test 03 local
```

The choice is recorded in that working directory's `.meta/`, so it's per-directory and survives
until you change it. Without one, debugging uses the first test case — the first *local* test for a
contribution, since validators are the hidden scoring ones and landing in one would be surprising.

## Python

The debugger launches your solution in-process, so a breakpoint set directly in `solution.py` is
hit. Stdin is bound to the selected test's input.

It works through the symlink too: whether you have `solution.py` or `data/solution.src` open, the
breakpoint matches. The target is run at exactly the path you had focused, so there's no
symlink-resolution mismatch to work around.

## C++ (and other containerised languages)

No local compiler, no local gdb, no local anything except Docker.

`cg` builds a debug profile in the container, starts a stopped `gdbserver`, and VS Code attaches
through `docker exec`. Stdin is redirected from the test case inside the container, which sidesteps
the debug adapter's own unreliable stdin handling entirely.

Your **workspace** is bind-mounted read-only into the container *at its own path* — `/home/me/work`
inside the container is `/home/me/work` on the host. Two things follow. Breakpoints need no path
mapping at all, because the paths the compiler recorded are already the paths your editor has open.
And one container serves every working directory in the workspace, rather than one per puzzle.

Normally you never invoke these by hand — the generated tasks do — but they exist:

```bash
cg debug start --file puzzle/solution.cpp
cg debug stop --file puzzle/solution.cpp
```

Both work in a puzzle or a contribution and take no test argument; they infer the kind, the working
directory, and the test from `--file` and the selection. The per-kind forms are still there when you
want to name a test explicitly:

```bash
cg puzzle debug start 1
cg contribution debug start 03 local
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
