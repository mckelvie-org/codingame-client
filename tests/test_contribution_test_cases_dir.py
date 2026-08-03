"""Unit tests for codingame_tools.contribution_manager.test_cases_dir: the tests/ directory
   import/commit algorithm (local/validator pairing, ordinal directories, title-collision
   handling, natural sort, renormalization).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

from codingame_tools.client.common.protocol.contribution import CgTestCase
from codingame_tools.contribution_manager.test_cases_dir import (
    LOCAL_SUBDIR_NAME,
    TEST_META_FILE_NAME,
    VALIDATOR_SUBDIR_NAME,
    CgTestCaseFileMeta,
    commit_test_cases,
    ensure_trailing_newline,
    import_test_cases,
    list_local_test_cases,
    normalize_test_title,
    renormalize_test_case_dirs,
)


def _tc(title: str, test_in: str, test_out: str, *, is_test: bool, is_validator: bool) -> CgTestCase:
    return CgTestCase(
            title=title, test_in=test_in, test_out=test_out,
            is_test=is_test, is_validator=is_validator, need_validation=True,
        )


def _local(title: str, i: str = "in", o: str = "out") -> CgTestCase:
    return _tc(title, i, o, is_test=True, is_validator=False)


def _validator(title: str, i: str = "in", o: str = "out") -> CgTestCase:
    return _tc(title, i, o, is_test=False, is_validator=True)


# --- normalize_test_title -------------------------------------------------------------------


def test_normalize_test_title_replaces_punctuation_and_spaces() -> None:
    assert normalize_test_title("Large grid test case!") == "Large-grid-test-case"


def test_normalize_test_title_collapses_runs_and_strips_edges() -> None:
    assert normalize_test_title("  Foo   Bar--Baz!! ") == "Foo-Bar-Baz"


def test_normalize_test_title_falls_back_when_nothing_alphanumeric_remains() -> None:
    assert normalize_test_title("!!!") == "test"


# --- import_test_cases: well-paired case --------------------------------------------------


def test_import_well_paired_same_title_collapses_into_one_dir(tmp_path: Path) -> None:
    test_cases = [_local("Case A", "1", "2"), _validator("Case A", "3", "4")]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)

    ordinal_dir = tests_dir / "01"
    assert ordinal_dir.is_dir()
    named_dirs = list(ordinal_dir.iterdir())
    assert len(named_dirs) == 1
    named_dir = named_dirs[0]
    assert named_dir.name == "Case-A"
    meta = CgTestCaseFileMeta.load(named_dir / TEST_META_FILE_NAME)
    assert meta.title == "Case A"
    assert (named_dir / LOCAL_SUBDIR_NAME / "input.txt").read_text() == "1\n"
    assert (named_dir / LOCAL_SUBDIR_NAME / "output.txt").read_text() == "2\n"
    assert (named_dir / VALIDATOR_SUBDIR_NAME / "input.txt").read_text() == "3\n"
    assert (named_dir / VALIDATOR_SUBDIR_NAME / "output.txt").read_text() == "4\n"


def test_import_appends_trailing_newline_only_when_missing(tmp_path: Path) -> None:
    test_cases = [_local("Case A", "already-has-nl\n", "no-nl")]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)
    named_dir = tests_dir / "01" / "Case-A"
    assert (named_dir / LOCAL_SUBDIR_NAME / "input.txt").read_text() == "already-has-nl\n"
    assert (named_dir / LOCAL_SUBDIR_NAME / "output.txt").read_text() == "no-nl\n"


# --- import_test_cases: differing titles ----------------------------------------------------


def test_import_differing_titles_creates_two_dirs(tmp_path: Path) -> None:
    test_cases = [_local("Local title"), _validator("Validator title")]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)
    ordinal_dir = tests_dir / "01"
    names = sorted(d.name for d in ordinal_dir.iterdir())
    assert names == ["Local-title", "Validator-title"]
    assert (ordinal_dir / "Local-title" / LOCAL_SUBDIR_NAME).is_dir()
    assert not (ordinal_dir / "Local-title" / VALIDATOR_SUBDIR_NAME).is_dir()
    assert (ordinal_dir / "Validator-title" / VALIDATOR_SUBDIR_NAME).is_dir()
    assert not (ordinal_dir / "Validator-title" / LOCAL_SUBDIR_NAME).is_dir()


def test_import_slug_collision_with_differing_titles_auto_suffixes(tmp_path: Path) -> None:
    """"Case A" and "Case A!" normalize to the same slug but are different titles--must not
       collapse (that's reserved for exact title matches)."""
    test_cases = [_local("Case A"), _validator("Case A!")]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)
    ordinal_dir = tests_dir / "01"
    names = sorted(d.name for d in ordinal_dir.iterdir())
    assert names == ["Case-A", "Case-A-2"]
    local_meta = CgTestCaseFileMeta.load(ordinal_dir / "Case-A" / TEST_META_FILE_NAME)
    validator_meta = CgTestCaseFileMeta.load(ordinal_dir / "Case-A-2" / TEST_META_FILE_NAME)
    assert local_meta.title == "Case A"
    assert validator_meta.title == "Case A!"


# --- import_test_cases: unbalanced counts / one-sided ordinals -----------------------------


def test_import_unbalanced_counts_leaves_trailing_ordinals_one_sided(tmp_path: Path) -> None:
    test_cases = [
            _local("L1"), _validator("V1"),
            _local("L2"), _validator("V2"),
            _local("L3"),
        ]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)
    assert (tests_dir / "03" / "L3" / LOCAL_SUBDIR_NAME).is_dir()
    assert not (tests_dir / "03" / "L3" / VALIDATOR_SUBDIR_NAME).is_dir()
    assert len(list((tests_dir / "03").iterdir())) == 1


def test_import_preserves_each_sides_relative_order_despite_interleaving(tmp_path: Path) -> None:
    """All locals first, then all validators (a real deviation from the "pairs" convention)--
       position-based pairing must still work, independent of interleaving."""
    test_cases = [
            _local("L1"), _local("L2"), _local("L3"),
            _validator("V1"), _validator("V2"), _validator("V3"),
        ]
    tests_dir = tmp_path / "tests"
    import_test_cases(test_cases, tests_dir)
    for i, (lt, vt) in enumerate([("L1", "V1"), ("L2", "V2"), ("L3", "V3")], start=1):
        ordinal_dir = tests_dir / str(i).zfill(2)
        assert (ordinal_dir / lt / LOCAL_SUBDIR_NAME).is_dir()
        assert (ordinal_dir / vt / VALIDATOR_SUBDIR_NAME).is_dir()


def test_import_clears_prior_content(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "stale-file.txt").write_text("stale")
    import_test_cases([_local("New")], tests_dir)
    assert not (tests_dir / "stale-file.txt").exists()
    assert (tests_dir / "01" / "New").is_dir()


def test_import_empty_list_produces_no_tests_dir_content(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    import_test_cases([], tests_dir)
    assert not tests_dir.is_dir()


# --- commit_test_cases: round trip ----------------------------------------------------------


def test_commit_round_trips_well_paired_case(tmp_path: Path) -> None:
    original = [_local("Case A", "1\n", "2\n"), _validator("Case A", "3\n", "4\n")]
    tests_dir = tmp_path / "tests"
    import_test_cases(original, tests_dir)
    committed = commit_test_cases(tests_dir)
    assert committed == original


def test_commit_round_trips_differing_titles_in_ordinal_order(tmp_path: Path) -> None:
    original = [
            _local("L1", "1\n", "2\n"), _validator("V1", "3\n", "4\n"),
            _local("L2", "5\n", "6\n"), _validator("V2", "7\n", "8\n"),
        ]
    tests_dir = tmp_path / "tests"
    import_test_cases(original, tests_dir)
    committed = commit_test_cases(tests_dir)
    assert committed == original


def test_commit_emits_local_then_validator_per_ordinal_even_if_only_one_side(tmp_path: Path) -> None:
    original = [_local("L1"), _local("L2"), _validator("V1")]
    tests_dir = tmp_path / "tests"
    import_test_cases(original, tests_dir)
    committed = commit_test_cases(tests_dir)
    # Ordinal 1: L1 + V1 (paired by position); ordinal 2: L2 only.
    assert [tc.title for tc in committed] == ["L1", "V1", "L2"]


def test_commit_falls_back_to_dir_name_when_test_json_missing(tmp_path: Path) -> None:
    """A manually-created test directory (no test.json) should still commit, using the directory
       name itself (dashes turned back into spaces) as a reasonable title guess."""
    tests_dir = tmp_path / "tests"
    named_dir = tests_dir / "01" / "Problem-statement-example"
    (named_dir / LOCAL_SUBDIR_NAME).mkdir(parents=True)
    (named_dir / LOCAL_SUBDIR_NAME / "input.txt").write_text("in\n")
    (named_dir / LOCAL_SUBDIR_NAME / "output.txt").write_text("out\n")
    assert not (named_dir / TEST_META_FILE_NAME).exists()

    committed = commit_test_cases(tests_dir)

    assert len(committed) == 1
    assert committed[0].title == "Problem statement example"


def test_commit_missing_tests_dir_returns_empty_list(tmp_path: Path) -> None:
    assert commit_test_cases(tmp_path / "does-not-exist") == []


def test_commit_is_agnostic_to_ordinal_naming_convention(tmp_path: Path) -> None:
    """A user-renamed/inserted ordinal dir (e.g. "05a") must still sort correctly via natural
       sort, without requiring the clean zero-padded convention import_test_cases writes."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name, title in [("1", "First"), ("2a", "Inserted"), ("10", "Tenth")]:
        d = tests_dir / name / normalize_test_title(title)
        d.mkdir(parents=True)
        CgTestCaseFileMeta(title=title).save(d / TEST_META_FILE_NAME)
        (d / LOCAL_SUBDIR_NAME).mkdir()
        (d / LOCAL_SUBDIR_NAME / "input.txt").write_text("in\n")
        (d / LOCAL_SUBDIR_NAME / "output.txt").write_text("out\n")
    committed = commit_test_cases(tests_dir)
    assert [tc.title for tc in committed] == ["First", "Inserted", "Tenth"]


# --- renormalize_test_case_dirs --------------------------------------------------------------


def test_renormalize_rewrites_to_clean_zero_padded_sequence(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name, title in [("1", "First"), ("2a", "Inserted"), ("10", "Tenth")]:
        d = tests_dir / name / normalize_test_title(title)
        d.mkdir(parents=True)
        CgTestCaseFileMeta(title=title).save(d / TEST_META_FILE_NAME)
        (d / LOCAL_SUBDIR_NAME).mkdir()
        (d / LOCAL_SUBDIR_NAME / "input.txt").write_text("in\n")
        (d / LOCAL_SUBDIR_NAME / "output.txt").write_text("out\n")

    renormalize_test_case_dirs(tests_dir)

    names = sorted(d.name for d in tests_dir.iterdir())
    assert names == ["01", "02", "03"]
    # Order preserved.
    assert CgTestCaseFileMeta.load(tests_dir / "01" / "First" / TEST_META_FILE_NAME).title == "First"
    assert CgTestCaseFileMeta.load(tests_dir / "02" / "Inserted" / TEST_META_FILE_NAME).title == "Inserted"
    assert CgTestCaseFileMeta.load(tests_dir / "03" / "Tenth" / TEST_META_FILE_NAME).title == "Tenth"


def test_renormalize_noop_on_missing_or_empty_dir(tmp_path: Path) -> None:
    renormalize_test_case_dirs(tmp_path / "does-not-exist")  # must not raise
    empty = tmp_path / "empty-tests"
    empty.mkdir()
    renormalize_test_case_dirs(empty)  # must not raise
    assert list(empty.iterdir()) == []


# --- list_local_test_cases ---------------------------------------------------------------------


def test_list_local_missing_tests_dir_returns_empty_list(tmp_path: Path) -> None:
    assert list_local_test_cases(tmp_path / "does-not-exist") == []


def test_list_local_returns_one_entry_per_side(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    local_tc = _tc("Case A", "in-local\n", "out-local\n", is_test=True, is_validator=False)
    validator_tc = _tc("Case A", "in-validator\n", "out-validator\n", is_test=False, is_validator=True)
    import_test_cases([local_tc, validator_tc], tests_dir)

    entries = list_local_test_cases(tests_dir)

    assert [(e.ordinal, e.side) for e in entries] == [("01", "local"), ("01", "validator")]
    assert entries[0].title == "Case A"
    assert entries[0].input_text == "in-local\n"
    assert entries[0].output_text == "out-local\n"
    assert entries[0].input_file.is_file()
    assert entries[1].input_text == "in-validator\n"


def test_list_local_omits_missing_side(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    local_only = _tc("Local only", "in\n", "out\n", is_test=True, is_validator=False)
    import_test_cases([local_only], tests_dir)

    entries = list_local_test_cases(tests_dir)

    assert len(entries) == 1
    assert entries[0].side == "local"


def test_list_local_output_file_can_be_overwritten_and_reread(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    local_tc = _tc("Case A", "in\n", "stale\n", is_test=True, is_validator=False)
    import_test_cases([local_tc], tests_dir)
    entries = list_local_test_cases(tests_dir)

    entries[0].output_file.write_text("fresh\n", encoding="utf-8")

    reread = list_local_test_cases(tests_dir)
    assert reread[0].output_text == "fresh\n"


def test_list_local_natural_sorts_ordinals(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name, title in [("1", "First"), ("2a", "Inserted"), ("10", "Tenth")]:
        d = tests_dir / name / normalize_test_title(title)
        d.mkdir(parents=True)
        CgTestCaseFileMeta(title=title).save(d / TEST_META_FILE_NAME)
        (d / LOCAL_SUBDIR_NAME).mkdir()
        (d / LOCAL_SUBDIR_NAME / "input.txt").write_text("in\n")
        (d / LOCAL_SUBDIR_NAME / "output.txt").write_text("out\n")

    entries = list_local_test_cases(tests_dir)

    assert [e.title for e in entries] == ["First", "Inserted", "Tenth"]


def test_ensure_trailing_newline_leaves_empty_text_empty() -> None:
    """A file is a list of lines, correctly expanded as `"\\n".join(lines) + ("\\n" if lines else
       "")`: no lines is a zero-length file, one empty line is `"\\n"`, and those are different
       files. Beyond being right in its own terms, this is what makes "no reference solution"
       representable--`contribution_manager.manager` spells it as a zero-length `solution.src`,
       which would be impossible if every write produced at least a newline."""
    assert ensure_trailing_newline("") == ""
    assert ensure_trailing_newline("\n") == "\n"
    assert ensure_trailing_newline("abc") == "abc\n"
    assert ensure_trailing_newline("abc\n") == "abc\n"


def test_an_empty_test_input_round_trips_as_a_zero_length_file(tmp_path: Path) -> None:
    """An empty test input is written as an empty file, not a stray newline, and reads back
       unchanged. (What reaches the server was already correct either way--
       `CgContributionServiceHelper.update_contribution` strips one trailing newline via
       `strip_test_final_eols`--so this is about the file on disk being honest.)"""
    import_test_cases([
            CgTestCase(title="Empty input", test_in="", test_out="ok",
                       is_test=True, is_validator=False, need_validation=True),
        ], tmp_path)

    input_file = next(tmp_path.rglob("input.txt"))
    assert input_file.read_bytes() == b""

    (committed,) = commit_test_cases(tmp_path)
    assert committed.test_in == ""
    assert committed.test_out == "ok\n"
