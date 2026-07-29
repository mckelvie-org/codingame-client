"""Unit tests for codingame_client.contribution_manager.manager.CgContributionManager
   (`import_`/`commit`/`materialize_base`/`materialize_remote`/`rebase`/`merge_discard_local`/
   `merge_discard_server`), against a fake, duck-typed client (services.contribution,
   servlets.file_servlet, servlets.file_upload)--no real CgAsyncClient/network involved.

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
from codingame_client.contribution_manager.manager import CgContributionManager, CgContributionManagerError, CgRebaseStatus
from codingame_client.contribution_manager.schema import CgContributionWorkingDir

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


async def test_import_writes_sidecar_files_and_manifest(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    working = await manager.import_("handle-1")

    assert (tmp_path / "statement.cgmd").read_text() == "The statement\n"
    assert (tmp_path / "input_description.cgmd").read_text() == "Input desc\n"
    assert (tmp_path / "output_description.cgmd").read_text() == "Output desc\n"
    assert (tmp_path / "constraints.cgmd").read_text() == "1 <= N <= 100\n"
    assert (tmp_path / "stub_generator.cgstub").read_text() == "read int N;\n"
    assert (tmp_path / "cover.png").read_bytes() == COVER_CONTENT
    assert working.solution_file == "solution.py"
    assert (tmp_path / "solution.py").read_text() == "print('hi')\n"
    assert (tmp_path / "tests" / "01").is_dir()

    assert working.puzzle_type == "PUZZLE_INOUT"
    assert working.draft is True
    assert working.ready_for_moderation is False
    assert working.data.statement is None  # working copy keeps the sidecar-backed fields empty
    assert working.data.title == "My Puzzle"

    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.cover_binary_hash == compute_content_hash(COVER_CONTENT)
    assert last_committed.contribution.last_version.statement_html is None
    assert manager.last_committed_cover_file.read_bytes() == COVER_CONTENT

    assert manager.contribution_file.is_file()
    assert CgContributionWorkingDir.load(manager.contribution_file) == working


async def test_import_creates_target_dir_when_only_a_cover_image_is_set(tmp_path: Path) -> None:
    """Regression test: if every sidecar field (statement, input/output description, constraints,
       stub_generator) is None, _write_sidecar's None branch never creates contribution_dir--the
       cover image write must not depend on one of those having run first."""
    data = CgContributionData(title="Cover Only", cover_binary_id=555)
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    target = tmp_path / "fresh-target"
    assert not target.exists()
    manager = CgContributionManager(target, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    assert (target / "cover.png").read_bytes() == COVER_CONTENT
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.cover_binary_hash == compute_content_hash(COVER_CONTENT)


async def test_import_with_no_cover_image_leaves_cover_hash_none(tmp_path: Path) -> None:
    data = _make_full_data(cover_binary_id=None)
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]

    await manager.import_("handle-1")

    assert not (tmp_path / "cover.png").exists()
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.cover_binary_hash is None
    assert not manager.last_committed_cover_file.exists()


async def test_reimport_preserves_existing_solution_file_pointer(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    working = await manager.import_("handle-1")
    working.solution_file = "custom/solution.py"
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "solution.py").write_text("stale\n")
    manager.save(working)

    await manager.import_("handle-1")

    reloaded = manager.load()
    assert reloaded.solution_file == "custom/solution.py"
    assert (tmp_path / "custom" / "solution.py").read_text() == "print('hi')\n"


async def test_reimport_regenerates_and_deletes_old_solution_file_when_language_changes_inside_dir(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    assert (tmp_path / "solution.py").is_file()

    new_data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    working = await manager2.import_("handle-1")

    assert working.solution_file == "solution.java"
    assert (tmp_path / "solution.java").read_text() == "class Main {}\n"
    assert not (tmp_path / "solution.py").exists()  # old file (inside contribution_dir) removed


async def test_reimport_regenerates_symlinked_solution_file_when_language_changes(tmp_path: Path) -> None:
    """solution_file is always inside contribution_dir; projecting the real source elsewhere is
       done via a symlink placed there instead--regenerating on a language change must only ever
       remove the symlink itself, never the file it points to."""
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    real_target = tmp_path.parent / "real-solution.py"
    real_target.write_text("print('hi')\n")
    (tmp_path / "solution.py").unlink()
    (tmp_path / "solution.py").symlink_to(real_target)

    new_data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    reloaded = await manager2.import_("handle-1")

    assert reloaded.solution_file == "solution.java"
    assert (tmp_path / "solution.java").read_text() == "class Main {}\n"
    assert not (tmp_path / "solution.py").exists()  # symlink removed
    assert real_target.is_file()  # the file it pointed to is untouched
    assert real_target.read_text() == "print('hi')\n"


async def test_reimport_keeps_solution_file_when_language_and_extension_still_match(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(solution_language="Python3", solution="print('updated')")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    working = await manager2.import_("handle-1")

    assert working.solution_file == "solution.py"
    assert (tmp_path / "solution.py").read_text() == "print('updated')\n"


async def test_reimport_overwrites_in_place_never_deletes_symlink_when_language_unchanged(tmp_path: Path) -> None:
    """The alternative (non-recommended, but supported) symlink pattern--solution_file itself is
       a symlink inside contribution_dir pointing to a real file elsewhere--depends entirely on
       this: as long as the language doesn't change, new content must always be written via
       overwrite-in-place (following the symlink), never delete-then-recreate (which would sever
       the link and leave a plain file behind instead)."""
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    real_target = tmp_path.parent / "real-solution.py"
    real_target.write_text("print('hi')\n")
    (tmp_path / "solution.py").unlink()
    (tmp_path / "solution.py").symlink_to(real_target)

    new_data = _make_full_data(solution_language="Python3", solution="print('updated')")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    working = await manager2.import_("handle-1")

    assert working.solution_file == "solution.py"
    assert (tmp_path / "solution.py").is_symlink()  # still a symlink--not replaced with a plain file
    assert (tmp_path / "solution.py").resolve() == real_target.resolve()
    assert real_target.read_text() == "print('updated')\n"  # the real file got the new content


async def test_reimport_keeps_solution_file_when_prior_extension_is_unrecognized(tmp_path: Path) -> None:
    """Can't confirm a mismatch if the *prior* file's extension isn't a known language at
       all--don't force a change without positive evidence."""
    data = _make_full_data(solution_language="Python3")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    working = await manager.import_("handle-1")
    (tmp_path / "solution.py").unlink()
    (tmp_path / "solution.custom").write_text("print('hi')\n")
    working.solution_file = "solution.custom"
    manager.save(working)

    new_data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution2 = _make_contribution(new_data, version=4)
    client2, _, _, _ = _make_fake_client(contribution2)
    manager2 = CgContributionManager(tmp_path, client2)  # type: ignore[arg-type]

    reloaded = await manager2.import_("handle-1")

    assert reloaded.solution_file == "solution.custom"
    assert (tmp_path / "solution.custom").read_text() == "class Main {}\n"


async def test_revert_regenerates_solution_file_when_base_language_differs(tmp_path: Path) -> None:
    data = _make_full_data(solution_language="Java", solution="class Main {}")
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    assert (tmp_path / "solution.java").is_file()
    # Simulate a local edit that switched the working solution to Python (with a matching
    # working_data.solution_language, as a real edit would do), while last_committed/ still
    # records Java as the base.
    (tmp_path / "solution.java").unlink()
    (tmp_path / "solution.py").write_text("print('local')\n")
    working = manager.load()
    working.solution_file = "solution.py"
    working.data = dataclasses.replace(working.data, solution_language="Python3")
    manager.save(working)

    reverted = manager.revert()

    assert reverted.solution_file == "solution.java"
    assert (tmp_path / "solution.java").read_text() == "class Main {}\n"
    assert not (tmp_path / "solution.py").exists()


# --- commit ------------------------------------------------------------------------------


async def test_commit_requires_puzzle_type(tmp_path: Path) -> None:
    working = CgContributionWorkingDir(data=CgContributionData(title="x"))
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(working)
    with pytest.raises(CgContributionManagerError):
        await manager.commit()


async def test_commit_requires_a_prior_import(tmp_path: Path) -> None:
    working = CgContributionWorkingDir(puzzle_type="PUZZLE_INOUT", data=CgContributionData(title="x"))
    manager = CgContributionManager(tmp_path, object())  # type: ignore[arg-type]
    manager.save(working)
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
    assert last_committed.contribution.last_version.version == 4
    assert last_committed.cover_binary_hash == compute_content_hash(COVER_CONTENT)


async def test_commit_reuploads_cover_when_content_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    updated = _make_contribution(data, version=4)
    client, service, file_upload, _ = _make_fake_client(contribution, update_result=updated, new_upload_id=777)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "cover.png").write_bytes(b"changed-bytes")

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
    (tmp_path / "statement.cgmd").write_text("Edited statement\n")

    await manager.commit()

    submitted = service.update_calls[0]["contribution_data"]
    assert submitted.statement == "Edited statement\n"
    assert [tc.title for tc in submitted.test_cases] == ["Case A", "Case A"]
    assert submitted.solution == "print('hi')\n"


async def test_commit_passes_working_dir_puzzle_type_and_flags(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data, draft=False, ready_for_moderation=True)
    updated = _make_contribution(data, version=4)
    client, service, _, _ = _make_fake_client(contribution, update_result=updated)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    working = await manager.import_("handle-1")
    assert working.draft is False
    assert working.ready_for_moderation is True

    await manager.commit()

    call = service.update_calls[0]
    assert call["puzzle_type"] == "PUZZLE_INOUT"
    assert call["draft"] is False
    assert call["ready_for_moderation"] is True
    assert call["prev_version"] == 3


# --- active_version refresh (updateContribution's response can report it stale) -----------


async def test_commit_refreshes_stale_active_version_via_find_contribution(tmp_path: Path) -> None:
    """updateContribution's response can report active_version lagging one behind
       last_version.version (confirmed live)--commit() must re-fetch via findContribution rather
       than caching the stale value."""
    data = _make_full_data()
    contribution = _make_contribution(data)  # version=3, active_version=3
    stale_update_result = dataclasses.replace(_make_contribution(data, version=4), active_version=3)
    client, service, _, _ = _make_fake_client(contribution, update_result=stale_update_result)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    # Simulate the server having caught up by the time commit()'s refresh poll re-fetches it.
    service.find_result = _make_contribution(data, version=4)  # active_version=4

    result = await manager.commit()

    assert result.active_version == 4
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.contribution.active_version == 4


async def test_commit_gives_up_refreshing_after_max_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If active_version never catches up, commit() must still return rather than hang forever."""
    async def no_sleep(seconds: float) -> None:
        return None
    monkeypatch.setattr("codingame_client.contribution_manager.manager.asyncio.sleep", no_sleep)

    data = _make_full_data()
    contribution = _make_contribution(data)  # version=3, active_version=3
    stale_update_result = dataclasses.replace(_make_contribution(data, version=4), active_version=3)
    client, service, _, _ = _make_fake_client(contribution, update_result=stale_update_result)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    # find_contribution keeps reporting the same stale active_version forever.
    service.find_result = stale_update_result

    result = await manager.commit()

    assert result.active_version == 3  # gave up, still stale--but didn't hang or raise


# --- materialize_base / materialize_remote -------------------------------------------------


async def test_materialize_base_reproduces_last_committed_content_without_network(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()  # only care about calls made by materialize_base itself

    base_dir = tmp_path.parent / "base"
    manager.materialize_base(base_dir)

    assert (base_dir / "statement.cgmd").read_text() == "The statement\n"
    assert (base_dir / "cover.png").read_bytes() == COVER_CONTENT
    assert file_servlet.calls == []  # no network access at all


async def test_materialize_base_raises_on_corrupted_cover_cache(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    manager.last_committed_cover_file.write_bytes(b"tampered content")

    with pytest.raises(CgContributionManagerError):
        manager.materialize_base(tmp_path.parent / "base")


async def test_materialize_base_raises_on_missing_cover_cache(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    manager.last_committed_cover_file.unlink()

    with pytest.raises(CgContributionManagerError):
        manager.materialize_base(tmp_path.parent / "base")


# --- revert ------------------------------------------------------------------------------


async def test_revert_discards_local_edits_without_network(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "statement.cgmd").write_text("Local edit\n")
    (tmp_path / "constraints.cgmd").unlink()
    find_calls_before = service.find_call_count
    file_servlet.calls.clear()

    working = manager.revert()

    assert (tmp_path / "statement.cgmd").read_text() == "The statement\n"
    assert (tmp_path / "constraints.cgmd").read_text() == "1 <= N <= 100\n"
    assert working.data.title == "My Puzzle"
    assert service.find_call_count == find_calls_before  # no network access
    assert file_servlet.calls == []


async def test_revert_preserves_existing_solution_file_pointer(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    working = await manager.import_("handle-1")
    working.solution_file = "custom/solution.py"
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "solution.py").write_text("edited\n")
    manager.save(working)

    reverted = manager.revert()

    assert reverted.solution_file == "custom/solution.py"
    assert (tmp_path / "custom" / "solution.py").read_text() == "print('hi')\n"


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
    manager.last_committed_cover_file.write_bytes(b"tampered")

    with pytest.raises(CgContributionManagerError):
        manager.revert()


async def test_materialize_remote_reuses_cached_cover_when_binary_id_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    remote_dir = tmp_path.parent / "remote"
    await manager.materialize_remote(remote_dir)

    assert (remote_dir / "cover.png").read_bytes() == COVER_CONTENT
    assert file_servlet.calls == []  # reused the cached bytes, no download


async def test_materialize_remote_downloads_when_binary_id_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"new-cover-bytes", content_type="image/png")

    remote_dir = tmp_path.parent / "remote"
    await manager.materialize_remote(remote_dir)

    assert (remote_dir / "cover.png").read_bytes() == b"new-cover-bytes"
    assert file_servlet.calls == [666]


# --- rebase --------------------------------------------------------------------------------


async def test_rebase_up_to_date_when_server_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    status = await manager.rebase()

    assert status == CgRebaseStatus.UP_TO_DATE
    assert (tmp_path / "statement.cgmd").read_text() == "The statement\n"  # untouched


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
    assert (tmp_path / "statement.cgmd").read_text() == "Updated on server\n"
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.prev_version == 4


async def test_rebase_reports_conflict_and_changes_nothing_when_both_diverged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    (tmp_path / "statement.cgmd").write_text("Local edit\n")
    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    status = await manager.rebase()

    assert status == CgRebaseStatus.CONFLICT
    assert (tmp_path / "statement.cgmd").read_text() == "Local edit\n"  # untouched
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.prev_version == 3  # untouched


async def test_rebase_up_to_date_even_with_local_edits_if_server_unchanged(tmp_path: Path) -> None:
    """Local dirtiness alone is not rebase's concern--only server drift is."""
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, _, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "statement.cgmd").write_text("Local edit\n")

    status = await manager.rebase()

    assert status == CgRebaseStatus.UP_TO_DATE
    assert (tmp_path / "statement.cgmd").read_text() == "Local edit\n"  # untouched


# --- merge_discard_local / merge_discard_server --------------------------------------------


async def test_merge_discard_local_always_overwrites(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "statement.cgmd").write_text("Local edit\n")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    await manager.merge_discard_local()

    assert (tmp_path / "statement.cgmd").read_text() == "Server edit\n"


async def test_merge_discard_server_leaves_working_content_untouched(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    (tmp_path / "statement.cgmd").write_text("Local edit\n")

    new_data = _make_full_data(statement="Server edit")
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_discard_server()

    assert result.prev_version == 4
    assert (tmp_path / "statement.cgmd").read_text() == "Local edit\n"  # untouched
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.prev_version == 4


async def test_merge_discard_server_leaves_cover_cache_untouched_when_binary_id_unchanged(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    file_servlet.calls.clear()

    new_data = _make_full_data(statement="Server edit")  # same cover_binary_id=555
    service.find_result = _make_contribution(new_data, version=4)

    await manager.merge_discard_server()

    assert file_servlet.calls == []  # cover untouched/not re-downloaded
    last_committed = manager.load_last_committed()
    assert last_committed is not None
    assert last_committed.cover_binary_hash == compute_content_hash(COVER_CONTENT)


async def test_merge_discard_server_downloads_new_cover_when_binary_id_changed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, file_servlet = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")

    new_data = _make_full_data(cover_binary_id=666)
    service.find_result = _make_contribution(new_data, version=4)
    file_servlet.result = CgDownloadFileResult.create(id=666, content=b"new-cover-bytes", content_type="image/png")

    result = await manager.merge_discard_server()

    assert result.cover_binary_hash == compute_content_hash(b"new-cover-bytes")
    assert manager.last_committed_cover_file.read_bytes() == b"new-cover-bytes"
    assert (tmp_path / "cover.png").read_bytes() == COVER_CONTENT  # local working copy untouched


async def test_merge_discard_server_clears_cover_cache_when_binary_id_removed(tmp_path: Path) -> None:
    data = _make_full_data()
    contribution = _make_contribution(data)
    client, service, _, _ = _make_fake_client(contribution)
    manager = CgContributionManager(tmp_path, client)  # type: ignore[arg-type]
    await manager.import_("handle-1")
    assert manager.last_committed_cover_file.is_file()

    new_data = _make_full_data(cover_binary_id=None)
    service.find_result = _make_contribution(new_data, version=4)

    result = await manager.merge_discard_server()

    assert result.cover_binary_hash is None
    assert not manager.last_committed_cover_file.exists()
