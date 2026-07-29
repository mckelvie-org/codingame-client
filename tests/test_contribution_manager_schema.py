"""Unit tests for codingame_client.contribution_manager.schema.CgContributionWorkingDir and
   codingame_client.contribution_manager.last_committed.CgLastCommittedContribution:
   round-tripping through their JSON files, and the contribution_id/prev_version convenience
   properties on the latter.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

from pathlib import Path

from codingame_client.client.common.protocol.contribution import (
    CgContribution,
    CgContributionData,
    CgContributionVersion,
)
from codingame_client.contribution_manager.last_committed import CgLastCommittedContribution
from codingame_client.contribution_manager.schema import CgContributionWorkingDir


def _make_contribution(*, public_handle: str = "handle-123", version: int = 3) -> CgContribution:
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
            last_version=CgContributionVersion(version=version, data=CgContributionData(title="My Puzzle")),
            avatar=0,
            comment_count=0,
            up_votes=0,
            down_votes=0,
            editable=True,
            draft=True,
            ready_for_moderation=False,
            contribution_type="PUZZLE_INOUT",
        )


# --- CgContributionWorkingDir ----------------------------------------------------------------


def test_working_dir_round_trips_through_json(tmp_path: Path) -> None:
    working = CgContributionWorkingDir(
            puzzle_type="PUZZLE_INOUT",
            draft=True,
            ready_for_moderation=False,
            solution_file="solution.py",
            data=CgContributionData(title="My Puzzle"),
        )
    path = tmp_path / "contribution.json"
    working.save(path)
    reloaded = CgContributionWorkingDir.load(path)
    assert reloaded == working


def test_default_working_dir_has_sensible_defaults() -> None:
    working = CgContributionWorkingDir(data=CgContributionData(title="x"))
    assert working.draft is True
    assert working.ready_for_moderation is False
    assert working.puzzle_type is None
    assert working.solution_file is None


# --- CgLastCommittedContribution -------------------------------------------------------------


def test_last_committed_round_trips_through_json(tmp_path: Path) -> None:
    last_committed = CgLastCommittedContribution(contribution=_make_contribution(), cover_binary_hash="abc123")
    path = tmp_path / "contribution.json"
    last_committed.save(path)
    reloaded = CgLastCommittedContribution.load(path)
    assert reloaded == last_committed


def test_last_committed_contribution_id_and_prev_version() -> None:
    last_committed = CgLastCommittedContribution(contribution=_make_contribution(public_handle="the-handle", version=5))
    assert last_committed.contribution_id == "the-handle"
    assert last_committed.prev_version == 5


def test_last_committed_cover_binary_hash_defaults_to_none() -> None:
    last_committed = CgLastCommittedContribution(contribution=_make_contribution())
    assert last_committed.cover_binary_hash is None
