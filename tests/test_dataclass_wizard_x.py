"""Unit tests for codingame_client.common.dataclass_wizard_x, focused on the YAML support
   (from_yaml/load_yaml/to_yaml/save_yaml) added on top of JSONWizardX's existing JSON support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from codingame_client.common.dataclass_wizard_x import DEFAULT_YAML_DECODER, CatchAll, JSONWizardX


@dataclass
class _Widget(JSONWizardX):
    name: str
    extra_data: CatchAll = field(default_factory=dict)
    nested_value: int | None = None


@dataclass
class _AllOptional(JSONWizardX):
    """Every field defaulted, unlike _Widget--needed to exercise a comment-only YAML document,
       since an unset required field would fail to parse for an unrelated reason."""
    extra_data: CatchAll = field(default_factory=dict)
    value: int | None = None


def test_to_yaml_uses_camel_case_by_default() -> None:
    widget = _Widget(name="hi", nested_value=42)
    text = widget.to_yaml()
    assert "nestedValue: 42" in text
    assert "name: hi" in text


def test_from_yaml_to_yaml_round_trip() -> None:
    original = _Widget(name="hi", nested_value=42)
    restored = _Widget.from_yaml(original.to_yaml())
    assert restored == original


def test_from_yaml_preserves_unknown_fields_via_catch_all() -> None:
    restored = _Widget.from_yaml("name: hi\nfutureField: 42\n")
    assert restored.name == "hi"
    assert restored.extra_data == {"futureField": 42}


def test_yaml_decoder_rejects_unexpected_kwargs() -> None:
    with pytest.raises(TypeError, match="does not accept extra keyword arguments"):
        _Widget.loads("name: hi", decoder=DEFAULT_YAML_DECODER, extra_kwarg=1)


def test_save_yaml_load_yaml_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "widget.yaml"
    original = _Widget(name="hi", nested_value=42)
    original.save_yaml(path)
    assert path.read_text().endswith("\n")

    restored = _Widget.load_yaml(path)
    assert restored == original


def test_yaml_decoder_treats_empty_document_as_empty_mapping() -> None:
    assert DEFAULT_YAML_DECODER("") == {}
    assert DEFAULT_YAML_DECODER("# just a comment\n") == {}


def test_from_yaml_comment_only_document_parses_as_all_defaults() -> None:
    """Regression test: a comment-only YAML file (e.g. all real fields commented out as
       documentation examples) must parse as an empty mapping, not fail with "not a dict"."""
    restored = _AllOptional.from_yaml("# value: 42\n")
    assert restored == _AllOptional()


def test_to_dict_omits_unset_fields_by_default() -> None:
    """Regression test for a JSONWizardX bug where Meta.skip_defaults was silently ignored
       because skip_defaults=None was always forwarded explicitly to dataclass_wizard, which
       only consults Meta.skip_defaults when the keyword is omitted from the call entirely."""
    assert _AllOptional().to_dict() == {}
    assert _AllOptional(value=42).to_dict() == {"value": 42}
