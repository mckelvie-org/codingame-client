"""
Async FeaturedEvent service endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from json_data_types import JsonDict

from ....common.protocol.featured_event import CgClashSlot, CgFeaturedEvent
from ....common.raw_client import CgAuthenticationError
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncFeaturedEventServiceHelper(CgAsyncServiceHelper["CgAsyncFeaturedEventService"]):
    """Helper methods for CgAsyncFeaturedEventService. Currently empty."""


class CgAsyncFeaturedEventService(CgAsyncService):
    """Async FeaturedEvent service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "FeaturedEvent")
        self.helper = CgAsyncFeaturedEventServiceHelper(self)

    async def find_upcoming_and_ongoing_featured_events(
                self,
                codingamer_id: int | None = None,
            ) -> list[CgFeaturedEvent]:
        """Find upcoming and ongoing site-wide featured events (e.g. scheduled Clash of Code or
           puzzle events), and whether the given codingamer is registered for each.

        Args:
            codingamer_id: The codingamer to check registration status for. If not provided,
                           defaults to the logged-in codingamer's ID.

        Returns:
            A list of CgFeaturedEvent objects.

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
        raw_events = await self.service_request_to_list(
                "findUpcomingAndOngoingFeaturedEvents", [codingamer_id])
        return CgFeaturedEvent.from_list(cast(list[JsonDict], raw_events))

    async def is_codingamer_auto_registered(
                self,
                codingamer_id: int | None = None,
            ) -> bool:
        """Check whether a codingamer is auto-registered for featured events (e.g. an account
           setting that opts them into upcoming Clash of Code/puzzle events automatically).

           This is a personal setting: passing a `codingamer_id` other than your own logged-in
           ID is rejected by the server with a 403 (`invalidUser: You are not authorized to
           perform this operation`).

        Args:
            codingamer_id: The codingamer to check. Must be the logged-in codingamer's own ID
                           (server-enforced; see above). If not provided, defaults to the
                           logged-in codingamer's ID.

        Returns:
            True if the codingamer is auto-registered, False otherwise.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login, or if
                `codingamer_id` is not provided and no codingamer ID can be resolved from the
                session's credentials.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx (e.g. 403 if `codingamer_id` is not your own), or
                if the decoded content is not a bool.
        """
        if codingamer_id is None:
            await self.require_authenticate()
            codingamer_id = self.client.codingamer_id
            if codingamer_id is None:
                raise CgAuthenticationError()
        result = await self.service_request("isCodingamerAutoRegistered", [codingamer_id])
        return cast(bool, result)

    async def find_new_featured_event_count(
                self,
                since: datetime | None = None,
            ) -> int:
        """Count featured events published since a given point in time.

           `since` is sent to the server as a bare epoch-millis integer, like every other
           epoch-millis argument in this API. CodinGame's own web client has been observed
           sending it as a quoted (string-encoded) number instead--both encodings were tested
           empirically and the server accepts either, so the simpler bare-int form is used here.
           Also confirmed empirically: passing a timestamp before a known featured event's
           `publish_time` counts it towards the result; passing one at or after does not.

           This value has not been observed being returned by any other endpoint (e.g. as a
           stored "last checked" marker)--callers are expected to track their own reference
           point (e.g. "now", or whenever they last called this).

        Args:
            since: Count featured events published after this point in time. If not provided,
                   defaults to now (which will always yield 0--callers interested in a nonzero
                   count should track their own reference point, e.g. the last time they called
                   this). Naive datetimes are interpreted as local time (matching Python's own
                   `datetime.timestamp()` behavior).

        Returns:
            The number of featured events published since `since`.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not an int.
        """
        if since is None:
            since = datetime.now(timezone.utc)
        since_ms = int(since.timestamp() * 1000)
        result = await self.service_request("findNewFeaturedEventCount", [since_ms])
        return cast(int, result)

    async def find_clash_slots(
                self,
                featured_event_id: int,
            ) -> list[CgClashSlot]:
        """Find the individual scheduled Clash of Code slots belonging to a featured event.

           `featured_event_id` is `CgFeaturedEvent.id` (not `CgFeaturedEvent.handle`)--e.g. for
           a `CgFeaturedEvent` with `handle == "4725bc5cbd6926ec69e31fd542cd0b354738"`, `id`
           is `4725`, the (coincidental-looking) numeric prefix of the handle.

        Args:
            featured_event_id: The `id` of a "CLASH_OF_CODE"-type `CgFeaturedEvent`.

        Returns:
            A list of CgClashSlot objects.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        raw_slots = await self.service_request_to_list("findClashSlots", [featured_event_id])
        return CgClashSlot.from_list(cast(list[JsonDict], raw_slots))

    async def find_by_handle(
                self,
                handle: str,
            ) -> CgFeaturedEvent:
        """Find a featured event by its opaque handle.

           Unlike findUpcomingAndOngoingFeaturedEvents, this endpoint has no codingamer context,
           so the returned `CgFeaturedEvent.registered` is always None here.

        Args:
            handle: The featured event's opaque handle (`CgFeaturedEvent.handle`).

        Returns:
            A CgFeaturedEvent object.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a dict.
        """
        raw_event = await self.service_request_to_dict("findByHandle", [handle])
        return CgFeaturedEvent.from_dict(raw_event)
