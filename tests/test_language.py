"""Tests for `codingame_tools.language`: discovery/registry behavior, the `Python3` concrete
   implementation (including streaming execution), and the 26 extension-only language plugins.

Pure/local--no network--so it runs under the default `pdm run test` invocation. Spawns real
`sys.executable` subprocesses (via Python3's `run`/`run_streaming`), same as
`test_test_runner_runner.py` used to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codingame_tools.language import (
    CgDefaultLanguage,
    CgLanguageOperationNotSupportedError,
    CgRunFinished,
    CgRunOutputChunk,
    get_language,
    get_language_by_extension,
    list_language_cg_ids,
)

# The exact 27 solution-language ID strings returned live by ProgrammingLanguage/findAllIds.
LIVE_LANGUAGE_IDS = [
        "Bash", "C", "C#", "C++", "Clojure", "D", "Dart", "F#", "Go", "Groovy", "Haskell", "Java",
        "Javascript", "Kotlin", "Lua", "ObjectiveC", "OCaml", "Pascal", "Perl", "PHP", "Python3",
        "Ruby", "Rust", "Scala", "Swift", "TypeScript", "VB.NET",
    ]


def _write_solution(tmp_path: Path, source: str) -> Path:
    solution_file = tmp_path / "solution.src"
    solution_file.write_text(source)
    return solution_file


# --- discovery / registry --------------------------------------------------------------------


def test_python3_is_an_identity_stable_singleton() -> None:
    first = get_language("Python3")
    second = get_language("Python3")
    assert first is second


def test_extension_only_languages_resolve_to_their_own_real_class_not_the_catchall() -> None:
    for cg_id, extension in [("C++", "cpp"), ("Java", "java"), ("Rust", "rs")]:
        language = get_language(cg_id)
        assert not isinstance(language, CgDefaultLanguage)
        assert language.cg_id == cg_id
        assert language.extension == extension


def test_extension_only_language_has_no_run_support() -> None:
    language = get_language("C++")
    with pytest.raises(CgLanguageOperationNotSupportedError):
        language.run_streaming(Path("x.cpp"), "")


async def test_extension_only_language_run_raises() -> None:
    language = get_language("Java")
    with pytest.raises(CgLanguageOperationNotSupportedError):
        await language.run(Path("x.java"), "")


async def test_extension_only_language_has_no_stub() -> None:
    assert await get_language("Rust").build_contribution_create_stub_source() is None


def test_unknown_language_falls_back_to_catchall_and_is_identity_stable() -> None:
    first = get_language("TotallyUnknownLang")
    second = get_language("TotallyUnknownLang")
    assert isinstance(first, CgDefaultLanguage)
    assert first.cg_id == "TotallyUnknownLang"
    assert first.extension is None
    assert first is second


def test_get_language_by_extension_resolves_python3() -> None:
    python3 = get_language("Python3")
    assert get_language_by_extension("py") is python3
    assert get_language_by_extension(".PY") is python3
    assert get_language_by_extension("solution.py") is python3


def test_get_language_by_extension_resolves_extension_only_entry() -> None:
    assert get_language_by_extension("cpp") is get_language("C++")


def test_get_language_by_extension_unknown_returns_none() -> None:
    assert get_language_by_extension("totallyunknownext") is None


def test_format_comment() -> None:
    assert get_language("Python3").format_comment("some text") == "# some text"
    assert get_language("Rust").format_comment("some text") is None


def test_list_language_cg_ids_contains_every_discovered_language() -> None:
    cg_ids = list_language_cg_ids()
    assert set(cg_ids) == set(LIVE_LANGUAGE_IDS)
    assert cg_ids == tuple(sorted(cg_ids))


def test_every_live_language_id_maps_to_an_extension() -> None:
    for language_id in LIVE_LANGUAGE_IDS:
        extension = get_language(language_id).extension
        assert extension is not None, f"{language_id!r} has no extension mapping"


def test_extension_round_trips_back_to_the_same_language_id() -> None:
    for language_id in LIVE_LANGUAGE_IDS:
        extension = get_language(language_id).extension
        assert extension is not None
        resolved = get_language_by_extension(extension)
        assert resolved is not None
        assert resolved.cg_id == language_id


def test_previously_buggy_mappings_now_match_the_real_ids() -> None:
    """These three didn't match any real language ID before being fixed ("DMD", "Objective-C",
       "JavaScript")--extension lookup silently failed for the real IDs."""
    assert get_language("D").extension == "d"
    assert get_language("ObjectiveC").extension == "m"
    assert get_language("Javascript").extension == "js"
    assert get_language("DMD").extension is None
    assert get_language("Objective-C").extension is None
    assert get_language("JavaScript").extension is None


# --- Python3: run / run_streaming -------------------------------------------------------------


async def test_run_echoes_input_to_output(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "n = int(input())\nprint(n * 2)\n")

    result = await get_language("Python3").run(solution_file, "21\n")

    assert result.output == "42\n"
    assert result.returncode == 0
    assert not result.timed_out


async def test_run_captures_stderr_without_failing(tmp_path: Path) -> None:
    solution_file = _write_solution(
            tmp_path, "import sys\nprint('debug', file=sys.stderr)\nprint('ok')\n")

    result = await get_language("Python3").run(solution_file, "")

    assert result.output == "ok\n"
    assert "debug" in result.stderr
    assert result.returncode == 0


async def test_run_reports_nonzero_returncode_on_uncaught_exception(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "raise ValueError('boom')\n")

    result = await get_language("Python3").run(solution_file, "")

    assert result.returncode != 0
    assert "ValueError" in result.stderr


async def test_run_times_out_on_infinite_loop(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "while True:\n    pass\n")

    result = await get_language("Python3").run(solution_file, "", timeout=0.5)

    assert result.timed_out
    assert result.returncode == -1


async def test_build_contribution_create_stub_source() -> None:
    assert await get_language("Python3").build_contribution_create_stub_source() == "n = input()\nprint(n)\n"


async def test_run_streaming_final_event_matches_run(tmp_path: Path) -> None:
    solution_file = _write_solution(tmp_path, "n = int(input())\nprint(n * 2)\n")
    language = get_language("Python3")

    events = [event async for event in language.run_streaming(solution_file, "21\n")]
    finished = events[-1]
    assert isinstance(finished, CgRunFinished)

    expected = await language.run(solution_file, "21\n")
    assert finished.result == expected


async def test_run_streaming_tags_chunks_by_stream(tmp_path: Path) -> None:
    solution_file = _write_solution(
            tmp_path, "import sys\nprint('out-line')\nprint('err-line', file=sys.stderr)\n")

    events = [event async for event in get_language("Python3").run_streaming(solution_file, "")]
    chunks = [e for e in events if isinstance(e, CgRunOutputChunk)]

    assert any(c.stream == "stdout" and "out-line" in c.text for c in chunks)
    assert any(c.stream == "stderr" and "err-line" in c.text for c in chunks)


async def test_run_streaming_yields_output_progressively_before_completion(tmp_path: Path) -> None:
    """A real progressive-streaming assertion, not just an end-state check: the solution prints,
       reads more stdin, then prints again--confirm the first chunk arrives as a distinct event
       strictly before the run finishes producing the second."""
    solution_file = _write_solution(
            tmp_path, "print('first')\ninput()\nprint('second')\n")

    events = []
    async for event in get_language("Python3").run_streaming(solution_file, "go\n"):
        events.append(event)
        if isinstance(event, CgRunOutputChunk) and "first" in event.text:
            break  # got the first chunk before the generator was fully drained/finished

    assert events
    assert isinstance(events[-1], CgRunOutputChunk)
    assert "first" in events[-1].text
