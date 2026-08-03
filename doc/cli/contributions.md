# Authoring contributions

A contribution is a puzzle you're writing for other people. Unlike a puzzle, it has a dozen editable
pieces — statement, constraints, descriptions, stub generator, test cases, reference solution — any
of which can change on the server while you're working. So the working directory is backed by a real
git repository and there's a real merge workflow.

## Two ways to start

```bash
cg contribution create ./my-puzzle "My Puzzle"   # brand new, purely local
cg contribution import <handle> ./my-puzzle      # existing server-side contribution
```

`create` makes **no network call** and creates nothing server-side. You get a complete working
directory with a Python3 starter solution and a seeded test/validator pair, and nothing exists
remotely until your first `push`. That's deliberate: it means you can start, change your mind, and
delete the directory without ever having published anything.

`import` needs the contribution's handle. To find your own:

```bash
cg contributions
```

## What you edit

Everything under `data/`:

```
data/
    statement.cgmd            the problem statement
    input-description.cgmd
    output-description.cgmd
    constraints.cgmd
    stub-generator.cgstub
    solution.src              the reference solution
    cover.png
    tests/                    ordinal/named/{local,validator}/{input,output}.txt
    contribution-data.json    title, difficulty, topics, language
```

Test cases are directories, not one blob, so they diff and merge sensibly:

```
tests/01/Simple-case/local/input.txt
tests/01/Simple-case/local/output.txt
tests/01/Simple-case/validator/input.txt
tests/01/Simple-case/validator/output.txt
```

Ordinals are a sort key, not an identity — insert `tests/05a/` and it sorts where you'd expect.
Tidy them up afterwards with:

```bash
cg contribution renormalize-tests
```

## Validate before you push

```bash
cg contribution play          # run the reference solution against every local test case
cg contribution play 2        # just ordinal 2
```

Entirely local, no network. This matters more here than for puzzles: `updateContribution` validates
your reference solution against **every** test case server-side and rejects the whole push if any
disagree. Running locally first turns a slow rejection into a fast one.

## Pushing

```bash
cg contribution status        # local summary, no network
cg contribution status --refresh
cg contribution push
```

`push` sends your content, then updates the internal `server`/`version-data` branches to match. On
first push for a `create`d directory it safely creates the server-side contribution.

Two things worth knowing:

- **A contribution stores exactly one solution, with no history.** Each push overwrites the last
  durable copy. `.meta/`'s git repo is scaffolding for merges — not a backup.
- **A heavy contribution can take long enough to time out at the CDN.** `push` handles the HTTP 524
  case by polling until the version increments, rather than failing on a request that probably
  succeeded.

## When the server moves under you

```bash
cg contribution rebase
```

Detects drift and resolves it when unambiguous: a no-op if the server hasn't advanced, a fast-forward
if you have no local edits. When it genuinely conflicts, use the merge state machine — which is
ordinary git, on ordinary files:

```bash
cg contribution merge start      # fetch, then a real `git merge server`
# ...resolve conflict markers in data/ with your editor...
cg contribution merge continue   # stage and commit
cg contribution merge abort      # or back out entirely
```

`merge continue` refuses if a file still contains conflict markers, which catches the classic
"resolved" -that-wasn't.

```bash
cg contribution discard-local    # give up on local edits, match the server exactly
```

## Changing language

```bash
cg contribution set-language C++
```

**Destructive by design** — a contribution has one solution and no per-language memory, so this
replaces it with a starter stub and there's nothing to switch back to. It refuses unless the current
solution is still the generated stub; `--force` discards real work. Save it somewhere outside the
working directory first. See [languages](../concepts/languages.md).

## Deleting

```bash
cg contribution delete
```

Deletes the contribution **from the server**, unrecoverably, and by default removes the working
directory too. Unlike `cg puzzle delete`, this one is not local-only.

## Recovering

```bash
cg contribution repair
```

Rebuilds the git-dir from scratch without disturbing what's already in `data/` — for a fresh clone
(`.meta/` is gitignored) or a corrupted repo.

## Full reference

Every flag of every command: **[`cg contribution` reference](reference/contribution.md)**.
