# Contributing

This project uses [PDM](https://pdm-project.org/) for dependency management, linting, type checking, and testing.

### 1. GitHub environments

Run script `bin/install-github-invironments` to set up GitHub for building and publishing.
This will create two GitHub environments:

- **`testpypi`** — used by `publish-test.yml`
- **`pypi`** — used by `publish.yml`

No secrets or protection rules are required; the environment names are what
the workflows reference.

### 2. TestPyPI trusted publisher

On [test.pypi.org](https://test.pypi.org), go to **Account → Publishing → Add a
new pending publisher** (use "pending" because the project won't exist there yet):

| Field | Value |
|---|---|
| PyPI project name | `codingame-client` *(or your fork's package name)* |
| Owner | `sammck` *(or your fork's GitHub owner) |
| Repository | `codingame-client` |
| Workflow | `publish-test.yml` |
| Environment | `testpypi` |

### 3. PyPI trusted publisher

On [pypi.org](https://pypi.org), same flow — **Account → Publishing → Add a new
pending publisher**:

| Field | Value |
|---|---|
| PyPI project name | `codingame-client` *(or your fork's package name)* |
| Owner | `sammck` *(or your fork's GitHub owner) |
| Repository | `codingame-client` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

### Trigger sequence

Once the above is in place:

1. (optional) `bin/bump-dev [patch|minor|major]` — for a deliberate semantic version bump on `main`
2. `bin/cut-rc` — pushes a `v*-rc.*` tag → triggers `publish-test.yml` → TestPyPI, then waits for that workflow and reports its outcome
3. `git checkout v<x.y.z>-rc.<n>` — check out the rc that TestPyPI just accepted
4. `bin/cut-prod` — pushes a `v*.*.*` tag → triggers `publish.yml` → PyPI + auto-bumps `main`, then waits for that workflow and syncs your local `main`

---

## Development setup

```bash
bin/install        # first-time setup (installs PDM and dependencies)
pdm install -G dev # subsequent dependency updates
pdm run lint       # ruff check
pdm run typecheck  # mypy
pdm run test       # pytest
pdm build
```

## Release workflow

Releases follow a three-channel model:

| Channel | Tag format             | Moving tag   | Index    |
|---------|------------------------|--------------|----------|
| dev     | —                      | —            | —        |
| rc      | `v<x.y.z>-rc.<n>`     | `rc-latest`  | TestPyPI |
| prod    | `v<x.y.z>`             | `prod-latest`| PyPI     |

The `main` GitHub branch is the only relevant branch, and always carries `X.Y.Z-dev.N` as the package version.
It is never necessary to check out any other branch. Releases are driven entirely by tags on branchless commits —
no `rc` or `prod` branches are created. When a release is cut, a custom tagged commit with only the modified version
information is created--that commit is not on any branch, and the only thing keeping the commit alive is
the tag that labels it. This approach ensures that prod/rc version labels never leak into development code, and that
dev versions always apear "newer" than rc or prod versions they are based on, and older than the prod/rc versions they become.

### Bump the dev version

Cutting an rc doesn't require bumping the dev release number first -- the rc counter
(`X.Y.Z-rc.N`) is unique on its own, independent of whatever `N` `main`'s own `X.Y.Z-dev.N`
currently carries. Use `bin/bump-dev` when you want a deliberate version bump ahead of time,
most commonly a semantic one (a new `X.Y.Z`):

```bash
bin/bump-dev [dev|patch|minor|major]   # edits pyproject.toml, does not commit
```

| `bump_type` | Example |
|-------------|---------|
| `dev`       | `1.0.0-dev.1` → `1.0.0-dev.2` |
| `patch`     | `1.0.0-dev.2` → `1.0.1-dev.1` |
| `minor`     | `1.0.0-dev.2` → `1.1.0-dev.1` |
| `major`     | `1.0.0-dev.2` → `2.0.0-dev.1` |

This will modify pyproject.toml to reflect the version change.
Commit and push to `main` before cutting a release.

### Cut a release candidate on TestPyPi

Run from `main`:

```bash
bin/cut-rc [--force]
```

`cut-rc` first requires a clean working tree and local `main` to be exactly in sync with
`origin/main` (any mismatch -- ahead, behind, or diverged -- is an error; pull/rebase and/or push
to fix). From `main`'s current `X.Y.Z-dev.N`, it finds the next unused rc counter from existing
`v<x.y.z>-rc.*` tags, sets the version to `X.Y.Z-rc.N` in a worktree, tags the commit
`v<x.y.z>-rc.<n>`, and pushes the tag — triggering the `Publish TestPyPI` workflow.

`cut-rc` then waits for that workflow and shows its live status. The workflow itself polls
TestPyPI until the version is actually visible there before reporting success (the upload API call
succeeding doesn't mean the index has caught up yet -- there's a brief propagation window), and
updates the `rc-latest` tag. If the workflow fails, `cut-rc` reports it and exits non-zero.

Use `--force` to overwrite an existing tag and retry a failed publish.

### Cut a production release

`cut-prod` promotes an rc that has *already been published to TestPyPI* -- it isn't just working
from a version string, it verifies the rc is really there. The recommended flow is to check out
the rc tag first, so you're never sitting on `main` (and therefore never at risk of doing new work
on `main`) while a release is in flight:

```bash
git checkout v<x.y.z>-rc.<n>
bin/cut-prod [--force]
```

`RC_REF` (`bin/cut-prod [--force] [RC_REF]`) is optional. Resolution order:
1. Explicit argument (tag, sha, or bare version like `1.0.5-rc.1`).
2. `HEAD`, if it is itself tagged with a `v<x.y.z>-rc.<n>` tag (the normal case after `git checkout` above).
3. The `rc-latest` tag (the most recently published rc), if HEAD isn't tagged.

`cut-prod` requires:
- A clean working tree.
- If you're on a named branch (rather than detached at an rc tag), that branch must be exactly in
  sync with its upstream -- no local-only commits. A detached rc checkout has nothing to sync,
  since the commit is already reachable from origin via its tag.
- The resolved rc version must actually exist on TestPyPI (checked directly against
  `test.pypi.org`, with a short retry to ride out any residual index-propagation lag) --
  promoting an rc that never successfully published is refused.

It also warns (without blocking) if `origin/main` has moved since the rc was cut, in case that
matters to you.

Strips the rc qualifier, commits to a worktree, tags the commit `v<x.y.z>`, and pushes the tag —
triggering `Publish`, which (like `Publish TestPyPI`) polls PyPI until the version is actually
visible before reporting success, updates `prod-latest`, and then ensures `main` carries a dev version
strictly ahead of the one just published, bumping to `X.Y.(Z+1)-dev.1` if needed. This is safe with
other developers landing commits on `main`, or another release racing to bump it at the same time:
every attempt re-fetches the live tip of `main` and re-evaluates whether a bump is still needed from
scratch, rather than trusting a stale snapshot, and retries a few times if its push loses a race
(the winner's bump may already satisfy the requirement, in which case there's nothing left to do).

After pushing the prod tag, `cut-prod` waits for the triggered `Publish` workflow to finish and
shows its live status. On success, it syncs your local `main` with `origin/main` (which the
workflow may have just bumped) -- rebasing in place if `main` is your current branch, or otherwise
just fast-forwarding the local `main` ref without touching your current (normally still-detached)
checkout. On failure, it reports the error and exits non-zero; `main` is left alone.

Use `--force` to overwrite an existing tag and retry a failed publish.

### Guards

Both publish workflows validate that:

- The version in `pyproject.toml` matches the expected format for the target index.
- The version does not already exist on the target index.
- Lint, type checks, and tests pass.

### Smoke test

Use the **Install Smoke Test** workflow to verify an install without publishing:

```bash
# From GitHub source
gh workflow run install-smoke.yml --field source=github --field git_ref=main

# From TestPyPI
gh workflow run install-smoke.yml --field source=testpypi --field version=1.0.0rc1
```

## Forking this repository

If you fork this project and want the full release pipeline to work, you need
to wire up OIDC trusted publishing on both PyPI indexes.
