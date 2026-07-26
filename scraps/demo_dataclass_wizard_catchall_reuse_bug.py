#!/usr/bin/env python3
"""
Minimal, standalone demonstration of a dataclass_wizard 1.0.0 bug.

Depends on nothing but `dataclass_wizard` itself (and its implicit dependencies)
plus the Python standard library. No import from this project.

    pip install dataclass-wizard==1.0.0

Note: every dataclass below is defined at MODULE level, not nested inside a
function. Some of the classes below have fields that reference other
module-level classes by name (a forward reference, resolved against the
module's globals); defining a class inside a function would break that
resolution with an unrelated `NameError`, obscuring the actual bug this
script is about.

THE BUG (general form)
=======================
This started as an investigation into a narrower-looking bug ("recursive
dataclasses fail"), but the real defect is broader and does NOT require
recursion/self-reference at all:

    A dataclass with a `CatchAll` field (used to capture unrecognized JSON
    keys) can only be successfully loaded/dumped by dataclass_wizard 1.0.0 in
    ONE distinct *structural context* per process. Structural context means:
    "used as the direct top-level target of `.from_dict()`/`.to_dict()`", or
    "used as a field of enclosing class X", or "used as a field of enclosing
    class Y" -- each of these is a different context. Whichever context is
    encountered FIRST works fine. Any SECOND, differently-shaped use of that
    SAME class -- even a completely ordinary one, unrelated to recursion --
    then fails, permanently, for the rest of the process, with:

        TypeError: issubclass() arg 1 must be a class

    bottoming out in dataclass_wizard's codegen (1.0.0):

        dataclass_wizard/_loaders.py:1014, in load_dispatcher_for_annotation
            if issubclass(origin, t):

This is NOT an obscure edge case. Section 5 below reproduces it with the
ordinary sequence "call service method A, then call service method B" against
two of this project's own production classes (`CgCodingamer`,
`CgCodingamePointsStats`) -- exactly the kind of thing any long-lived client
session does. A class with NO `CatchAll` field is entirely unaffected (see
section 1b): reuse across as many different contexts as you like just works,
as normal dataclass_wizard behavior would lead you to expect.

Self-referential ("recursive") dataclasses -- e.g. a tree node with a
`children: list[Self]` field -- are a special case of this same defect, not a
separate bug: resolving a self-referential class as a top-level target
inherently ALSO requires resolving it as a nested field (of itself, via the
forward reference) within the very same codegen pass. That's already two
conflicting structural contexts in one call, so it fails immediately, even as
the very first thing done with the class in the process (section 6) --
whereas a non-recursive class survives its first use in any single context
and only fails on a second, different one (sections 2-5).

CONSEQUENCE / WORKAROUND STATUS
=================================
The wrapper-class trick that fixes plain self-referential classes (route
`.from_dict()`/`.to_dict()` through a throwaway non-recursive wrapper so the
recursive class is only ever resolved as a nested field, never as a top-level
target) does NOT generalize to this broader bug -- wrapping is itself just
another structural context, and it collides with any other context that same
class is later used in (see section 5, which is exactly two different
"wrapper" contexts for the same inner class). No general fix/workaround has
been found yet. Practically, this means: within a single dataclass_wizard
1.0.0 process, a `CatchAll`-bearing class must be used in only ONE structural
role for its entire lifetime -- e.g. never call `.from_dict()` on it directly
AND rely on it being reachable as a nested field elsewhere. This is a live,
unresolved problem in the parent project as of this writing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dataclass_wizard import JSONWizard
from dataclass_wizard.models import CatchAll

# --- Section 1: a CatchAll-bearing class used in exactly ONE context (direct
#     top-level call) -- its only use ever. Works fine. ---

@dataclass
class DirectOnlyLeaf(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


# --- Section 1b: a class with NO CatchAll field, used in two DIFFERENT
#     contexts (direct, then nested) -- for comparison. Works fine both times:
#     this confirms CatchAll (not recursion, not "reuse" per se) is the
#     necessary ingredient. ---

@dataclass
class NoCatchAllLeaf(JSONWizard):
    name: str


@dataclass
class NoCatchAllWrapper(JSONWizard):
    value: NoCatchAllLeaf


# --- Section 2: a FRESH CatchAll-bearing class used in exactly ONE context
#     (nested inside an enclosing class) -- its only use ever. Works fine. ---

@dataclass
class NestedOnlyLeaf(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class NestedOnlyWrapper(JSONWizard):
    value: NestedOnlyLeaf


# --- Section 3: a FRESH class used directly first, then the SAME class used
#     nested afterward -- the second (nested) use fails. ---

@dataclass
class DirectThenNestedLeaf(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class DirectThenNestedWrapper(JSONWizard):
    value: DirectThenNestedLeaf


# --- Section 4: a FRESH class used nested first, then directly afterward --
#     the second (direct) use fails. (The mirror image of section 3: order
#     doesn't matter, only "first context wins".) ---

@dataclass
class NestedThenDirectLeaf(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class NestedThenDirectWrapper(JSONWizard):
    value: NestedThenDirectLeaf


# --- Section 5: a FRESH class nested inside TWO DIFFERENT enclosing classes
#     -- neither use is "top-level", proving this isn't about top-level vs.
#     nested at all, only about "first structural context vs. any other".
#     Named after this project's own production classes that hit this exact
#     scenario in the wild: CgCodingamer is nested once inside
#     CgCodingamePointsStats and, in a different service call, would be
#     reached directly (see module docstring). ---

@dataclass
class TwoContextLeaf(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class ContextWrapperA(JSONWizard):
    value: TwoContextLeaf


@dataclass
class ContextWrapperB(JSONWizard):
    other: TwoContextLeaf


# --- Section 6: a self-referential class with CatchAll -- fails on its very
#     FIRST use (as a direct top-level target), because that single call
#     already requires resolving the class in two conflicting contexts at
#     once (top-level entry, and nested-in-itself via the forward reference).
#     Contrast with sections 1-5, where the FIRST use of a class always
#     succeeds and only a later, different-context use fails. ---

@dataclass
class SelfRefNode(JSONWizard):
    name: str
    extra_data: CatchAll = field(default_factory=dict)
    children: list[SelfRefNode] = field(default_factory=list)


def run_section_1() -> None:
    leaf = DirectOnlyLeaf.from_dict({"name": "root", "unrecognized": "x"})
    print(f"    OK: {leaf}")


def run_section_1b() -> None:
    direct = NoCatchAllLeaf.from_dict({"name": "a"})
    print(f"    OK (direct): {direct}")
    wrapper = NoCatchAllWrapper.from_dict({"value": {"name": "b"}})
    print(f"    OK (nested, different context, no CatchAll involved): {wrapper}")


def run_section_2() -> None:
    wrapper = NestedOnlyWrapper.from_dict({"value": {"name": "root", "unrecognized": "x"}})
    print(f"    OK: {wrapper}")


def run_section_3() -> None:
    leaf = DirectThenNestedLeaf.from_dict({"name": "a", "unrecognized": "x"})
    print(f"    OK (direct, first use): {leaf}")
    try:
        wrapper = DirectThenNestedWrapper.from_dict({"value": {"name": "b", "unrecognized": "y"}})
        print(f"    UNEXPECTED SUCCESS (nested, second use): {wrapper}")
    except TypeError as e:
        print(f"    FAILED as expected (nested, second/different context): {e}")


def run_section_4() -> None:
    wrapper = NestedThenDirectWrapper.from_dict({"value": {"name": "a", "unrecognized": "x"}})
    print(f"    OK (nested, first use): {wrapper}")
    try:
        leaf = NestedThenDirectLeaf.from_dict({"name": "b", "unrecognized": "y"})
        print(f"    UNEXPECTED SUCCESS (direct, second use): {leaf}")
    except TypeError as e:
        print(f"    FAILED as expected (direct, second/different context): {e}")


def run_section_5() -> None:
    wa = ContextWrapperA.from_dict({"value": {"name": "a", "unrecognized": "x"}})
    print(f"    OK (nested in ContextWrapperA, first use): {wa}")
    try:
        wb = ContextWrapperB.from_dict({"other": {"name": "b", "unrecognized": "y"}})
        print(f"    UNEXPECTED SUCCESS (nested in ContextWrapperB, second use): {wb}")
    except TypeError as e:
        print(f"    FAILED as expected (nested in a DIFFERENT enclosing class): {e}")


def run_section_6() -> None:
    try:
        node = SelfRefNode.from_dict({"name": "root", "children": [{"name": "child", "children": []}]})
        print(f"    UNEXPECTED SUCCESS: {node}")
    except TypeError as e:
        print(f"    FAILED on the very FIRST use (unlike sections 2-5): {e}")


if __name__ == "__main__":
    print("1. CatchAll-bearing class used in exactly one context (direct) -- expect OK:")
    run_section_1()

    print("\n1b. Class with NO CatchAll, used direct then nested -- expect OK both times:")
    run_section_1b()

    print("\n2. Fresh CatchAll-bearing class used in exactly one context (nested) -- expect OK:")
    run_section_2()

    print("\n3. Fresh class: direct first (OK), then nested (expect FAILURE):")
    run_section_3()

    print("\n4. Fresh class: nested first (OK), then direct (expect FAILURE):")
    run_section_4()

    print("\n5. Fresh class nested in two DIFFERENT enclosing classes (expect FAILURE on the second):")
    run_section_5()

    print("\n6. Self-referential class with CatchAll -- fails immediately, even alone (expect FAILURE):")
    run_section_6()
