"""
Async Intercom service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...raw_client import CgAsyncClientHttpError
from ..cg_service import CgAsyncService

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncIntercomService(CgAsyncService):
    """Async Intercom service endpoint."""

    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "Intercom")

    async def generate_token(self) -> str | None:
        """Generate an Intercom identity-verification JWT for the logged-in codingamer, used to
           authenticate the user's identity to Intercom's live-chat widget.

           The decoded JWT payload (HS256, audience "Intercom") contains standard identity
           claims: `user_id`, `email`, `pseudo`, `language_override`, plus `iat`/`exp` (observed
           validity: 1 hour).

           Returns None if Intercom is not available for the logged-in codingamer--observed for
           one real, logged-in account, reason unknown (possibly an account/plan-specific
           feature gate). This is a genuine, successfully-decoded `null` response, not an error.

        Returns:
            The signed JWT string, or None if not available for this codingamer.

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is neither a str nor null.
        """
        result = await self.service_request("generateToken")
        if result is None:
            return None
        if not isinstance(result, str):
            raise CgAsyncClientHttpError(
                    f"Invalid response type: expected a JSON string or null, got {type(result).__name__}",
                    content=result,
                )
        return result
