# Puzzle and contribution managers

The layer between the [raw client](../client/index.md) and the [CLI](../cli/index.md). Each manager
owns one working directory and knows how to sync it with the server. The CLI is a thin shell over
these — anything `cg` can do, a script can do.

```python
from codingame_tools.client import CgClient
from codingame_tools.puzzle_manager import CgPuzzleManager

async with CgClient() as client:
    manager = CgPuzzleManager(Path("./puzzle"), client)
    await manager.import_("temperatures")
    results = await manager.play()
```

- **[Puzzle manager](puzzle-manager.md)** — one editable file, no git, per-language server history.
- **[Contribution manager](contribution-manager.md)** — many editable files, a real git repo, and a
  merge workflow.

## What they share

Both follow the same [working-directory layout](../concepts/working-directories.md) and the same
lifecycle:

| | |
| --- | --- |
| `import_()` | Build a fresh working directory from the server. |
| `repair()` | Rebuild `.meta/` from the identity file, without touching `data/`. |
| `status()` | Summarise local state; optionally check against the server. |
| `discard_local()` | Throw local edits away and match the server. |
| `play()` | Run the solution against local test cases, no network. |
| `build()` | Compile, for languages that need it. |
| `set_language()` | Switch language. |
| `delete()` | Tear down. |
| `provision_vscode()` | Write VS Code run/debug configuration. |

Everything is `async`, including `delete()` — tearing down a working directory also removes any
containers it owns.

## Naming follows git

Where an operation has a git analogue, it uses git's word, because these are operations people
already have intuitions about:

| | |
| --- | --- |
| `push()` | send local content to the server |
| `fetch()` | retrieve server state without touching your files |
| `rebase()` | reconcile with an advanced server, when unambiguous |
| `merge_start()` / `merge_continue()` / `merge_abort()` | when it isn't |
| `discard_local()` | throw local changes away |

Deviations from git's meaning are called out explicitly in the docstrings where they exist. The one
worth internalising: `push()` is not `git push`. There is no history on the server — each push
overwrites the single stored version.
