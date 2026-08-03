# Working directories

Both managers put a single puzzle or contribution into a directory on disk, with the same split:

```
<root>/
    data/            your content -- the only thing that is ever pushed
    .meta/           server-derived cache and scaffolding -- gitignored, disposable
    solution.py      convenience symlink -> data/solution.src
    puzzle.json      identity: which puzzle/contribution this directory is
```

## `data/` is yours

Everything under `data/` is content you edit and that gets sent to the server. For a puzzle that's
just `solution.src`. For a contribution it's the solution plus the statement, constraints,
input/output descriptions, stub generator, cover image, and a `tests/` tree.

## `.meta/` is a cache

Nothing in `.meta/` is precious. It holds the test-session handle, downloaded test cases, cached
statement copies, snapshots, and — for contributions — the git repository used for merges. It is
gitignored on purpose, so a fresh clone of a repo containing a working directory won't have it.

That's what `repair()` is for:

```bash
cg puzzle repair
cg contribution repair
```

Both rebuild `.meta/` from the identity file without touching `data/`. If something in `.meta/`
looks wrong, deleting it and repairing is always a valid move.

**Don't treat `.meta/`'s git history as a backup.** For contributions it exists to make merge
resolution feel familiar, not to preserve anything. The only durable copy of your work is on the
server, and the server keeps exactly one solution per contribution with no history.

## The solution symlink

`solution.<ext>` at the root points at `data/solution.src`. The single real file has a fixed name so
tooling can find it; the symlink gives it an extension so your editor picks the right language,
syntax highlighting and language server. Change languages and the symlink is re-pointed for you.

Open whichever you like — the debugger is wired to work through either, no matter how many symlink
hops sit between the file you have open and the file that runs.

## Test cases

Both managers keep test cases on disk, but they are **not** the same kind of thing, and the
difference is deliberate:

| | puzzle `.meta/tests/` | contribution `data/tests/` |
| --- | --- | --- |
| Origin | files downloaded from the server, byte-for-byte | strings the server stores, rendered into files |
| Editable? | no — server truth, rebuilt by `repair()` | yes, that's the point |
| Pushed back? | never | yes |
| Final newline | exactly as downloaded | one added by this client |

That last row causes real bugs if you get it wrong, which is why it's written down. A contribution's
test-case file carries a terminator that isn't part of the value; a puzzle's doesn't. See
[final newlines](../design/final-newlines.md) — it's measured, not assumed.

## Puzzles vs. contributions

The same layout, but very different amounts of machinery:

| | puzzle | contribution |
| --- | --- | --- |
| Editable files | one | many |
| Git repo in `.meta/` | no | yes — for three-way merges against the server |
| Server keeps history? | yes, per language | no — one solution, no history |
| Conflict handling | `cg puzzle discard-local` | `cg contribution rebase` / `merge` |

A puzzle has exactly one editable file, so there is nothing to merge — hence no git repo. A
contribution has a dozen, any of which can change on the server while you're editing, so it gets a
real git repo and a real merge workflow.
