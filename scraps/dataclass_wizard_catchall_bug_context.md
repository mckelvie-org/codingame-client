# Context: dataclass_wizard `CatchAll` reuse bug — debug + PR

You're picking up an investigation into a real bug in `dataclass_wizard` 1.0.0. The goal now is
to find the root cause in the library's own source, fix it, and prepare a PR. This file is
self-contained context for a fresh session — you shouldn't need anything else to get started,
though the pointers below tell you exactly where to look.

## Where things live

- **The fork to work in:** `/Users/sam/projects/pypi/dataclass-wizard` — a clean checkout of
  `git@github.com:mckelvie-org/dataclass-wizard.git` (`origin`), currently on `main`, HEAD at
  commit `57535e9` ("Bump version: 0.39.1 → 1.0.0"), working tree clean, unmodified. This is a
  sibling directory to `codingame-client` (the client library that surfaced the bug), not a
  subdirectory of it.
- **The client project that depends on it:** `/Users/sam/projects/pypi/codingame-client` — a
  Python CodinGame API client. Its `.venv` has `dataclass-wizard==1.0.0` installed (pip), which
  as of now is identical in content to the fork's current HEAD.
- **Standalone minimal reproduction (already written and verified):**
  `/Users/sam/projects/pypi/codingame-client/scraps/demo_dataclass_wizard_catchall_reuse_bug.py`
  — depends only on `dataclass_wizard` + stdlib, no import from the client project. Six isolated
  scenarios, each documented with a comment explaining what it proves. Run it against the fork
  with:
  ```
  cd /Users/sam/projects/pypi/codingame-client
  PYTHONPATH=/Users/sam/projects/pypi/dataclass-wizard python3 \
      scraps/demo_dataclass_wizard_catchall_reuse_bug.py
  ```
  Already confirmed (2026-07-26): all 6 scenarios reproduce identically against the fork's own
  source via this `PYTHONPATH` override, so the bug lives in the fork as of its current HEAD, not
  something specific to the pip-packaged build.
- **Persistent memory** (survives across Claude sessions on this machine):
  `project_dataclass_wizard_catchall_reuse_bug.md` in the codingame-client project's memory store
  documents this same finding for future reference from the client-project side.

## The bug, precisely

A dataclass with a `CatchAll` field (`from dataclass_wizard.models import CatchAll`, used to
capture unrecognized JSON keys into a dict) can only be successfully loaded/dumped by
dataclass_wizard 1.0.0 in **one distinct structural context per process**. "Context" means: used
as the direct top-level target of `.from_dict()`/`.to_dict()`, vs. used as a field of enclosing
class X, vs. used as a field of enclosing class Y — each is different. Whichever context is hit
FIRST works. Any SECOND, differently-shaped use of that *same class* then fails, permanently, for
the rest of the process, with:

```
TypeError: issubclass() arg 1 must be a class
```

raised from `dataclass_wizard/_loaders.py`, function `load_dispatcher_for_annotation`, at the line
`if issubclass(origin, t):` (dump side: `dataclass_wizard/_dumpers.py`, analogous function/line).

This is **not recursion-specific** — plain, non-self-referential classes hit it too, e.g. calling
`.from_dict()` directly on some class `Leaf` (with a `CatchAll` field), then later parsing a
different class that has `Leaf` as a nested field, breaks the second call. Self-referential
("recursive": a class with a field typed as itself, e.g. `children: list[Self]`) classes are a
special case that fails on their very *first* use rather than their second — see "root cause"
below for why that's consistent with the same defect, not a separate one.

## Root cause — a strong, code-verified lead (not yet fixed, but this should save you the hunt)

Found by direct source reading, not just symptom-poking. In `dataclass_wizard/_loaders.py`,
inside `load_func_for_dataclass`:

```python
field_to_aliases = resolve_dataclass_field_to_alias_for_load(cls)
...
catch_all_field: str | None = field_to_aliases.pop(CATCH_ALL, None)
has_catch_all = catch_all_field is not None
```

`resolve_dataclass_field_to_alias_for_load` (in `dataclass_wizard/_class_helper.py`) is:

```python
def resolve_dataclass_field_to_alias_for_load(cls):
    if cls not in IS_CONFIG_SETUP:
        setup_config_for_cls(cls)
    return DATACLASS_FIELD_TO_ALIAS_FOR_LOAD[cls]
```

`DATACLASS_FIELD_TO_ALIAS_FOR_LOAD` is a module-level `WeakKeyDictionary` keyed only by `cls` —
i.e. this returns a **direct reference to a dict cached once per class**, not a copy. The
`.pop(CATCH_ALL, None)` call back in `load_func_for_dataclass` then **destructively mutates that
shared cached dict**, permanently removing the `CATCH_ALL` marker from it.

Consequence: the first time `load_func_for_dataclass(cls)` runs for a given class (in whatever
context triggers it first), `has_catch_all` is correctly `True`, codegen special-cases and strips
the `CatchAll` field as intended, and the call succeeds — but the shared per-class alias cache is
now permanently missing its `CATCH_ALL` entry. If `load_func_for_dataclass` is invoked again for
the *same class* in a **different context** (different enclosing class, or top-level vs. nested,
which apparently doesn't hit a compiled-function cache and reruns this codegen path from
scratch — worth confirming exactly why/where that recompilation is triggered as part of the fix),
`has_catch_all` is now incorrectly computed as `False`. The `CatchAll`-typed field is no longer
stripped/special-cased, so its declared type annotation gets resolved through the *normal* dispatch
path instead — and that field's annotation is:

```python
# dataclass_wizard/models.py
CatchAll = NewType('CatchAll', Mapping)
```

A `typing.NewType` instance is a callable, **not a class**. When the normal dispatch path
eventually calls `issubclass(origin, t)` with this `NewType` object as `origin`, it raises exactly
the observed `TypeError: issubclass() arg 1 must be a class`.

The exact same pattern exists on the dump side: `dataclass_wizard/_dumpers.py` has
`catch_all_name: str | None = field_to_alias.pop(CATCH_ALL, None)` sourced from
`resolve_dataclass_field_to_alias_for_dump`, which returns `DATACLASS_FIELD_TO_ALIAS_FOR_DUMP[cls]`
the same direct-reference way.

This also cleanly explains why **self-referential classes fail on their very first use** rather
than their second: resolving a self-referential class as a top-level `.from_dict()` target
requires dataclass_wizard to generate codegen for that class *twice* within a single call — once
for the top-level entry, and again when the self-referential field (`children: list[Self]`, a
forward reference to the same class) is resolved during that same codegen pass. The second,
inner invocation of `load_func_for_dataclass` for that class already sees the freshly-mutated
(post-`.pop()`) cache from the first, outer invocation, moments earlier in the same call stack —
so the "first use always succeeds, second use fails" rule applies even here, just compressed into
a single top-level call instead of two separate ones.

**Likely fix direction** (not yet attempted/verified — this is a lead, not a patch): stop
mutating the shared cached dict as a side effect of reading it. E.g. copy it before popping
(`field_to_aliases = dict(resolve_dataclass_field_to_alias_for_load(cls))`), or look up/remove the
`CATCH_ALL` marker without mutating the cache (e.g. `field_to_aliases.get(CATCH_ALL)` plus tracking
the index/stripped name locally rather than `del`-ing from `field_to_aliases` itself), doing the
same on the dump side. Before committing to this as *the* fix: trace why/where
`load_func_for_dataclass` gets re-invoked for a class it's already generated code for in a
different context in the first place (there may be a caching layer above this — `CLASS_TO_LOADER`/
`CLASS_TO_DUMPER` in `_class_helper.py` — that's supposed to prevent recompute per-class but
evidently keys or checks something that differs across "top-level" vs "nested-in-X" vs
"nested-in-Y" contexts; understanding *that* fully will make the fix airtight rather than a patch
over a symptom).

## What "done" looks like

1. Root cause identified and understood well enough to explain *why* dataclass_wizard's design
   makes this class of bug possible (not just where the crash happens).
2. A fix in the fork that makes all 6 scenarios in
   `scraps/demo_dataclass_wizard_catchall_reuse_bug.py` pass (currently scenarios 3, 4, 5, and 6
   fail; only 1, 1b, and 2 currently pass — after the fix, all of them, including 3-6, should
   succeed instead of raising).
3. The fork's own existing test suite (`dataclass-wizard/tests/`) still passes — run it (check
   `dataclass-wizard/Makefile`/`pyproject.toml` for the right test command, likely `pytest` or
   `tox`) before considering this done.
4. Ideally, a new regression test added to the fork's own test suite covering this exact
   scenario (reuse of a `CatchAll`-bearing class across two different structural contexts in one
   process), so it can't silently regress.
5. A PR opened from the fork. Ask the user whether they want it targeted at their own fork's
   `main` (`mckelvie-org/dataclass-wizard`) or upstream (`rnag/dataclass-wizard`, the original
   project) before opening one against a repo they may not have intended — don't assume.
6. Once merged/fixed, the client project (`codingame-client`) should be able to drop its existing
   narrower workaround in `codingame_client/common/dataclass_wizard_x.py`
   (`_is_self_referential`/`_get_wrapper_class`, which only covers the self-referential special
   case) — but that cleanup is a separate follow-up in the *other* repo, not part of this task,
   and shouldn't be done without the user's explicit go-ahead (don't edit sibling repos without
   being asked).
