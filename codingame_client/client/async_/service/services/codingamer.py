"""
Async CodinGamer service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from json_data_types import JsonDict

from ....common.protocol.codingamer import CgCodingamePointsStats, CgCodingamer, CgCodingamerFollower
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncCodingamerService(CgAsyncService):
    """Async Codingamer service endpoint."""
    
    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "CodinGamer")

    async def find_codingame_points_stats_by_handle(
                self,
                handle: str,
            ) -> CgCodingamePointsStats:
        """Find a codingamer's points/ranking stats by their opaque public handle.

        Args:
            handle: The codingamer's opaque public handle string (not their numeric ID).

        Returns:
            A CgCodingamePointsStats object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_stats = await self.service_request_to_dict(
                "findCodingamePointsStatsByHandle", [handle])
        return CgCodingamePointsStats.from_dict(raw_stats)

    async def find_codingamer_public_informations(
                self,
                codingamer_id: int | None = None,
            ) -> CgCodingamer:
        """Find a codingamer's public profile information by their numeric ID.

           This is a genuinely public endpoint--no login is required when `codingamer_id` is
           explicitly provided. A login is only required to resolve the default
           `codingamer_id` when one is not provided.

        Args:
            codingamer_id: The codingamer's numeric ID. If not provided, defaults to the
                           logged-in codingamer's ID.

        Returns:
            A CgCodingamer object.

        Raises:
            CgAuthenticationError:
                If `codingamer_id` is not provided and no codingamer ID can be resolved from
                the session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_codingamer = await self.service_request_to_dict(
                "findCodinGamerPublicInformations", [codingamer_id], require_login=False)
        return CgCodingamer.from_dict(raw_codingamer)

    async def find_followers(
                self,
                codingamer_id: int | None = None,
                current_codingamer_id: int | None = None,
                arg3: dict[str, Any] | None = None,
            ) -> list[CgCodingamerFollower]:
        """Find the followers of a codingamer.

           Empirically, `current_codingamer_id` is not a free "viewpoint" parameter: the server
           rejects the call with a 422 unless it equals the logged-in codingamer's own ID, even
           when `codingamer_id` refers to a different codingamer. It appears to exist purely so
           the server can compute `is_follower`/`is_following` on each result relative to the
           logged-in codingamer, rather than relative to `codingamer_id`.

           `arg3`'s purpose is unknown. Passing a scalar (int, str, bool) causes a 422; only
           `None` and `{}` have been observed to succeed--possibly reserved for future
           pagination/filtering parameters.

        Args:
            codingamer_id: The codingamer whose followers to list. Defaults to the logged-in
                           codingamer's ID.
            current_codingamer_id: Must equal the logged-in codingamer's ID (server-enforced;
                           see above). Defaults to the logged-in codingamer's ID.
            arg3:          Third positional argument to the underlying findFollowers API call.
                           Purpose unknown; defaults to None.

        Returns:
            A list of CgCodingamerFollower objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if either ID
                is not provided and cannot be resolved from the session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        await self.require_authenticate()
        own_id = self.client.codingamer_id
        if codingamer_id is None:
            codingamer_id = own_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        if current_codingamer_id is None:
            current_codingamer_id = own_id
            if current_codingamer_id is None:
                raise CgAuthenticationError()
        raw_followers = await self.service_request_to_list(
                "findFollowers", [codingamer_id, current_codingamer_id, arg3])
        return CgCodingamerFollower.from_list(cast(list[JsonDict], raw_followers))

    async def find_following(
                self,
                codingamer_id: int | None = None,
                current_codingamer_id: int | None = None,
            ) -> list[CgCodingamerFollower]:
        """Find the codingamers that a codingamer is following.

           Same `codingamer_id`/`current_codingamer_id` semantics as `find_followers` (see its
           docstring)--`current_codingamer_id` must equal the logged-in codingamer's own ID, and
           serves only to compute `is_follower`/`is_following` from the logged-in codingamer's
           perspective. Unlike `find_followers`, there is no third (unknown) argument.

        Args:
            codingamer_id: The codingamer whose followees to list. Defaults to the logged-in
                           codingamer's ID.
            current_codingamer_id: Must equal the logged-in codingamer's ID (server-enforced).
                           Defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgCodingamerFollower objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if either ID
                is not provided and cannot be resolved from the session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        await self.require_authenticate()
        own_id = self.client.codingamer_id
        if codingamer_id is None:
            codingamer_id = own_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        if current_codingamer_id is None:
            current_codingamer_id = own_id
            if current_codingamer_id is None:
                raise CgAuthenticationError()
        raw_following = await self.service_request_to_list(
                "findFollowing", [codingamer_id, current_codingamer_id])
        return CgCodingamerFollower.from_list(cast(list[JsonDict], raw_following))

    async def find_follower_ids(
                self,
                codingamer_id: int | None = None,
            ) -> list[int]:
        """Find the numeric IDs of a codingamer's followers.

        Args:
            codingamer_id: The codingamer whose follower IDs to list. Defaults to the logged-in
                           codingamer's ID.

        Returns:
            A list of numeric codingamer IDs.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_ids = await self.service_request_to_list("findFollowerIds", [codingamer_id])
        return cast(list[int], raw_ids)

    async def find_following_ids(
                self,
                codingamer_id: int | None = None,
            ) -> list[int]:
        """Find the numeric IDs of the codingamers that a codingamer is following.

        Args:
            codingamer_id: The codingamer whose followee IDs to list. Defaults to the logged-in
                           codingamer's ID.

        Returns:
            A list of numeric codingamer IDs.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        raw_ids = await self.service_request_to_list("findFollowingIds", [codingamer_id])
        return cast(list[int], raw_ids)
