"""Unit tests for codingame_client.contribution_manager.manager.CgContributionManager
   (`import_`/`commit`/`materialize_remote`/`rebase`/`merge_discard_local`/
   `merge_discard_server`/`revert`/`merge_start`/`merge_continue`/`merge_abort`), against a fake,
   duck-typed client (services.contribution, servlets.file_servlet, servlets.file_upload)--no real
   CgAsyncClient/network involved.

These are pure/local tests--no network--so they run under the default `pdm run test` invocation.
"""

from __future__ import annotations

import dataclasses
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


async def test_import_writes_identity_view_and_content_files(tmp_path: Path) -> None:
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

    last_committed = manager.load_last_committed()
    assert last_committed is not None
    last_view, last_snapshot = last_committed
    assert last_snapshot.cover_binary_hash == compute_content_hash(COVER_CONTENT)
    assert last_snapshot.contribution.last_version.statement_html is None
    assert last_snapshot.contribution.last_version.data.title == ""  # redacted
    assert (manager.last_committed_dir / "data" / "statement.cgmd").read_text() == "The statement\n"
    assert not (manager.last_committed_dir / "solution.py").exists()  # symlink never propagated
    assert last_view.data.title == "My Puzzle"

    assert manager.contribution_data_file.is_file()
    assert CgContributionView.load(manager.contribution_data_file) == view


async def test_import_with_no_cover_image_leaves_cover_hash_none(tmp_path: Path) -> None:
    data = _make_full_data(cover_binary_id=None)
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    assert not (tmp_path / "data" / "cover.png").exists()
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].cover_binary_hash is None


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


async def test_reimport_with_language_change_regenerates_symlink(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    assert (tmp_path / "solution.py").is_symlink()

    new_data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    await manager2.import_("handle-1")

    assert (tmp_path / "data" / "solution.src").read_text() == "class Main {}\n"
    assert not (tmp_path / "solution.py").exists()
    assert (tmp_path / "solution.java").is_symlink()


# --- commit ------------------------------------------------------------------------------


async def test_commit_requires_puzzle_type(tmp_path: Path) -> None:
    view = CgContributionView(data=CgContributionData(title="x"))
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(view)
    with pytest.raises(CgContributionManagerError):
        await manager.commit()


async def test_commit_requires_a_prior_import(tmp_path: Path) -> None:
    view = CgContributionView(puzzle_type="PUZZLE_INOUT", data=CgContributionData(title="x"))
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(view)
    with pytest.raises(NotImplementedError):
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

    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 4
    assert last_committed[1].cover_binary_hash == compute_content_hash(COVER_CONTENT)


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
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()

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
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].contribution.active_version == 4


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


# --- materialize_remote ---------------------------------------------------------------------


async def test_materialize_remote_reuses_cached_cover_when_binary_id_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    await manager.materialize_remote(manager.remote_dir)

    assert (manager.remote_dir / "data" / "statement.cgmd").read_text() == "The statement\n"
    assert (manager.remote_dir / "data" / "cover.png").read_bytes() == COVER_CONTENT
    assert file_servlet.calls == []


async def test_materialize_remote_downloads_when_binary_id_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"new-cover-bytes", content_type="image/png")

    await manager.materialize_remote(manager.remote_dir)

    assert (manager.remote_dir / "data" / "cover.png").read_bytes() == b"new-cover-bytes"
    assert file_servlet.calls == [666]


async def test_materialize_remote_raises_on_corrupted_last_committed_cover_cache(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (manager.last_committed_dir / "data" / "cover.png").write_bytes(b"tampered content")

    with pytest.raises(CgContributionManagerError):
        await manager.materialize_remote(manager.remote_dir)


async def test_materialize_remote_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()

    with pytest.raises(CgContributionManagerError):
        await manager.materialize_remote(manager.remote_dir)


async def test_materialize_remote_skips_rewrite_when_target_already_matches_fetched_version(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    await manager.materialize_remote(manager.remote_dir)  # version 3, populates .meta/remote/
    file_servlet.calls.clear()

    # Server reports a *different* cover_binary_id, but the *same* version number as what's
    # already cached in remote_dir--materialize_remote should trust that nothing changed and
    # skip the rewrite entirely (not even check the cover), rather than acting on the stale
    # (impossible in practice, but exercises the short-circuit condition precisely) binary ID.
    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=3)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"should-not-be-fetched", content_type="image/png")

    await manager.materialize_remote(manager.remote_dir)

    assert (manager.remote_dir / "data" / "cover.png").read_bytes() == COVER_CONTENT  # untouched
    assert file_servlet.calls == []


async def test_materialize_remote_reuses_targets_own_previously_cached_cover(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    other_cover = b"\x89PNG\x00other-cover-bytes"
    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=other_cover, content_type="image/png")
    await manager.materialize_remote(manager.remote_dir)  # version 4, binary_id 666, downloads once
    file_servlet.calls.clear()

    # Now the server moves on to version 5 but the cover_binary_id reverts to 666 (e.g. someone
    # reused an old image)--still different from last_committed's (555), but matching remote_dir's
    # *own* previously-cached 666--so it should be reused from there instead of downloaded again.
    newer_data = _make_full_data(cover_binary_id=666, statement="Newer statement")
    service.find_result = _make_contribution(newer_data, version=5)

    await manager.materialize_remote(manager.remote_dir)

    assert (manager.remote_dir / "data" / "cover.png").read_bytes() == other_cover
    assert (manager.remote_dir / "data" / "statement.cgmd").read_text() == "Newer statement\n"
    assert file_servlet.calls == []


async def test_materialize_remote_self_heals_when_targets_own_cover_cache_is_corrupted(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"original-666-bytes", content_type="image/png")
    await manager.materialize_remote(manager.remote_dir)
    (manager.remote_dir / "data" / "cover.png").write_bytes(b"tampered")

    newer_data = _make_full_data(cover_binary_id=666, statement="Newer statement")
    service.find_result = _make_contribution(newer_data, version=5)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"fresh-666-bytes", content_type="image/png")

    await manager.materialize_remote(manager.remote_dir)  # doesn't raise--just re-downloads

    assert (manager.remote_dir / "data" / "cover.png").read_bytes() == b"fresh-666-bytes"


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
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 4


async def test_rebase_reports_conflict_and_changes_nothing_when_both_diverged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    status = await manager.rebase()

    assert status == CgRebaseStatus.CONFLICT
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 3


async def test_rebase_up_to_date_even_with_local_edits_if_server_unchanged(tmp_path: Path) -> None:
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
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()

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


async def test_merge_discard_server_leaves_working_content_untouched(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    commit_data = await manager.merge_discard_server()

    assert commit_data.prev_version == 4
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 4


async def test_merge_discard_server_reuses_cover_when_binary_id_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(statement="Server edit")  # same cover_binary_id=555
    service.find_result = _make_contribution(new_data, version=4)

    await manager.merge_discard_server()

    assert file_servlet.calls == []
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].cover_binary_hash == compute_content_hash(COVER_CONTENT)


async def test_merge_discard_server_downloads_new_cover_when_binary_id_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"new-cover-bytes", content_type="image/png")

    commit_data = await manager.merge_discard_server()

    assert commit_data.cover_binary_hash == compute_content_hash(b"new-cover-bytes")
    assert (manager.last_committed_dir / "data" / "cover.png").read_bytes() == b"new-cover-bytes"
    assert (tmp_path / "data" / "cover.png").read_bytes() == COVER_CONTENT  # local working copy untouched


async def test_merge_discard_server_clears_cover_cache_when_binary_id_removed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(cover_binary_id=None)
    service.find_result = _make_contribution(new_data, version=4)

    commit_data = await manager.merge_discard_server()

    assert commit_data.cover_binary_hash is None
    assert not (manager.last_committed_dir / "data" / "cover.png").exists()


async def test_merge_discard_local_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()
    with pytest.raises(CgContributionManagerError):
        await manager.merge_discard_local()


async def test_merge_discard_server_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()
    with pytest.raises(CgContributionManagerError):
        await manager.merge_discard_server()


# --- revert --------------------------------------------------------------------------------


async def test_revert_discards_local_edits_without_network(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")
    (tmp_path / "data" / "constraints.cgmd").unlink()
    find_calls_before = service.find_call_count
    file_servlet.calls.clear()

    view = manager.revert()

    assert (tmp_path / "data" / "statement.cgmd").read_text() == "The statement\n"
    assert (tmp_path / "data" / "constraints.cgmd").read_text() == "1 <= N <= 100\n"
    assert view.data.title == "My Puzzle"
    assert service.find_call_count == find_calls_before
    assert file_servlet.calls == []
    assert (tmp_path / "solution.py").is_symlink()  # symlink regenerated


async def test_revert_requires_a_prior_import(tmp_path: Path) -> None:
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        manager.revert()


async def test_revert_raises_on_corrupted_cover_cache(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (manager.last_committed_dir / "data" / "cover.png").write_bytes(b"tampered")

    with pytest.raises(CgContributionManagerError):
        manager.revert()


async def test_revert_refuses_while_merge_in_progress(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    await manager.merge_start()
    with pytest.raises(CgContributionManagerError):
        manager.revert()


async def test_revert_preserves_identity_and_last_committed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    manager.revert()

    identity = manager.load_identity()
    assert identity is not None
    assert identity.contribution_handle == "handle-1"
    assert manager.load_last_committed() is not None


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
    assert not manager.merge_dir.exists()
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"  # untouched


async def test_merge_start_is_idempotent(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift

    first = await manager.merge_start()
    assert first.status == CgMergeStartStatus.STARTED

    (manager.merge_local_dir / "sentinel.txt").write_text("do not touch\n")
    second = await manager.merge_start()

    assert second.status == CgMergeStartStatus.ALREADY_IN_PROGRESS
    assert (manager.merge_local_dir / "sentinel.txt").is_file()  # untouched, not re-materialized


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
    assert manager.merge_in_progress


async def test_merge_start_leaves_local_only_change_untouched(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "data" / "statement.cgmd").write_text("Local edit\n")

    # An unrelated server-side change, so the merge machinery actually runs--otherwise a purely
    # local-only change, with the server unchanged, short-circuits to UP_TO_DATE (see
    # test_merge_start_reports_up_to_date_when_server_unchanged) before ever touching statement.cgmd.
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

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_start()

    assert "statement.cgmd" in result.text_conflicts
    content = (tmp_path / "data" / "statement.cgmd").read_text()
    assert "<<<<<<< local" in content
    assert "Local edit" in content
    assert "Server edit" in content
    assert ">>>>>>> remote" in content


async def test_merge_start_keeps_local_cover_on_binary_conflict(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    local_cover = b"\x89PNG\x00locally-changed-cover"
    remote_cover = b"\x89PNG\x00remote-changed-cover"
    (tmp_path / "data" / "cover.png").write_bytes(local_cover)

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=remote_cover, content_type="image/png")

    result = await manager.merge_start()

    assert "cover.png" in result.binary_conflicts
    assert (tmp_path / "data" / "cover.png").read_bytes() == local_cover  # kept local


async def test_merge_start_removes_solution_symlink(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    service.find_result = _make_contribution(data, version=4)  # a real merge needs server drift
    assert (tmp_path / "solution.py").is_symlink()

    await manager.merge_start()

    assert not (tmp_path / "solution.py").exists()


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
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    await manager.merge_start()

    (tmp_path / "data" / "statement.cgmd").write_text("Resolved by hand\n")
    manager.merge_continue()

    assert not manager.merge_in_progress
    assert not manager.merge_dir.exists()
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 4
    assert (tmp_path / "solution.py").is_symlink()  # regenerated at continue time


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
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)
    await manager.merge_start()
    assert "statement.cgmd" in (tmp_path / "data" / "statement.cgmd").read_text() or True  # sanity: file exists

    manager.merge_abort()

    assert not manager.merge_in_progress
    assert (tmp_path / "data" / "statement.cgmd").read_text() == "Local edit\n"  # restored to pre-merge local snapshot
    assert (tmp_path / "solution.py").is_symlink()
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed[1].prev_version == 3  # untouched by the aborted merge
