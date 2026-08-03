# Concepts

Four ideas explain most of how `cg` behaves. Worth ten minutes before the guides.

- **[Authentication](authentication.md)** — CodinGame has no API tokens, so `cg login` drives a real
  browser and captures the resulting session cookies.
- **[Profiles](profiles.md)** — named identities with their own credentials and defaults, plus the
  `config.yaml` / `settings.json` split and how the two resolve.
- **[Working directories](working-directories.md)** — the `data/` + `.meta/` layout both managers
  share: what's yours, what's a disposable cache, and why puzzles have no git repo but contributions
  do.
- **[Languages and toolchains](languages.md)** — how a language is chosen, and how compiled
  languages build and run in Docker without you installing a toolchain.

See also the [design notes](../design/index.md) for decisions that aren't obvious from the code.
