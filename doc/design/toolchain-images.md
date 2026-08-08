# Composable toolchain images

`cg` runs compiled and interpreted languages inside a container so you don't need a local toolchain
for a language you touch once. The question this page answers is why that's **one image carrying
every language**, built from composable fragments, rather than the obvious one-image-per-language.

## The obvious design, and why it fails

The first implementation was per-language: C++ was `FROM gcc:14` plus gdb, tagged `cg-cpp:<hash>`,
with one container per (working directory × language). It broke on contact with three things.

**A per-language base can't compose.** Two images cannot both be `FROM`. The moment a workspace
holds a C++ puzzle and a Python one, you have two images and two containers, each bind-mounting the
whole workspace, for no benefit.

**It hides the version where nobody looks.** `FROM gcc:14` puts the compiler version in an image
tag. CodinGame runs **gcc 11.2.0**. That drifted two major releases without anything failing, so
C++20 constructs compiled locally and were rejected on submission — the exact failure a pinned
toolchain exists to prevent. Versions now live in fragments, next to a comment saying what was
measured and when.

**Some languages need two toolchains at once.** CodinGame runs Java on JDK 21.0.4 but Clojure,
Groovy and Scala on JVM 1.8 — and keeps four JDKs installed side by side to do it. No image
supporting both Java and Scala can have either own the global `JAVA_HOME`/`PATH`. A per-language
image dodges this by never having to; a shared one must solve it.

## Fragments

A fragment is a slug, a version, a list of dependencies, some Dockerfile lines, and an activation
script:

```python
CgToolchainFragment(
    slug="cpp", version=2, depends_on=("gcc11",),
    dockerfile="",                       # installs nothing
    env_script='. /opt/cg/env.d/gcc11.sh\nexport CG_CXXFLAGS="-std=c++20 -O0 -g ..."\n',
)
```

Two kinds, and the distinction is the point:

- A **subsystem** installs a toolchain — `gcc11`, `python311`, `jdk21`, `dotnet8`, `node20`.
- A **language** usually installs *nothing at all* and only declares a dependency plus flags. `c`
  and `cpp` both depend on `gcc11`; `javascript` and `typescript` both depend on `node20`. That
  sharing is what keeps an image with both from carrying the toolchain twice.

`typescript` is the one language that does install something — the `tsc` npm package onto `node20`.

## Activation scripts, not `PATH`

Each fragment ships `/opt/cg/env.d/<slug>.sh`, which exports what that toolchain needs and sources
its dependencies' scripts first. Every command `cg` runs in the container is prefixed with one line:

```sh
. /opt/cg/env.d/cpp.sh
"$CG_CXX" $CG_CXXFLAGS -x c++ -o "$out" "$src" $CG_CXXLIBS
```

Two alternatives were rejected:

- **A global `PATH`/`JAVA_HOME`** cannot represent two JDKs. The conflict is unrepresentable, not
  merely awkward.
- **Wrapper executables** (`/opt/cg/bin/cpp-compile`) would move compile flags *into the image*,
  versioning them with the image rather than with `cg` — so changing a flag would need a rebuild.
  Env scripts keep the split where it belongs: the **image** knows where its toolchain is, **`cg`**
  knows how to invoke it.

This turned out to be exactly what CodinGame does. Their `PATH` is
`/bin:/usr/bin:/usr/GNUstep/Local/Tools:/usr/GNUstep/System/Tools:/opt/coderunner/groovy/bin` —
every toolchain under its own prefix, only the relevant one exposed. Arrived at independently, which
is mild evidence it's the right shape.

Verified on the built image: `java`, `javac`, `dotnet`, `node`, `npm` and `tsc` are **absent from
the global `PATH`**, reachable only by sourcing their script.

## Ordering is load-bearing

Fragments are resolved transitively and topologically sorted, **breaking ties by slug**. That
determinism isn't tidiness — it's what makes a subset's Dockerfile a literal *prefix* of a
superset's, so Docker's layer cache is shared between them. Measured:

| | body lines | identical prefix |
| --- | --- | --- |
| `C++` | 25 | — |
| `C++`, `Python3` | 40 | **25** |

So adding a language rebuilds only from the point it's added, and a user who trims to `C++` and
later adds `Python3` reuses everything already built.

The image tag is the SHA-256 of the composed Dockerfile, which means correct subset/superset tagging
falls out with no extra logic. It also makes the tag **order-insensitive**: `--languages C,C++`,
`--languages "C++,C"` and `--languages C++ C` all produce the same tag, because the composer sorts
before it renders.

## Why the default is everything

The full 8-language image is **1.89 GB**; C++ alone is about 400 MB. That ratio is the argument: the
languages that dominate the size (JDK, .NET SDK, Node) share one Debian base rather than each
dragging its own, so trimming saves far less than the confusion of having to choose. `cg` defaults
to all of them and lets `toolchainLanguages` narrow it.

The default set is **derived, never hardcoded** — a language is in it exactly when it declares a
`toolchain_fragment`. Adding a language is one module, and the two can't drift apart.

## The tag must cover what's actually built

`cg` writes a `base.dockerfile` it owns and appends a `custom.dockerfile` the user owns, and the
image tag hashes the **composed** result. This is easy to get subtly wrong: the `custom.dockerfile`
`cg` generates is entirely comments, which is still content, so hashing the base alone yields a tag
no image will ever have. `cg docker toolchain show` composes in memory precisely so it can report
the true tag without overwriting the user's base file.

That's also what makes `cg docker toolchain build` a genuine prewarm rather than a similar-looking
build: it goes through the same `ensure_image` the run path uses, so the two cannot disagree about
what to build or what to call it.

## Multi-architecture

`docker buildx build --load` can only load a **single** platform into the local daemon — a
multi-platform image is a manifest list, which the daemon's image store has no way to represent. So:

- one platform, or none → loads locally;
- more than one → requires `--push` to a registry.

`cg` checks this before invoking Docker and says so, because buildx's own failure for it is obscure
and the fix isn't guessable from the message.

## See also

- **[What CodinGame actually runs](codingame-runtime.md)** — the measured versions these fragments
  pin, and how to re-measure them.
- `codingame_tools.language.toolchain` — the fragment model and composer.
- `codingame_tools.language._docker` — image/container lifecycle, and why state lives on the Docker
  objects rather than beside them.
