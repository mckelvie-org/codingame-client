"""Parsing of CodinGame-compatible timestamps from flexible human-friendly strings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytimeparse2  # type: ignore[import-untyped]

__all__ = ["parse_timestamp"]


def parse_timestamp(duration_str: str) -> datetime:
    """Parse a string into a Codingame compatible UTC timestamp. The
       return value is always in UTC timezone.

       Codingame uses timestamps in milliseconds since the epoch (1970-01-01T00:00:00Z).

       The following are accepted:
          - A simple bare number (e.g., "1680000000000") is interpreted as milliseconds since the epoch UTC. Note that
            this is different from the standard Unix timestamp, which is in seconds since the epoch.
          - A pytimeparse-compatible duration string with explicit units (e.g., "1h30m")
            is interpreted as a duration from the epoch UTC.
            To provide a Unix-style "seconds since epoch" timestamp, you can add an "s" suffix (e.g., "1680000000s").
          - A relative duration from now (e.g., "-1h30m" or "+0") is interpreted as a pytimeparse-compatible duration
            subtracted from or added to the current time.
          - An ISO 8601 datetime string (e.g., "2023-03-15T12:34:56Z"). If the string does not contain timezone information,
            it is assumed to be in the local timezone.
    """
    if duration_str.startswith(("+", "-")):
        # Relative duration from now
        sign_ch = duration_str[0]
        remainder = duration_str[1:]
        try:
            delta = cast(timedelta | None,
                    pytimeparse2.parse(remainder, granularity="seconds", as_timedelta=True)
                )
            if delta is None:
                raise ValueError(f"Bad pytimeparsestring: {remainder!r}")
            if sign_ch == "-":
                delta = -delta
            now = datetime.now(timezone.utc)
            dt = now + delta
            return dt
        except ValueError as e:
            raise ValueError(f"Invalid relative duration string: {duration_str!r}: {e}") from e
    try:
        ms = float(duration_str)
        seconds = ms / 1000.0
    except ValueError:
        delta = cast(timedelta | None,
                    pytimeparse2.parse(duration_str, granularity="seconds", as_timedelta=True)
                )
        if delta is None:
            # Try parsing as an ISO 8601 datetime string
            try:
                dt = datetime.fromisoformat(duration_str)
                dt = dt.astimezone(timezone.utc)
                return dt
            except ValueError:
                raise ValueError(f"Invalid timestamp or duration string: {duration_str!r}") from None
        seconds = delta.total_seconds()
    result = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return result
