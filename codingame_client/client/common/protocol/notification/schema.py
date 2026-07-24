"""
JSON-serializable dataclasses for the findUnseenNotifications and findUnreadNotifications Codingame API methods.

Both methods return a bare JSON array of notification objects (not wrapped in an envelope object), so
there is no dedicated "response" dataclass here--callers should use `CgNotification.from_list(raw_list)`
to parse the array.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .....common.dataclass_wizard_x import Alias, CatchAll, CgEpochMillis, JSONWizardX

CgNotificationType = str
"""The specific notification type discriminator, e.g. "new-comment", "following". Determines the shape of
   `CgNotification.data`, if present. Only a couple of values have been observed so far, so this is
   left as a plain string rather than an enum pending broader coverage."""

CgNotificationTypeGroup = str
"""The broad category a notification type belongs to, e.g. "comment", "social"."""


@dataclass
class CgNotificationCodingamer(JSONWizardX):
    """The codingamer associated with a notification, e.g. the commenter or new follower who triggered it."""
    user_id: int
    country_id: str
    public_handle: str

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)

    pseudo: str | None = None
    """The codingamer's display name. Not always present--observed absent for at least one
       codingamer returned from a live findUnreadNotifications call, reason unknown."""

    avatar: int | None = None
    """The binary image ID of the codingamer's avatar image. Not always present--e.g. absent for a
       plain "following" notification."""

    cover: int | None = None
    """The binary image ID of the codingamer's cover image. Not always present--e.g. absent for a
       plain "following" notification."""


@dataclass
class CgNotification(JSONWizardX):
    """A single notification, as returned (in a bare JSON array) by findUnseenNotifications and
       findUnreadNotifications.

       The shape of `data` depends on `type`/`type_group`, and is not present for all notification types
       (e.g. it is absent for "following" notifications). Two shapes have been observed so far:

           # "new-comment"/"comment"
           {
               "commentType": "CONTRIBUTION",
               "commentId": <int>,
               "commentableId": <int>,
               "title": <str>,
               "type": {"en": <str>, "fr": <str>},
               "typeData": {"handle": <str>, "type": <str>}
           }

           # "custom"/"custom"
           {
               "title": {"en": <str>, "fr": <str>},
               "description": {"en": <str>, "fr": <str>},
               "url": <str>,
               "image": <str>
           }

       `data` is left as a raw dict pending examples of more notification types.
    """
    id: int
    type_group: CgNotificationTypeGroup
    priority: int
    urgent: bool

    _date: CgEpochMillis = Alias("date")

    notification_type: CgNotificationType = Alias("type")

    # See the note in CgNotificationCodingamer: `extra_data` is deliberately the first field with
    # a default. `notification_type` above is fine (Alias() with no default, so still "required"
    # for ordering purposes); new defaulted fields belong after `extra_data`, like `codingamer`/`data`.
    extra_data: CatchAll = field(default_factory=dict)

    codingamer: CgNotificationCodingamer | None = None
    """The codingamer who triggered the notification. Not present for all notification types--e.g.
       absent for a "custom" notification, which is a broadcast rather than tied to a specific user."""

    # Typed as a plain dict[str, Any] rather than the recursive JsonDict alias: dataclass_wizard
    # 1.0.0 corrupts nested dict values (e.g. {"en": "x", "fr": "y"} becomes ["en", "fr"]) when
    # loading a field typed with that self-referential Union.
    data: dict[str, Any] | None = None
    """Notification-type-specific payload; see class docstring. Absent for some notification types."""

    @property
    def date(self) -> datetime:
        """The date/time of the event that triggered the notification, always UTC."""
        return self._date

    @date.setter
    def date(self, value: datetime) -> None:
        self._date = CgEpochMillis.upcast(value)


__all__ = [
    "CgNotification", "CgNotificationCodingamer",
    "CgNotificationType", "CgNotificationTypeGroup",
]
