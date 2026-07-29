"""Reads/writes the `tests/` subdirectory of a contribution working directory, converting between
   it and the flat `list[CgTestCase]` used by the CodinGame API.

   The API just presents a flat list of individual test cases, distinguished only by
   `is_test`/`is_validator`. The CodinGame web app (and, informally, this contribution's own
   `findContribution` responses observed so far) presents them as local/validator *pairs*--but
   nothing in the API schema enforces that convention, titles are independent and not
   guaranteed-unique even within a well-paired contribution, and only each side's own relative
   order (not the interleaving) is actually meaningful.

   To make editing easy while surviving all of that, tests are stored as:

       tests/
           <ordinal>/
               <normalized-title>/
                   test.json          # {"title": "<the real, unnormalized title>"}
                   local/
                       input.txt
                       output.txt
                   validator/
                       input.txt
                       output.txt

   `<ordinal>` is a sort key, not a guaranteed-stable index--see `import_test_cases` (always
   writes clean zero-padded numbers) and `commit_test_cases` (agnostic to naming convention, via
   natural sort, so a user is free to rename/insert directories, e.g. "05a"). Within one ordinal,
   the local and validator test are co-located under one `<normalized-title>/` directory if (and
   only if) they share the exact same title; otherwise each side gets its own named directory
   (auto-suffixed, e.g. "-2", only if their normalized slugs happen to collide despite different
   true titles--collisions are otherwise irrelevant across different ordinals).

   `commit_test_cases` reconstructs the flat list by walking ordinals in sorted order and emitting
   the local test (if present) then the validator test (if present)--this may reorder relative to
   the original API response, but preserves each side's own relative order, which is what actually
   matters (see module docstring above).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..client.common.protocol.contribution import CgTestCase
from ..common.dataclass_wizard_x import CatchAll, JSONWizardX

__all__ = [
    "TESTS_SUBDIR_NAME",
    "TEST_META_FILE_NAME",
    "LOCAL_SUBDIR_NAME",
    "VALIDATOR_SUBDIR_NAME",
    "CgContributionTestCaseError",
    "CgTestCaseFileMeta",
    "normalize_test_title",
    "import_test_cases",
    "commit_test_cases",
    "renormalize_test_case_dirs",
]

TESTS_SUBDIR_NAME = "tests"
"""Name of the contribution working directory's test-cases subdirectory."""

TEST_META_FILE_NAME = "test.json"
"""Name of the metadata file within each named test directory."""

LOCAL_SUBDIR_NAME = "local"
"""Name of the subdirectory holding a local (`is_test=True`) test case's input/output."""

VALIDATOR_SUBDIR_NAME = "validator"
"""Name of the subdirectory holding a server-side validator (`is_validator=True`) test case's
   input/output."""

_INPUT_FILE_NAME = "input.txt"
_OUTPUT_FILE_NAME = "output.txt"

_SLUG_INVALID_RUN_RE = re.compile(r"[^A-Za-z0-9]+")
_NATURAL_SORT_RE = re.compile(r"(\d+)")


class CgContributionTestCaseError(Exception):
    """Raised by `commit_test_cases` when `tests/`'s on-disk layout is malformed in a way that
       can't be interpreted--e.g. more than one local (or validator) test case directory under a
       single ordinal directory. Only possible via manual editing; `import_test_cases` never
       produces a layout that triggers this."""


@dataclass
class CgTestCaseFileMeta(JSONWizardX):
    """The content of a single test case directory's `test.json`: just the test's real,
       unnormalized title (the directory name itself is a lossy filename-friendly slug--see
       `normalize_test_title`)."""

    title: str
    """The test case's real title, exactly as it appears in `CgTestCase.title`."""

    extra_data: CatchAll = field(default_factory=dict)


def normalize_test_title(title: str) -> str:
    """Convert a test case title into a filename-friendly slug: runs of whitespace/punctuation
       become a single dash, and leading/trailing dashes are stripped. Falls back to "test" if
       nothing alphanumeric remains (e.g. a title that's pure punctuation)."""
    slug = _SLUG_INVALID_RUN_RE.sub("-", title).strip("-")
    return slug or "test"


def _unique_name(base: str, used: set[str]) -> str:
    """Return `base`, or `base` suffixed with "-2", "-3", etc. until it's not already in `used`."""
    if base not in used:
        return base
    n = 2
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def _natural_sort_key(name: str) -> tuple[object, ...]:
    """Sort key that compares embedded digit runs numerically rather than lexicographically (so
       "9" sorts before "10"), while staying agnostic to padding/format--works for clean zero-
       padded names as well as free-form ones like "05a" or "6"."""
    parts = _NATURAL_SORT_RE.split(name)
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _ensure_trailing_newline(text: str) -> str:
    """Append a trailing newline if `text` doesn't already end with one--used only when importing
       server-provided content into files, so a clean import-then-commit round trip (with no
       edits) doesn't spuriously diff against the file's on-disk convention. The reverse
       (stripping a trailing newline before submission) already happens automatically in
       `CgAsyncContributionServiceHelper.update_contribution`."""
    return text if text.endswith("\n") else text + "\n"


def _write_test_meta(named_dir: Path, title: str) -> None:
    named_dir.mkdir(parents=True, exist_ok=True)
    CgTestCaseFileMeta(title=title).save(named_dir / TEST_META_FILE_NAME)


def _write_test_side(named_dir: Path, side_subdir_name: str, test_case: CgTestCase) -> None:
    side_dir = named_dir / side_subdir_name
    side_dir.mkdir(parents=True, exist_ok=True)
    (side_dir / _INPUT_FILE_NAME).write_text(_ensure_trailing_newline(test_case.test_in), encoding="utf-8")
    (side_dir / _OUTPUT_FILE_NAME).write_text(_ensure_trailing_newline(test_case.test_out), encoding="utf-8")


def _place_ordinal(ordinal_dir: Path, local: CgTestCase | None, validator: CgTestCase | None) -> None:
    used_names: set[str] = set()
    if local is not None and validator is not None and local.title == validator.title:
        name = _unique_name(normalize_test_title(local.title), used_names)
        named_dir = ordinal_dir / name
        _write_test_meta(named_dir, local.title)
        _write_test_side(named_dir, LOCAL_SUBDIR_NAME, local)
        _write_test_side(named_dir, VALIDATOR_SUBDIR_NAME, validator)
        return
    if local is not None:
        name = _unique_name(normalize_test_title(local.title), used_names)
        used_names.add(name)
        named_dir = ordinal_dir / name
        _write_test_meta(named_dir, local.title)
        _write_test_side(named_dir, LOCAL_SUBDIR_NAME, local)
    if validator is not None:
        name = _unique_name(normalize_test_title(validator.title), used_names)
        used_names.add(name)
        named_dir = ordinal_dir / name
        _write_test_meta(named_dir, validator.title)
        _write_test_side(named_dir, VALIDATOR_SUBDIR_NAME, validator)


def import_test_cases(test_cases: list[CgTestCase], tests_dir: Path) -> None:
    """(Re)build `tests_dir` from a flat list of test cases (as returned by `findContribution`),
       entirely replacing any existing content there. Local (`is_test=True`) and validator
       (`is_validator=True`) test cases are each numbered separately, in their existing relative
       order, and paired by that number into ordinal directories--see the module docstring.

       Ordinal directories are always written as zero-padded numbers (width based on the total
       count, minimum 2 digits, e.g. "01"); `commit_test_cases` is agnostic to this and tolerates
       any renaming.
    """
    locals_ = [tc for tc in test_cases if tc.is_test]
    validators = [tc for tc in test_cases if tc.is_validator]
    if tests_dir.exists():
        shutil.rmtree(tests_dir)
    count = max(len(locals_), len(validators))
    if count == 0:
        return
    width = max(2, len(str(count)))
    tests_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        local = locals_[i] if i < len(locals_) else None
        validator = validators[i] if i < len(validators) else None
        ordinal_dir = tests_dir / str(i + 1).zfill(width)
        _place_ordinal(ordinal_dir, local, validator)


def _read_test_meta_title(named_dir: Path) -> str:
    """The test's title, from `test.json` if present. If a named test directory was created by
       hand without one, falls back to a reasonable guess derived from the directory name itself
       (dashes turned back into spaces)--lossy relative to a real title (the normalization that
       produced the slug can't be undone exactly), but good enough to avoid forcing a `test.json`
       to exist for every manually-added test case."""
    meta_path = named_dir / TEST_META_FILE_NAME
    if meta_path.is_file():
        return CgTestCaseFileMeta.load(meta_path).title
    return named_dir.name.replace("-", " ")


def _read_test_side(side_dir: Path, title: str, *, is_test: bool, is_validator: bool) -> CgTestCase:
    test_in = (side_dir / _INPUT_FILE_NAME).read_text(encoding="utf-8")
    test_out = (side_dir / _OUTPUT_FILE_NAME).read_text(encoding="utf-8")
    return CgTestCase(
            title=title,
            test_in=test_in,
            test_out=test_out,
            is_test=is_test,
            is_validator=is_validator,
            need_validation=True,
        )


def commit_test_cases(tests_dir: Path) -> list[CgTestCase]:
    """Read `tests_dir` back into a flat `list[CgTestCase]`, in the order `updateContribution`
       should submit them: ordinal directories in natural-sort order, and within each, the local
       test case (if present) followed by the validator test case (if present)--see the module
       docstring for why this ordering is safe (each side's own relative order is preserved, even
       though the two may be interleaved differently than in the original API response).

       Returns an empty list if `tests_dir` doesn't exist (no test cases yet).
    """
    if not tests_dir.is_dir():
        return []
    ordinal_dirs = sorted(
            (d for d in tests_dir.iterdir() if d.is_dir()),
            key=lambda d: _natural_sort_key(d.name),
        )
    result: list[CgTestCase] = []
    for ordinal_dir in ordinal_dirs:
        local_entry: CgTestCase | None = None
        validator_entry: CgTestCase | None = None
        named_dirs = sorted((d for d in ordinal_dir.iterdir() if d.is_dir()), key=lambda d: d.name)
        for named_dir in named_dirs:
            title = _read_test_meta_title(named_dir)
            local_side = named_dir / LOCAL_SUBDIR_NAME
            if local_side.is_dir():
                if local_entry is not None:
                    raise CgContributionTestCaseError(
                            f"Multiple local test case directories found under {ordinal_dir}")
                local_entry = _read_test_side(local_side, title, is_test=True, is_validator=False)
            validator_side = named_dir / VALIDATOR_SUBDIR_NAME
            if validator_side.is_dir():
                if validator_entry is not None:
                    raise CgContributionTestCaseError(
                            f"Multiple validator test case directories found under {ordinal_dir}")
                validator_entry = _read_test_side(validator_side, title, is_test=False, is_validator=True)
        if local_entry is not None:
            result.append(local_entry)
        if validator_entry is not None:
            result.append(validator_entry)
    return result


def renormalize_test_case_dirs(tests_dir: Path) -> None:
    """Rewrite `tests_dir`'s ordinal directory names as a clean, sequential, zero-padded sort key
       (matching what `import_test_cases` would produce), preserving relative order via the same
       natural-sort comparator `commit_test_cases` uses. Named/local/validator subdirectory
       content is untouched--only the ordinal directories themselves are renamed. A no-op if
       `tests_dir` doesn't exist or is empty.
    """
    if not tests_dir.is_dir():
        return
    ordinal_dirs = sorted(
            (d for d in tests_dir.iterdir() if d.is_dir()),
            key=lambda d: _natural_sort_key(d.name),
        )
    if not ordinal_dirs:
        return
    width = max(2, len(str(len(ordinal_dirs))))
    # Two-phase rename (via temporary names) so that renumbering never collides with another
    # ordinal directory's current (pre-renumbering) name.
    staged: list[tuple[Path, str]] = []
    for i, d in enumerate(ordinal_dirs):
        temp_path = tests_dir / f".renormalize-tmp-{i}"
        d.rename(temp_path)
        staged.append((temp_path, str(i + 1).zfill(width)))
    for temp_path, target_name in staged:
        temp_path.rename(tests_dir / target_name)
