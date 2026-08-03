# Profiles

A profile is a named identity plus its own stored [credentials](authentication.md). Every command
takes `--profile NAME`; without it, the default profile is used.

```bash
cg --profile dev login
cg --profile dev whoami
```

Two reasons this exists, and the second matters more than it looks:

- **More than one CodinGame account.** A personal one and a test one, say.
- **Somewhere safe to experiment.** Several operations in this project are irreversible against
  real content — pushing a contribution overwrites its only stored solution, submitting a puzzle
  creates a permanent graded submission. A separate profile is the sanctioned way to try those
  without touching anything you care about.

```bash
cg settings set default-profile dev     # make it the default
cg settings delete default-profile      # go back
```

## Configuration vs. settings

Two files, deliberately distinct, and mixing them up causes confusion later:

| | `config.yaml` | `settings.json` |
| --- | --- | --- |
| Owned by | you | the app |
| Edited by | hand | `cg settings set` |
| Holds | how you want things configured | state the app remembers for you |
| Under version control? | reasonably, for a project-local one | no |

```bash
cg config init            # create a project-local config.yaml here
cg config init --global   # create the shared per-user one instead
cg config where           # which config.yaml is in play, and where its data directory resolves
cg config dump            # the fully resolved configuration, as JSON
cg settings dump          # the fully resolved settings, as JSON
```

## Resolution order

Configuration resolves in three tiers, **field by field**, most specific first:

1. `settings.json` (app-managed state)
2. the project-local `config.yaml` (nearest one at or above the working directory)
3. the global `config.yaml`

Field-by-field is the part worth internalising. A project-local config that sets one key does not
mask the global config's other keys — earlier versions merged whole files, and a project config with
a single setting in it would silently blank everything else. If a value isn't behaving as you
expect, `cg config dump` shows you what actually won.

## Default working directories

Both managers look for a working directory rather than taking one as an argument every time, and
those defaults are per-profile settings:

```bash
cg settings set puzzle-dir ~/cg/puzzle
cg settings set contribution-dir ~/cg/contribution
```

Without a setting, resolution falls back to the current directory, and then to `./puzzle` or
`./contribution`. `cg puzzle where` and `cg contribution where` answer "which directory would this
command actually use", which is usually faster than reasoning about it.
