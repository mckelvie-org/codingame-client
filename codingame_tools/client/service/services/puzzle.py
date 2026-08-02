"""
Async Puzzle service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from json_data_types import JsonData, JsonDict

from ...common.protocol.last_activities import CgLastActivityPuzzle
from ...common.protocol.puzzle import (
    CgFollowingPuzzleProgress,
    CgGeneratedPuzzleSession,
    CgPuzzleMinimalProgress,
    CgPuzzleOfTheWeek,
    CgSolvedPuzzlesByLanguage,
)
from ...common.raw_client import CgAuthenticationError
from ..cg_service import CgService, CgServiceHelper

if TYPE_CHECKING:
    from ...client import CgClient


class CgPuzzleServiceHelper(CgServiceHelper["CgPuzzleService"]):
    """Helper methods for CgPuzzleService. Currently empty."""


class CgPuzzleService(CgService):
    """Async Puzzle service endpoint."""

    def __init__(self, client: CgClient) -> None:
        super().__init__(client, "Puzzle")
        self.helper = CgPuzzleServiceHelper(self)

    async def count_solved_puzzles_by_programming_language(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgSolvedPuzzlesByLanguage]:
        """Count a codingamer's solved puzzles, broken down by programming language.

        Args:
            codingamer_id: The codingamer whose solved-puzzle counts to list. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgSolvedPuzzlesByLanguage objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_counts = await self.service_request_to_list(
                "countSolvedPuzzlesByProgrammingLanguage", [codingamer_id])
        return CgSolvedPuzzlesByLanguage.from_list(cast(list[JsonDict], raw_counts))

    async def find_puzzle_of_the_week(self) -> CgPuzzleOfTheWeek:
        """Find the current puzzle of the week.

        Returns:
            A CgPuzzleOfTheWeek object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_puzzle = await self.service_request_to_dict("findPuzzleOfTheWeek")
        return CgPuzzleOfTheWeek.from_dict(raw_puzzle)

    async def find_all_minimal_progress(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgPuzzleMinimalProgress]:
        """Find a codingamer's minimal progress summary for every puzzle they have some
           relationship to (not just solved/attempted ones--see `CgPuzzleMinimalProgress`).

        Args:
            codingamer_id: The codingamer whose puzzle progress to list. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgPuzzleMinimalProgress objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_progress = await self.service_request_to_list("findAllMinimalProgress", [codingamer_id])
        return CgPuzzleMinimalProgress.from_list(cast(list[JsonDict], raw_progress))

    async def find_progress_by_ids(
                self,
                puzzle_ids: list[int],
                codingamer_id: int | None = None,
                arg3: int = 2,
            ) -> list[CgLastActivityPuzzle]:
        """Find a codingamer's progress summary for a specific set of puzzles, by puzzle ID.

           `arg3`'s purpose is unclear: only `1` and `2` have been observed to return real data
           (both return the identical full result set, in the same order); every other value
           tried (0, 3, 4, 5, 6, 10, 100) silently returned an empty list rather than erroring.
           Defaults to 2, matching observed real usage.

        Args:
            puzzle_ids:    Numeric puzzle IDs to look up (e.g. `CgLastActivityPuzzle.id`,
                           `CgPuzzleMinimalProgress.id`).
            codingamer_id: The codingamer whose progress to look up. If not provided, defaults
                           to the logged-in codingamer's ID.
            arg3:          Third positional argument to the underlying findProgressByIds API
                           call. Purpose unclear; see above. Defaults to 2.

        Returns:
            A list of CgLastActivityPuzzle objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_progress = await self.service_request_to_list(
                "findProgressByIds", cast(list[JsonData], [puzzle_ids, codingamer_id, arg3]))
        return CgLastActivityPuzzle.from_list(cast(list[JsonDict], raw_progress))

    async def find_best_following_progress(
                self,
                puzzle_id: int,
                codingamer_id: int | None = None,
            ) -> list[CgFollowingPuzzleProgress]:
        """Find the best progress on a given puzzle among the codingamers a codingamer follows.

           Returns an empty list if none of the followed codingamer(s) have attempted the
           puzzle. Only a single followed codingamer has been observed in testing, so it's
           unconfirmed whether more than one entry can be returned, or how "best" is determined
           among them--see `CgFollowingPuzzleProgress`.

        Args:
            puzzle_id:     Numeric ID of the puzzle to check.
            codingamer_id: The codingamer whose followees to check. If not provided, defaults
                           to the logged-in codingamer's ID.

        Returns:
            A list of CgFollowingPuzzleProgress objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_progress = await self.service_request_to_list(
                "findBestFollowingProgress", [codingamer_id, puzzle_id])
        return CgFollowingPuzzleProgress.from_list(cast(list[JsonDict], raw_progress))

    async def find_progress_by_pretty_id(
                self,
                pretty_id: str,
                codingamer_id: int | None = None,
            ) -> CgLastActivityPuzzle:
        """Find a codingamer's progress summary for a single puzzle, by its pretty ID (the
           displayed puzzle title, lowercased with spaces replaced by hyphens--e.g.
           "literary-alfabet-soupe" for "Literary Alfabet Soupe").

           The richest of the three findProgress* methods: uniquely among them, this one also
           populates `linked_achievements`/`moderators`/`statement`/`title_map`.

        Args:
            pretty_id:     The puzzle's pretty ID (see `CgLastActivityPuzzle.pretty_id`).
            codingamer_id: The codingamer whose progress to look up. If not provided, defaults
                           to the logged-in codingamer's ID.

        Returns:
            A CgLastActivityPuzzle object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_puzzle = await self.service_request_to_dict(
                "findProgressByPrettyId", [pretty_id, codingamer_id])
        return CgLastActivityPuzzle.from_dict(raw_puzzle)

    async def generate_session_from_puzzle_pretty_id(
                self,
                puzzle_pretty_id: str,
                codingamer_id: int | None = None,
                arg3: bool = False,
            ) -> str:
        """Get (or create) the codingamer's test session handle for a puzzle, by the puzzle's
           pretty ID (e.g. "literary-alfabet-soupe"--see `CgTestSessionPuzzle.pretty_id`).

           This is the API that resolves "which puzzle" into "which test session" before calling
           `TestSession/startTestSession`--i.e. the entry point for solving a puzzle by pretty ID
           rather than already having a `test_session_handle` in hand (e.g. from
           `CgLastActivityPuzzle`). Confirmed live (2026-07-30) to return the *same* handle across
           repeated calls for the same codingamer/puzzle--i.e. a per-user singleton test session,
           safely reusable/cacheable rather than needing to be re-derived on every use.

           `arg3`'s purpose is unknown; only observed as `False`.

        Args:
            puzzle_pretty_id: The puzzle's pretty ID/slug.
            codingamer_id:    The codingamer to get/create the session for. If not provided,
                               defaults to the logged-in codingamer's ID.
            arg3:              Third positional argument to the underlying API call. Purpose
                               unknown; defaults to False.

        Returns:
            The test session handle (see `CgTestSessionService.start_test_session`).

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_result = await self.service_request_to_dict(
                "generateSessionFromPuzzlePrettyId", [codingamer_id, puzzle_pretty_id, arg3])
        return CgGeneratedPuzzleSession.from_dict(raw_result).handle
