"""Unit tests for codingame_tools.contribution_manager.schema (CgContributionIdentity,
   CgContributionView) and codingame_tools.contribution_manager.contribution_commit_data
   (CgContributionCommitMetadata, redact_commit_contribution).

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

from codingame_tools.client.common.protocol.contribution import (
    CgContribution,
    CgContributionData,
    CgContributionVersion,
)
from codingame_tools.contribution_manager.contribution_commit_data import (
    CgContributionCommitMetadata,
    redact_commit_contribution,
)
from codingame_tools.contribution_manager.schema import (
    CONTRIBUTION_SCHEMA_VERSION,
    CgContributionIdentity,
    CgContributionView,
)


def _make_contribution(*, public_handle: str = "handle-123", version: int = 3, cover_binary_id: int | None = None) -> CgContribution:
    return CgContribution(
            id=1,
            active_version=version,
            score=0,
            votable_id=2,
            codingamer_id=7412395,
            views=0,
            commentable_id=3,
            title="My Puzzle",
            status="PENDING",
            nickname="tester",
            public_handle=public_handle,
            codingamer_handle="cg-handle",
            last_version=CgContributionVersion(
                    version=version,
                    data=CgContributionData(title="My Puzzle", cover_binary_id=cover_binary_id),
                    statement_html="<p>rendered</p>",
                ),
            avatar=0,
            comment_count=0,
            up_votes=0,
            down_votes=0,
            editable=True,
            draft=True,
            ready_for_moderation=False,
            contribution_type="PUZZLE_INOUT",
        )


# --- CgContributionIdentity -------------------------------------------------------------------


def test_identity_round_trips_through_json(tmp_path: Path) -> None:
    identity = CgContributionIdentity(
            schema_version=CONTRIBUTION_SCHEMA_VERSION, contribution_handle="the-handle", git_dir_in_data=True,
        )
    path = tmp_path / "contribution.json"
    identity.save(path)
    reloaded = CgContributionIdentity.load(path)
    assert reloaded == identity


def test_identity_git_dir_in_data_defaults_to_false() -> None:
    identity = CgContributionIdentity(schema_version=CONTRIBUTION_SCHEMA_VERSION, contribution_handle="the-handle")
    assert identity.git_dir_in_data is False


def test_identity_contribution_handle_defaults_to_none() -> None:
    """A `create()`d-but-never-successfully-`push()`d working directory has no server-side
       contribution yet--see `CgContributionManager.push()`'s docstring."""
    identity = CgContributionIdentity(schema_version=CONTRIBUTION_SCHEMA_VERSION)
    assert identity.contribution_handle is None


def test_identity_with_none_handle_round_trips_through_json(tmp_path: Path) -> None:
    identity = CgContributionIdentity(schema_version=CONTRIBUTION_SCHEMA_VERSION, git_dir_in_data=True)
    path = tmp_path / "contribution.json"
    identity.save(path)
    reloaded = CgContributionIdentity.load(path)
    assert reloaded == identity
    assert reloaded.contribution_handle is None


# --- CgContributionView ----------------------------------------------------------------------


def test_view_round_trips_through_json(tmp_path: Path) -> None:
    view = CgContributionView(
            puzzle_type="PUZZLE_INOUT",
            draft=True,
            ready_for_moderation=False,
            data=CgContributionData(title="My Puzzle"),
        )
    path = tmp_path / "contribution-data.json"
    view.save(path)
    reloaded = CgContributionView.load(path)
    assert reloaded == view


def test_view_has_sensible_defaults() -> None:
    view = CgContributionView(data=CgContributionData(title="x"))
    assert view.draft is True
    assert view.ready_for_moderation is False
    assert view.puzzle_type is None


# --- CgContributionCommitMetadata / redact_commit_contribution ---------------------------------


def test_commit_metadata_round_trips_through_json(tmp_path: Path) -> None:
    metadata = CgContributionCommitMetadata(
            contribution_id="the-handle", version=5, cover_binary_id=555, cover_binary_hash="abc123",
        )
    path = tmp_path / "metadata.json"
    metadata.save(path)
    reloaded = CgContributionCommitMetadata.load(path)
    assert reloaded == metadata


def test_commit_metadata_cover_fields_default_to_none() -> None:
    metadata = CgContributionCommitMetadata(contribution_id="the-handle", version=5)
    assert metadata.cover_binary_id is None
    assert metadata.cover_binary_hash is None


def test_redact_nulls_all_content_and_flags_including_cover_binary_id() -> None:
    """cover_binary_id is tracked as its own explicit `CgContributionCommitMetadata` field (git
       trailer) instead--the embedded `CgContribution` is redacted with no exceptions."""
    original = _make_contribution(cover_binary_id=555)
    redacted = redact_commit_contribution(original)

    # Preserved: identity/version-tracking fields.
    assert redacted.public_handle == original.public_handle
    assert redacted.last_version.version == original.last_version.version
    assert redacted.active_version == original.active_version

    # Redacted: everything that duplicates CgContributionView/contribution-data.json, including
    # cover_binary_id.
    assert redacted.last_version.data.cover_binary_id is None
    assert redacted.last_version.data.title == ""
    assert redacted.last_version.data.statement is None
    assert redacted.draft is False
    assert redacted.ready_for_moderation is False
    assert redacted.contribution_type == ""
    assert redacted.last_version.draft is None
    assert redacted.last_version.ready_for_moderation is None
    assert redacted.last_version.statement_html is None


def test_redact_does_not_mutate_the_original() -> None:
    original = _make_contribution()
    redact_commit_contribution(original)
    assert original.draft is True
    assert original.last_version.data.title == "My Puzzle"
