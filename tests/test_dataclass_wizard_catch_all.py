"""Catch-all behaviour of `JSONWizardX`: unknown server fields must survive, in every context.

This is the property the whole client's tolerance for an undocumented, changing API rests on. If
CodinGame adds a field, `extra_data` captures it and the load succeeds; without that, every addition
upstream is a hard failure for every user until a release goes out.

`common/dataclass_wizard_x.py` currently carries a workaround for a dataclass_wizard 1.0.0 bug that
breaks exactly this (see that module's docstring). **These tests deliberately describe the
behaviour, not the workaround** -- so when upstream ships a fix and the workaround is deleted, this
file should keep passing untouched. That is precisely what tells you the fix really landed.

The shape that matters is a class loaded in *two different structural contexts*: once nested inside
another dataclass, once at the top level. One context alone passes even with the bug, which is why
it went unnoticed until real responses started losing fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from codingame_tools.common.dataclass_wizard_x import CatchAll, JSONWizardX


@dataclass
class Inner(JSONWizardX):
    name: str
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class Outer(JSONWizardX):
    inner: Inner
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class Wrapper(JSONWizardX):
    """A third context for `Inner`, to catch a fix that only ever survives two passes."""

    # `extra_data` first among the defaulted fields, per the convention every schema class here
    # follows: dataclass_wizard 1.0.0 silently mis-binds whichever defaulted field sits immediately
    # before the CatchAll. Reorder these two and this class fails to construct at all.
    extra_data: CatchAll = field(default_factory=dict)
    items: list[Inner] = field(default_factory=list)


def test_unknown_fields_are_captured_at_the_top_level() -> None:
    loaded = Inner.from_dict({"name": "a", "surprise": 1})

    assert loaded.name == "a"
    assert loaded.extra_data == {"surprise": 1}


def test_unknown_fields_are_captured_when_nested() -> None:
    """The regression. Loading `Inner` at the top level first is what primes -- and, with the
       upstream bug, corrupts -- the per-class state that this load then depends on."""
    Inner.from_dict({"name": "a", "surprise": 1})

    loaded = Outer.from_dict({"inner": {"name": "b", "surprise": 2}, "other": 3})

    assert loaded.inner.extra_data == {"surprise": 2}
    assert loaded.extra_data == {"other": 3}


def test_unknown_fields_survive_in_a_third_context() -> None:
    Inner.from_dict({"name": "a", "surprise": 1})
    Outer.from_dict({"inner": {"name": "b", "surprise": 2}})

    loaded = Wrapper.from_dict({"items": [{"name": "c", "surprise": 3}]})

    assert loaded.items[0].extra_data == {"surprise": 3}


@pytest.mark.parametrize("order", ["nested-first", "top-level-first"])
def test_capture_is_independent_of_load_order(order: str) -> None:
    """Whichever context happens to be exercised first, both must work. The bug is order-sensitive,
       so a test that only ever runs them one way round can pass by luck."""
    if order == "nested-first":
        nested = Outer.from_dict({"inner": {"name": "b", "surprise": 2}})
        top = Inner.from_dict({"name": "a", "surprise": 1})
    else:
        top = Inner.from_dict({"name": "a", "surprise": 1})
        nested = Outer.from_dict({"inner": {"name": "b", "surprise": 2}})

    assert top.extra_data == {"surprise": 1}
    assert nested.inner.extra_data == {"surprise": 2}


def test_unknown_fields_are_written_back_out() -> None:
    """Capturing isn't enough: a field we don't understand has to be returned to the server
       unchanged, or a round trip silently deletes data from the user's contribution."""
    loaded = Outer.from_dict({"inner": {"name": "b", "surprise": 2}, "other": 3})

    assert loaded.to_dict() == {"inner": {"name": "b", "surprise": 2}, "other": 3}


def test_no_unknown_fields_leaves_extra_data_empty() -> None:
    assert Inner.from_dict({"name": "a"}).extra_data == {}
    assert Outer.from_dict({"inner": {"name": "b"}}).to_dict() == {"inner": {"name": "b"}}
