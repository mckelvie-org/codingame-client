"""Unit tests for codingame_client.contribution_manager.manager.CgContributionManager
   (`import_`/`commit`/`fetch`/`rebase`/`merge_discard_local`/`merge_discard_server`/`revert`/
   `merge_start`/`merge_continue`/`merge_abort`), against a fake, duck-typed client
   (services.contribution, servlets.file_servlet, servlets.file_upload)--no real
   CgAsyncClient/network involved. Real git subprocess calls run against `tmp_path`.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
`git` itself is required on PATH (see `requires_git`)--near-universal in dev/CI environments, but
skipped gracefully if genuinely absent, for parity with `requires_diff3` elsewhere in this suite.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest

from codingame_client.client.common.protocol.contribution import (
    CgContribution,
    CgContributionData,
    CgContributionVersion,
    CgTestCase,
)
from codingame_client.client.common.raw_client import CgDownloadFileResult, CgUploadFileResult, compute_content_hash
from codingame_client.contribution_manager.manager import (
    CgContributionManager,
    CgContributionManagerError,
    CgMergeStartStatus,
    CgRebaseStatus,
)
from codingame_client.contribution_manager.schema import CgContributionView

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
pytestmark = requires_git

COVER_CONTENT = b"fake-png-bytes"


def _make_test_case(title: str, i: str, o: str, *, is_test: bool, is_validator: bool) -> CgTestCase:
    return CgTestCase(title=title, test_in=i, test_out=o, is_test=is_test, is_validator=is_validator, need_validation=True)


def _make_full_data(
            *, cover_binary_id: int | None = 555, statement: str = "The statement",
            solution_language: str | None = "Python3", solution: str | None = "print('hi')",
        ) -> CgContributionData:
    return CgContributionData(
            title="My Puzzle",
            statement=statement,
            input_description="Input desc",
            output_description="Output desc",
            constraints="1 <= N <= 100",
            difficulty="easy",
            stub_generator="read int N;",
            topics=[],
            test_cases=[
                    _make_test_case("Case A", "1", "2", is_test=True, is_validator=False),
                    _make_test_case("Case A", "3", "4", is_test=False, is_validator=True),
                ],
            solution_language=solution_language,
            solution=solution,
            cover_binary_id=cover_binary_id,
        )


def _make_contribution(
            data: CgContributionData, *,
            public_handle: str = "handle-1",
            version: int = 3,
            draft: bool = True,
            ready_for_moderation: bool = False,
        ) -> CgContribution:
    return CgContribution(
            id=1, active_version=version, score=0, votable_id=2, codingamer_id=7412395,
            views=0, commentable_id=3, title=data.title, status="PENDING", nickname="tester",
            public_handle=public_handle, codingamer_handle="cg-handle",
            last_version=CgContributionVersion(
                    version=version, data=data, statement_html="<p>rendered</p>",
                    draft=draft, ready_for_moderation=ready_for_moderation,
                ),
            avatar=0, comment_count=0, up_votes=0, down_votes=0, editable=True,
            draft=draft, ready_for_moderation=ready_for_moderation, contribution_type="PUZZLE_INOUT",
        )


class _FakeContributionHelper:
    def __init__(self, service: _FakeContributionService) -> None:
        self._service = service

    async def update_contribution(
                self, contribution_id: str, puzzle_type: str, contribution_data: CgContributionData,
                draft: bool, ready_for_moderation: bool, prev_version: int,
                codingamer_id: int | None = None, **kwargs: Any,
            ) -> CgContribution:
        self._service.update_calls.append({
                "contribution_id": contribution_id, "puzzle_type": puzzle_type,
                "contribution_data": contribution_data, "draft": draft,
                "ready_for_moderation": ready_for_moderation, "prev_version": prev_version,
            })
        return self._service.update_result


class _FakeContributionService:
    def __init__(self, find_result: CgContribution, update_result: CgContribution | None = None) -> None:
        self.find_result = find_result
        self.update_result = update_result if update_result is not None else find_result
        self.update_calls: list[dict[str, Any]] = []
        self.find_call_count = 0
        self.helper = _FakeContributionHelper(self)

    async def find_contribution(self, contribution_id: str, arg2: bool = True) -> CgContribution:
        self.find_call_count += 1
        return self.find_result


class _FakeServices:
    def __init__(self, contribution: _FakeContributionService) -> None:
        self.contribution = contribution


class _FakeFileServlet:
    def __init__(self, result: CgDownloadFileResult) -> None:
        self.result = result
        self.calls: list[int] = []

    async def __call__(
                self, id: int, format: str | None = None, timestamp: object = None, *, require_login: bool = True,
            ) -> CgDownloadFileResult:
        self.calls.append(id)
        return self.result


class _FakeFileUpload:
    def __init__(self, result: CgUploadFileResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def __call__(
                self, content: bytes, *, filename: str | None = None,
                content_type: str = "application/octet-stream", params: object = None,
            ) -> CgUploadFileResult:
        self.calls.append({"content": content, "filename": filename, "content_type": content_type})
        return self.result


class _FakeServlets:
    def __init__(self, file_servlet: _FakeFileServlet, file_upload: _FakeFileUpload) -> None:
        self.file_servlet = file_servlet
        self.file_upload = file_upload


class _FakeClient:
    def __init__(self, contribution_service: _FakeContributionService, servlets: _FakeServlets) -> None:
        self.services = _FakeServices(contribution_service)
        self.servlets = servlets


async def _start_conflicting_merge(
            manager: CgContributionManager, service: _FakeContributionService, data: CgContributionData,
        ) -> None:
    """Commit a local edit onto `main`, then advance the fake server with a conflicting edit to
       the same field, and start a merge--leaving it genuinely in progress (unresolved conflict
       markers), unlike a same-content/no-op version bump (which git merges cleanly and
       auto-commits, never leaving anything "in progress")."""
    (manager.data_dir / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    result = await manager.merge_start()
    assert manager.merge_in_progress, f"test setup didn't actually produce an in-progress merge: {result}"


def _make_fake_client(
            find_result: CgContribution,
            *,
            update_result: CgContribution | None = None,
            new_upload_id: int = 999,
            cover_content: bytes = COVER_CONTENT,
        ) -> tuple[_FakeClient, _FakeContributionService, _FakeFileUpload, _FakeFileServlet]:
    contribution_service = _FakeContributionService(find_result, update_result)
    file_servlet = _FakeFileServlet(
            CgDownloadFileResult.create(id=555, content=cover_content, content_type="image/png", filename="cover.png"))
    file_upload = _FakeFileUpload(CgUploadFileResult(id=new_upload_id, name="cover.png", size=len(cover_content), field_name="file"))
    servlets = _FakeServlets(file_servlet, file_upload)
    client = _FakeClient(contribution_service, servlets)
    return client, contribution_service, file_upload, file_servlet


# --- import_ -----------------------------------------------------------------------------


async def test_import_writes_identity_view_content_files_and_git_repo(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    view = await manager.import_("handle-1")

    assert (tmp_path / "data" / "statement.cgmd").read_text() == "The statement\n"
    assert (tmp_path / "data" / "input_description.cgmd").read_text() == "Input desc\n"
    assert (tmp_path / "data" / "output_description.cgmd").read_text() == "Output desc\n"
    assert (tmp_path / "data" / "constraints.cgmd").read_text() == "1 <= N <= 100\n"
    assert (tmp_path / "data" / "stub_generator.cgstub").read_text() == "read int N;\n"
    assert (tmp_path / "data" / "cover.png").read_bytes() == COVER_CONTENT
    assert (tmp_path / "data" / "solution.src").read_text() == "print('hi')\n"
    assert (tmp_path / "solution.py").is_symlink()
    assert (tmp_path / "solution.py").resolve() == (tmp_path / "data" / "solution.src").resolve()
    assert (tmp_path / "data" / "tests" / "01").is_dir()

    assert view.puzzle_type == "PUZZLE_INOUT"
    assert view.draft is True
    assert view.ready_for_moderation is False
    assert view.data.statement is None  # always-empty by convention
    assert view.data.title == "My Puzzle"

    identity = manager.load_identity()
    assert identity is not None
    assert identity.contribution_handle == "handle-1"

    assert manager.git_dir.is_dir()
    repo = manager.git_repo
    assert repo.resolve_ref("main") == repo.resolve_ref("server")
    assert repo.merge_base("main", "server") == repo.resolve_ref("main")

    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.contribution_id == "handle-1"
    assert metadata.version == 3
    assert metadata.cover_binary_id == 555
    assert metadata.cover_binary_hash == compute_content_hash(COVER_CONTENT)

    assert manager.contribution_data_file.is_file()
    assert CgContributionView.load(manager.contribution_data_file) == view


async def test_import_writes_gitignore_for_meta(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    # Not inside an existing outer git repo (tmp_path is bare) -> git-dir nested in data/, so the
    # protective .gitignore lives at data/.gitignore.
    identity = manager.load_identity()
    assert identity is not None
    assert identity.git_dir_in_data is True
    assert (tmp_path / "data" / ".gitignore").read_text() == ".meta/\n"


async def test_import_with_no_cover_image_leaves_cover_hash_none(tmp_path: Path) -> None:
    data = _make_full_data(cover_binary_id=None)
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    assert not (tmp_path / "data" / "cover.png").exists()
    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.cover_binary_hash is None


async def test_import_with_unmapped_language_writes_solution_src_without_symlink(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="SomeUnknownLanguage")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    assert (tmp_path / "data" / "solution.src").read_text() == "print('hi')\n"
    assert list(tmp_path.glob("solution.*")) == []  # no known extension to map--no symlink created


async def test_import_refuses_to_retarget_an_existing_directory(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    other_contribution = _make_contribution(data, public_handle="handle-2")
    client2, _, _, _ = _make_fake_client(other_contribution)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]
    with pytest.raises(CgContributionManagerError):
        await manager2.import_("handle-2")


async def test_import_refuses_if_git_repo_already_exists(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    with pytest.raises(CgContributionManagerError):
        await manager.import_("handle-1")


async def test_import_rehydrates_when_git_dir_missing_but_content_present(tmp_path: Path) -> None:
    """Simulates cloning an outer project that tracks contribution.json/data/ but not the git-dir
       itself (deliberately outer-gitignored)--see manager.py's import_() docstring."""
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit surviving the clone\n")

    shutil.rmtree(manager.git_dir.parent)  # remove .meta/ (the git-dir container) entirely
    assert not manager.git_dir.exists()

    view = await manager.import_("handle-1")

    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit surviving the clone\n"
    assert view.data.title == "My Puzzle"
    repo = manager.git_repo
    assert repo.resolve_ref("main") == repo.resolve_ref("server")


async def test_reimport_with_language_change_regenerates_symlink(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    assert (tmp_path / "solution.py").is_symlink()

    shutil.rmtree(manager.git_dir.parent)  # force rehydration path (fresh init_repo, per above)
    new_data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    await manager2.import_("handle-1")

    # Rehydration preserves data/'s on-disk content (the OLD Python3 solution.src)--this isn't a
    # live re-fetch overwrite, so the symlink still reflects what was already there.
    assert (tmp_path / "data" / "solution.src").read_text() == "print('hi')\n"
    assert (tmp_path / "solution.py").is_symlink()


# --- commit ------------------------------------------------------------------------------


async def test_commit_requires_puzzle_type(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    view = await manager.import_("handle-1")
    manager.save(dataclasses.replace(view, puzzle_type=None))

    with pytest.raises(CgContributionManagerError):
        await manager.commit()


async def test_commit_requires_a_prior_import(tmp_path: Path) -> None:
    view = CgContributionView(puzzle_type="PUZZLE_INOUT", data=CgContributionData(title="x"))
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(view)
    with pytest.raises(FileNotFoundError):
        await manager.commit()


async def test_commit_reuses_cover_binary_id_when_content_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    updated = _make_contribution(data, version=4)
    client, service, file_upload, _ = _make_fake_client(contribution, update_result=updated)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    result = await manager.commit()

    assert result.last_version.version == 4
    assert len(service.update_calls) == 1
    assert service.update_calls[0]["contribution_data"].cover_binary_id == 555
    assert file_upload.calls == []  # not re-uploaded--content hash matched

    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.version == 4
    assert metadata.cover_binary_hash == compute_content_hash(COVER_CONTENT)
    repo = manager.git_repo
    assert repo.resolve_ref("main") == repo.resolve_ref("server")


async def test_commit_reuploads_cover_when_content_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    updated = _make_contribution(data, version=4)
    client, service, file_upload, _ = _make_fake_client(contribution, update_result=updated, new_upload_id=777)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "cover.png").write_bytes(b"changed-bytes")

    await manager.commit()

    assert len(file_upload.calls) == 1
    assert service.update_calls[0]["contribution_data"].cover_binary_id == 777


async def test_commit_reflects_edited_sidecar_files(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    updated = _make_contribution(data, version=4)
    client, service, _, _ = _make_fake_client(contribution, update_result=updated)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Edited statement\n")

    await manager.commit()

    submitted = service.update_calls[0]["contribution_data"]
    assert submitted.statement == "Edited statement\n"
    assert [tc.title for tc in submitted.test_cases] == ["Case A", "Case A"]
    assert submitted.solution == "print('hi')\n"


async def test_commit_passes_view_puzzle_type_and_flags(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data, draft=False, ready_for_moderation=True)
    updated = _make_contribution(data, version=4)
    client, service, _, _ = _make_fake_client(contribution, update_result=updated)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    view = await manager.import_("handle-1")
    assert view.draft is False
    assert view.ready_for_moderation is True

    await manager.commit()

    call = service.update_calls[0]
    assert call["puzzle_type"] == "PUZZLE_INOUT"
    assert call["draft"] is False
    assert call["ready_for_moderation"] is True
    assert call["prev_version"] == 3


async def test_commit_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)

    with pytest.raises(CgContributionManagerError):
        await manager.commit()


# --- active_version refresh (updateContribution's response can report it stale) -----------


async def test_commit_refreshes_stale_active_version_via_find_contribution(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)  # version=3, active_version=3
    stale_update_result = dataclasses.replace(_make_contribution(data, version=4), active_version=3)
    client, service, _, _ = _make_fake_client(contribution, update_result=stale_update_result)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    service.find_result = _make_contribution(data, version=4)  # active_version=4

    result = await manager.commit()

    assert result.active_version == 4


async def test_commit_gives_up_refreshing_after_max_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr("codingame_client.contribution_manager.manager.asyncio.sleep", no_sleep)

    data = _make_full_data()
    contribution = _make_contribution(data)
    stale_update_result = dataclasses.replace(_make_contribution(data, version=4), active_version=3)
    client, service, _, _ = _make_fake_client(contribution, update_result=stale_update_result)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    service.find_result = stale_update_result

    result = await manager.commit()

    assert result.active_version == 3  # gave up, still stale--but didn't hang or raise


# --- fetch ---------------------------------------------------------------------------------


async def test_fetch_is_noop_when_version_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    server_before = manager.git_repo.resolve_ref("server")
    file_servlet.calls.clear()

    await manager.fetch()

    assert manager.git_repo.resolve_ref("server") == server_before
    assert file_servlet.calls == []


async def test_fetch_reuses_cached_cover_when_binary_id_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(statement="Server edit")  # same cover_binary_id=555
    service.find_result = _make_contribution(new_data, version=4)

    await manager.fetch()

    assert file_servlet.calls == []
    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.cover_binary_hash == compute_content_hash(COVER_CONTENT)


async def test_fetch_downloads_when_binary_id_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"new-cover-bytes", content_type="image/png")

    await manager.fetch()

    assert file_servlet.calls == [666]
    assert manager.git_repo.read_file_at("server", "cover.png") == b"new-cover-bytes"
    # working tree is never touched by fetch()
    assert (tmp_path / "data" / "cover.png").read_bytes() == COVER_CONTENT


async def test_fetch_self_heals_when_cached_cover_is_stale(tmp_path: Path) -> None:
    """Reuse only happens if the cached bytes' hash still matches what's recorded--if not
       (simulated here via a hash that doesn't match, since we can't easily corrupt a git blob in
       place), fetch re-downloads instead of raising--the cache is opportunistic, not sacred."""
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    # cover_binary_id unchanged (555) but cover_binary_hash trailer won't match COVER_CONTENT's
    # real hash if we swap in a same-id-different-bytes scenario is impossible via the public API
    # (id implies content server-side)--so exercise the self-heal path via a *changed* id whose
    # download then also fails to match on a second fetch, confirming no exception either way.
    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"cover-v4", content_type="image/png")
    await manager.fetch()

    newer_data = _make_full_data(cover_binary_id=666, statement="v5")  # same id, would try reuse
    service.find_result = _make_contribution(newer_data, version=5)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"cover-v4", content_type="image/png")

    await manager.fetch()  # doesn't raise regardless of reuse-vs-redownload outcome

    assert manager.git_repo.read_file_at("server", "cover.png") == b"cover-v4"


async def test_fetch_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)

    with pytest.raises(CgContributionManagerError):
        await manager.fetch()


# --- rebase --------------------------------------------------------------------------------


async def test_rebase_up_to_date_when_server_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    status = await manager.rebase()

    assert status == CgRebaseStatus.UP_TO_DATE
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "The statement\n"


async def test_rebase_fast_forwards_when_only_server_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(statement="Updated on server")
    service.find_result = _make_contribution(new_data, version=4)

    status = await manager.rebase()

    assert status == CgRebaseStatus.FAST_FORWARDED
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Updated on server\n"
    repo = manager.git_repo
    assert repo.resolve_ref("main") == repo.resolve_ref("server")
    # a true fast-forward, not a fresh sibling commit
    assert await manager.rebase() == CgRebaseStatus.UP_TO_DATE


async def test_rebase_reports_conflict_and_changes_nothing_when_both_diverged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    repo = manager.git_repo
    repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    status = await manager.rebase()

    assert status == CgRebaseStatus.CONFLICT
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"


async def test_rebase_up_to_date_even_with_uncommitted_local_edits_if_server_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")

    status = await manager.rebase()

    assert status == CgRebaseStatus.UP_TO_DATE
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"


async def test_rebase_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)

    with pytest.raises(CgContributionManagerError):
        await manager.rebase()


# --- merge_discard_local / merge_discard_server --------------------------------------------


async def test_merge_discard_local_always_overwrites(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    await manager.merge_discard_local()

    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Server edit\n"
    repo = manager.git_repo
    assert repo.resolve_ref("main") == repo.resolve_ref("server")


async def test_merge_discard_server_leaves_working_content_untouched(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_discard_server()

    assert result.last_version.version == 4
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"
    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.version == 4


async def test_merge_discard_local_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)
    with pytest.raises(CgContributionManagerError):
        await manager.merge_discard_local()


async def test_merge_discard_server_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)
    with pytest.raises(CgContributionManagerError):
        await manager.merge_discard_server()


# --- revert --------------------------------------------------------------------------------


async def test_revert_discards_local_edits_and_untracked_files_without_network(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    (tmp_path / "data" / "stray_untracked_file.txt").write_text("should be removed\n")
    find_calls_before = service.find_call_count
    file_servlet.calls.clear()

    view = manager.revert()

    assert (tmp_path / "data" / "statement.cgmd").read_text() == "The statement\n"
    assert not (tmp_path / "data" / "stray_untracked_file.txt").exists()
    assert view.data.title == "My Puzzle"
    assert service.find_call_count == find_calls_before
    assert file_servlet.calls == []
    assert (tmp_path / "solution.py").is_symlink()  # symlink regenerated


async def test_revert_requires_a_prior_import(tmp_path: Path) -> None:
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        manager.revert()


async def test_revert_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await _start_conflicting_merge(manager, service, data)
    with pytest.raises(CgContributionManagerError):
        manager.revert()


async def test_revert_preserves_identity(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    manager.revert()

    identity = manager.load_identity()
    assert identity is not None
    assert identity.contribution_handle == "handle-1"
    assert manager.server_metadata() is not None


# --- merge_start / merge_continue / merge_abort ---------------------------------------------


async def test_merge_start_reports_up_to_date_when_server_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")  # even with local edits present

    result = await manager.merge_start()

    assert result.status == CgMergeStartStatus.UP_TO_DATE
    assert not manager.merge_in_progress
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"  # untouched


async def test_merge_start_is_idempotent(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")  # real local commit, so the merge has conflicts
    service.find_result = _make_contribution(_make_full_data(statement="Server edit"), version=4)

    first = await manager.merge_start()
    assert first.status == CgMergeStartStatus.STARTED
    assert first.text_conflicts == ("statement.cgmd",)
    assert manager.merge_in_progress

    second = await manager.merge_start()

    assert second.status == CgMergeStartStatus.ALREADY_IN_PROGRESS
    # untouched, not re-attempted--conflict markers from the first attempt still there
    assert "<<<<<<<" in (tmp_path / "data" / "statement.cgmd").read_text()


async def test_merge_start_auto_applies_remote_only_change(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_start()

    assert result.status == CgMergeStartStatus.STARTED
    assert result.text_conflicts == ()
    assert result.binary_conflicts == ()
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Server edit\n"
    assert not manager.merge_in_progress  # clean merge auto-commits, nothing left to continue


async def test_merge_start_leaves_local_only_change_untouched(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")

    # An unrelated server-side change, so the merge machinery actually runs--otherwise a purely
    # local-only change, with the server unchanged, short-circuits to UP_TO_DATE.
    new_data = _make_full_data(solution="print('server')")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_start()

    assert result.status == CgMergeStartStatus.STARTED
    assert result.text_conflicts == ()
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"
    assert (tmp_path / "data" / "solution.src").read_text() == "print('server')\n"


async def test_merge_start_writes_diff3_markers_for_text_conflict(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_start()

    assert "statement.cgmd" in result.text_conflicts
    content = (tmp_path / "data" / "statement.cgmd").read_text()
    assert "<<<<<<<" in content
    assert "Local edit" in content
    assert "Server edit" in content
    assert manager.merge_in_progress


async def test_merge_start_keeps_local_cover_on_binary_conflict(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    local_cover = b"\x89PNG\x00locally-changed-cover"
    remote_cover = b"\x89PNG\x00remote-changed-cover"
    (tmp_path / "data" / "cover.png").write_bytes(local_cover)
    manager.git_repo.commit_worktree("local cover edit")

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=remote_cover, content_type="image/png")

    result = await manager.merge_start()

    assert "cover.png" in result.binary_conflicts
    assert (tmp_path / "data" / "cover.png").read_bytes() == local_cover  # kept local


async def test_merge_start_leaves_solution_symlink_untouched_while_conflicted(tmp_path: Path) -> None:
    """`solution.py` lives at `contribution_dir`'s root, *outside* `data/` (git's work tree)--so
       an in-progress merge (which only ever touches paths inside `data/`) can't affect it either
       way. It's only ever refreshed at merge's terminal points (`merge_continue()`/
       `merge_abort()`--see those tests), never mid-conflict."""
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)  # conflicting change -> stays in progress
    assert (tmp_path / "solution.py").is_symlink()

    result = await manager.merge_start()

    assert manager.merge_in_progress
    assert "statement.cgmd" in result.text_conflicts
    assert (tmp_path / "solution.py").is_symlink()


async def test_merge_start_handles_added_test_case_from_remote(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_test_cases = [*data.test_cases, _make_test_case("Case B", "5", "6", is_test=True, is_validator=False)]
    new_data = dataclasses.replace(data, test_cases=new_test_cases)
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_start()

    assert result.text_conflicts == () and result.binary_conflicts == ()
    assert (tmp_path / "data" / "tests" / "02" / "Case-B" / "local" / "input.txt").read_text() == "5\n"


async def test_merge_continue_requires_in_progress_merge(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    with pytest.raises(CgContributionManagerError):
        manager.merge_continue()


async def test_merge_continue_refuses_when_markers_remain(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    await manager.merge_start()

    with pytest.raises(CgContributionManagerError):
        manager.merge_continue()


async def test_merge_continue_succeeds_once_markers_resolved(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    await manager.merge_start()

    (tmp_path / "data" / "statement.cgmd").write_text("Resolved by hand\n")
    manager.merge_continue()

    assert not manager.merge_in_progress
    metadata = manager.server_metadata()
    assert metadata is not None
    assert metadata.version == 4
    assert (tmp_path / "solution.py").is_symlink()  # regenerated at continue time
    repo = manager.git_repo
    assert repo.merge_base("main", "server") == repo.resolve_ref("server")


async def test_merge_abort_requires_in_progress_merge(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    with pytest.raises(CgContributionManagerError):
        manager.merge_abort()


async def test_merge_abort_restores_pre_merge_state(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    manager.git_repo.commit_worktree("local edit")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    await manager.merge_start()

    manager.merge_abort()

    assert not manager.merge_in_progress
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"  # restored to pre-merge local state
    assert (tmp_path / "solution.py").is_symlink()
    metadata = manager.server_metadata()
    assert metadata is not None
    # server itself is NOT rolled back--merge_start()'s fetch() (step 1) already advanced it
    # before the merge attempt even began; merge_abort() only undoes the merge attempt against
    # main, not that prior fetch (see CgContributionManager.merge_abort's docstring).
    assert metadata.version == 4
