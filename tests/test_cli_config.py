"""Unit tests for codingame_tools.cli.main's config-related helpers.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from codingame_tools.cli.main import default_config_template
from codingame_tools.config import CgConfigData


def test_default_config_template_parses_as_all_defaults() -> None:
    """Regression/drift-detection test: default_config_template() is hand-written (so it can
       carry comments--plain YAML dumping can't emit those), not generated from CgConfigData. If
       a field is added, renamed, or its default changes, this will fail until the template is
       updated to match--keeping the two in sync deliberately rather than silently drifting
       apart. The actual placeholder value passed in doesn't matter for this check--it only
       affects the commented-out example value, not what the file parses back as."""
    template = default_config_template("/placeholder/data")
    assert CgConfigData.from_yaml(template) == CgConfigData()


def test_default_config_template_shows_the_actual_default_passed_in() -> None:
    """The commented-out example must reflect whatever the caller decided was appropriate for
       this specific invocation (project-local "../data" vs. the global per-user absolute path),
       not a fixed, potentially-wrong-for-one-of-the-two-cases description."""
    template = default_config_template("/some/global/data/dir")
    assert "/some/global/data/dir" in template


def test_default_config_template_shows_relative_project_local_example() -> None:
    """The project-local case must show the literal "../data" example, not an absolute path--an
       absolute path baked into a freshly-created config.yaml would silently stop matching the
       default the moment the project directory is renamed or moved."""
    template = default_config_template("../data")
    assert "../data" in template
    assert CgConfigData.from_yaml(template) == CgConfigData()
