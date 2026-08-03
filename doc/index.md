# codingame-tools

Solve CodinGame puzzles and author CodinGame contributions from your own editor, with your own
tools, under version control — instead of in the browser IDE.

Everything here is built on a typed async client for CodinGame's private web API, which the project
documents as it goes. There is no public API and no published spec; every endpoint, field and
behaviour described in these docs was reverse-engineered and then confirmed against the live
service. Where something was measured rather than assumed, the docs say so.

## Which layer do you want?

Most people want the first one.

| | |
| --- | --- |
| **[The `cg` CLI](cli/index.md)** | Log in, pull a puzzle or contribution into a local directory, edit it in your editor, run its tests, debug it, push it back. This is the product. |
| **[The programmatic client](client/index.md)** | `CgClient` — an async, fully typed wrapper over the service endpoints, with dataclasses for every request and response. For scripting things the CLI doesn't do. |
| **[Puzzle & contribution managers](tools/index.md)** | The layer in between: the local working-directory model, git-backed merges, local test running. What the CLI is made of, usable directly. |

## Start here

1. **[Authentication](concepts/authentication.md)** — `cg login` drives a real browser, because
   CodinGame has no API tokens.
2. **[Profiles](concepts/profiles.md)** — how more than one identity, and more than one set of
   defaults, coexist.
3. **[Working directories](concepts/working-directories.md)** — the `data/` + `.meta/` layout both
   managers share, what's yours, and what's a cache.
4. **[Solving a puzzle](cli/puzzles.md)** or **[authoring a contribution](cli/contributions.md)**.

## Reference

- **[CLI command reference](cli/reference/index.md)** — 148 commands, generated from the parser
  itself, so it cannot drift from the tool.
- **[Design notes](design/index.md)** — decisions that aren't obvious from the code, and the
  measurements behind them.

## A note on stability

This talks to a private API that its owners are free to change without warning, and does so by
imitating the web client. Two consequences worth knowing up front:

- **Breakage is expected to be occasional**, and will usually look like a schema error naming a
  field that appeared, vanished, or changed shape. Those are quick to fix; the client is written so
  that unknown fields are captured rather than fatal.
- **Some operations are irreversible or visible to other people** — submitting a puzzle solution
  creates a real graded submission, pushing a contribution updates real published content, and
  running a server-side test durably overwrites your saved code. Commands that do any of these say
  so in their help text.
