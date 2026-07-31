"""
Synchronous-only client for the CodinGame API.

TODO: decided the need for a real sync implementation isn't strong enough to justify building
and maintaining a parallel client--this package stays an empty placeholder. At some point,
collapse the async_/sync split entirely: drop this package, move `client/async_` up to
`client/`, and rename its `CgAsync*` classes to drop the `Async` prefix (`CgAsyncClient` ->
`CgClient`, etc.).
"""

from __future__ import annotations

__all__ = [
]
