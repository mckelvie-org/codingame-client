"""Regression test for codingame_client.client.common.protocol.schema's solution-language <->
   file-extension mapping, against the real set of language IDs confirmed live (2026-07-28) via
   `ProgrammingLanguage/findAllIds`.

Pure/local--no network--so it runs under the default `pdm run test` invocation.
"""

from __future__ import annotations

from codingame_client.client.common.protocol.schema import (
    cg_extension_to_solution_language,
    cg_solution_language_to_extension,
)

# The exact 27 solution-language ID strings returned live by ProgrammingLanguage/findAllIds.
LIVE_LANGUAGE_IDS = [
        "Bash", "C", "C#", "C++", "Clojure", "D", "Dart", "F#", "Go", "Groovy", "Haskell", "Java",
        "Javascript", "Kotlin", "Lua", "ObjectiveC", "OCaml", "Pascal", "Perl", "PHP", "Python3",
        "Ruby", "Rust", "Scala", "Swift", "TypeScript", "VB.NET",
    ]


def test_every_live_language_id_maps_to_an_extension() -> None:
    for language in LIVE_LANGUAGE_IDS:
        extension = cg_solution_language_to_extension(language)
        assert extension is not None, f"{language!r} has no extension mapping"


def test_extension_round_trips_back_to_the_same_language_id() -> None:
    for language in LIVE_LANGUAGE_IDS:
        extension = cg_solution_language_to_extension(language)
        assert extension is not None
        assert cg_extension_to_solution_language(extension) == language


def test_previously_buggy_mappings_now_match_the_real_ids() -> None:
    """These three didn't match any real language ID before being fixed ("DMD", "Objective-C",
       "JavaScript")--`cg_solution_language_to_extension` silently returned None for the real IDs."""
    assert cg_solution_language_to_extension("D") == "d"
    assert cg_solution_language_to_extension("ObjectiveC") == "m"
    assert cg_solution_language_to_extension("Javascript") == "js"
    assert cg_solution_language_to_extension("DMD") is None
    assert cg_solution_language_to_extension("Objective-C") is None
    assert cg_solution_language_to_extension("JavaScript") is None
