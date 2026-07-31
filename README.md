# codingame-tools

[![CI](https://github.com/mckelvie-org/codingame-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/mckelvie-org/codingame-tools/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/codingame-tools.svg)](https://pypi.org/project/codingame-tools/)
[![Python versions](https://img.shields.io/pypi/pyversions/codingame-tools.svg)](https://pypi.org/project/codingame-tools/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Python client and CLI for [CodinGame](https://www.codingame.com/): log in, call the
site's internal API, and manage local working directories for both solving puzzles and
authoring/maintaining community contributions (puzzles you publish to CodinGame).

## Highlights

- **`cg` CLI** — a single entry point (`login`, `whoami`, `raw-api`, `api`, `api-helper`,
  `config`, `settings`, plus the two working-directory command groups below).
- **Async + sync API client** — a typed wrapper around CodinGame's internal JSON API
  (session/credential handling, request/response models), usable directly as a library.
- **`cg puzzle`** — a local working directory for solving an existing CodinGame puzzle:
  import a puzzle, edit `data/solution.src`, run it locally or via `cg puzzle push` against
  the real judge, and debug it directly in VS Code against downloaded test cases.
- **`cg contribution`** — a local working directory for authoring/maintaining a CodinGame
  contribution (a puzzle you're writing). `data/` is a real git working tree with `main`/
  `server`/`version-data` branches, so pushing to and pulling from CodinGame's contribution
  server is a git-style fetch/rebase/merge workflow (conflicts included) instead of a
  one-shot overwrite.
- **Shared local test runner** — subprocess-based batch test execution plus an in-process,
  debugger-friendly entry point, used by both `cg puzzle` and `cg contribution` and wired
  into this repo's own `.vscode/launch.json`.

## Installation

```bash
pip install codingame-tools
```

## Quick Start

```bash
cg login                          # opens a browser to authenticate, saves credentials
cg whoami

cg puzzle import <puzzle-id> my-puzzle
cd my-puzzle && $EDITOR data/solution.src
cg puzzle play-local               # run locally against downloaded test cases
cg puzzle push                     # submit to CodinGame

cg contribution import <handle> my-contribution
cd my-contribution && $EDITOR data/solution.src
cg contribution play-local
cg contribution push               # push local commits to the server
```

Or use the client library directly (async-only for now — `codingame_tools.client.sync` is an
unused placeholder; see its module docstring for the plan to eventually drop the async/sync
split and rename `CgAsync*` classes to drop the `Async` prefix):

```python
import asyncio
from codingame_tools.client.async_.client import CgAsyncClient

async def main():
    async with CgAsyncClient() as client:
        me = await client.services.codingamer.find_codingame_points_stats_by_handle(...)

asyncio.run(main())
```

## Documentation

This README is a quick overview. Detailed docs (CLI reference, wire protocol, client
library, contribution manager, puzzle manager) will be broken out into their own pages —
not written yet.

## Supported Python Versions

Python 3.10 through 3.14.

## License

MIT. See [LICENSE](LICENSE).

---

For development and release workflow documentation, see [CONTRIBUTING.md](CONTRIBUTING.md).
