"""Unit tests for codingame_tools.cli.main's config-related helpers.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

from codingame_tools.cli.main import default_config_template
from codingame_tools.config import CgConfigData


def test_default_config_template_parses_as_all_defaults() -> None:
    """Regression/drift-detection test: default_config_template() is hand-written (so it can
       carry comments--plain YAML dumping can't emit those), not generated from CgConfigData. If
       a field is added, renamed, or its default changes, this will fail until the template is
       updated to match--keeping the two in sync deliberately rather than silently drifting
       apart. The actual placeholder path passed in doesn't matter for this check--it only
       affects the commented-out example value, not what the file parses back as."""
    template = default_config_template(Path("/placeholder/data"))
    assert CgConfigData.from_yaml(template) == CgConfigData()


def test_default_config_template_shows_the_actual_default_passed_in() -> None:
    """The commented-out example must reflect the real resolved default for this specific
       invocation (project-local sibling dir vs. the global per-user location), not a fixed,
       potentially-wrong-for-one-of-the-two-cases description."""
    template = default_config_template(Path("/some/global/data/dir"))
    assert "/some/global/data/dir" in template
