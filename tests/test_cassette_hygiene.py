"""Guards against ever committing a VCR cassette that contains cookie data.

conftest.py's before_record_response hook and filter_headers config already strip cookies
at recording time, but this test independently re-checks every committed cassette file so a
future vcrpy version, a config regression, or a manually-edited/hand-added cassette can't
silently reintroduce cookie values (e.g. AWSALB/AWSALBCORS, rememberMe, cgSession) into the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import CASSETTE_DIR

# Matches a YAML "Set-Cookie"/"Set-Cookie2" header key (any casing) in a cassette response,
# and a "Cookie" request header key. Also matches the known CodinGame/AWS cookie names directly,
# as a belt-and-suspenders check in case one ever appears somewhere other than a header (e.g.
# a body dump of raw headers).
_FORBIDDEN_PATTERNS = [
    re.compile(r"(?im)^\s*set-cookie2?\s*:"),
    re.compile(r"(?im)^\s*cookie\s*:"),
    re.compile(r"(?i)\brememberMe\b"),
    re.compile(r"(?i)\bcgSession\b"),
    re.compile(r"(?i)\bAWSALB(CORS)?\b"),
]


def _cassette_files() -> list[Path]:
    if not CASSETTE_DIR.is_dir():
        return []
    return sorted(CASSETTE_DIR.glob("*.yaml"))


@pytest.mark.parametrize("cassette_path", _cassette_files(), ids=lambda p: p.name)
def test_cassette_has_no_cookie_data(cassette_path: Path) -> None:
    text = cassette_path.read_text(encoding="utf-8")
    for pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"{cassette_path.name} appears to contain cookie data "
            f"(matched {pattern.pattern!r} at position {match.start() if match else '?'}); "
            "cassettes must never persist cookie values."
        )


def test_at_least_one_cassette_exists() -> None:
    """Sanity check that this test module is actually exercising real cassette files."""
    assert _cassette_files(), f"No cassette files found in {CASSETTE_DIR}"
