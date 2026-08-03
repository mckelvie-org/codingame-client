"""Tests for the release-time README link rewriting.

`README.md` has to serve two audiences from one file. GitHub resolves relative links; PyPI, which
renders the same file as the project's front page, resolves them against `pypi.org` and 404s. So
`bin/cut-rc`/`bin/cut-prod` rewrite them to absolute, tag-pinned URLs in the throwaway worktree they
build the release commit in -- leaving `main` with ordinary relative links.

That means the rewriting is only ever exercised during a release, when getting it wrong produces a
published page full of dead links and no way to fix it without cutting another version. Hence
testing it directly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rewrite_readme_links import rewrite_links  # noqa: E402  (needs the path fix above)

REPO = "mckelvie-org/codingame-tools"
REF = "v1.2.3"


def _rewrite(text: str, root: Path | None = None) -> str:
    return rewrite_links(text, REPO, REF, root if root is not None else REPO_ROOT)


def test_relative_file_link_becomes_a_pinned_blob_url() -> None:
    assert _rewrite("[docs](doc/index.md)") == (
        f"[docs](https://github.com/{REPO}/blob/{REF}/doc/index.md)")


def test_anchor_is_preserved() -> None:
    """Losing the fragment would silently land the reader at the top of a long page."""
    assert _rewrite("[cmp](doc/design/final-newlines.md#output-comparison)") == (
        f"[cmp](https://github.com/{REPO}/blob/{REF}/doc/design/final-newlines.md#output-comparison)")


def test_directories_use_tree_not_blob(tmp_path: Path) -> None:
    """GitHub doesn't redirect between the two, so a directory linked as `blob` is a 404."""
    (tmp_path / "doc").mkdir()
    assert _rewrite("[dir](doc)", root=tmp_path) == f"[dir](https://github.com/{REPO}/tree/{REF}/doc)"


def test_images_use_raw_urls() -> None:
    """A blob URL serves GitHub's HTML chrome, not the image bytes--PyPI would render a broken
       image."""
    assert _rewrite("![logo](doc/logo.png)") == (
        f"![logo](https://raw.githubusercontent.com/{REPO}/{REF}/doc/logo.png)")


@pytest.mark.parametrize("link", [
    "[pypi](https://pypi.org/project/codingame-tools/)",
    "[mail](mailto:dev@mckelvie.org)",
    "[section](#highlights)",
    "[proto](//example.com/x)",
])
def test_already_resolvable_targets_are_untouched(link: str) -> None:
    assert _rewrite(link) == link


def test_leading_dot_slash_is_normalized() -> None:
    assert _rewrite("[x](./doc/index.md)") == (
        f"[x](https://github.com/{REPO}/blob/{REF}/doc/index.md)")


def test_link_titles_survive() -> None:
    assert _rewrite('[x](doc/index.md "The docs")') == (
        f'[x](https://github.com/{REPO}/blob/{REF}/doc/index.md "The docs")')


def test_reference_style_definitions_are_rewritten() -> None:
    assert _rewrite("[docs]: doc/index.md") == (
        f"[docs]: https://github.com/{REPO}/blob/{REF}/doc/index.md")


def test_fenced_code_is_left_alone() -> None:
    """A fence can legitimately contain something that looks like a link--rewriting an example
       would corrupt it, and the reader can't tell it was us."""
    text = "```markdown\n[docs](doc/index.md)\n```\n[real](doc/index.md)\n"
    result = _rewrite(text)
    assert "```markdown\n[docs](doc/index.md)\n```" in result
    assert f"[real](https://github.com/{REPO}/blob/{REF}/doc/index.md)" in result


def test_rewriting_is_idempotent() -> None:
    """A re-run (a retried `cut-rc --force`, say) must not double-rewrite into a URL containing
       another URL."""
    once = _rewrite("[docs](doc/index.md)")
    assert _rewrite(once) == once


def test_the_real_readme_has_no_relative_links_left_after_rewriting() -> None:
    """End to end on the actual file: after a release rewrite, nothing relative may survive, or
       PyPI gets a dead link."""
    rewritten = _rewrite((REPO_ROOT / "README.md").read_text(encoding="utf-8"))

    fence = None
    for line in rewritten.splitlines():
        marker = re.match(r"^\s*(```|~~~)", line)
        if marker:
            fence = None if fence == marker.group(1) else (fence or marker.group(1))
            continue
        if fence is not None:
            continue
        for target in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)", line):
            assert target.startswith(("https://", "http://", "#")), (
                f"relative link survived rewriting, would 404 on PyPI: {target}")


def test_the_real_readme_links_resolve_before_rewriting() -> None:
    """The other side of the same coin: the relative links have to be correct in the repo, or the
       rewrite faithfully produces absolute URLs to files that don't exist."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [
        target for target in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)\)", text)
        if not target.startswith(("https://", "http://", "#", "mailto:"))
        and not (REPO_ROOT / target.partition("#")[0]).exists()
    ]
    assert not missing, f"README links to files that don't exist: {missing}"
