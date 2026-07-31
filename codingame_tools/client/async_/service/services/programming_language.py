"""
Async ProgrammingLanguage service endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ....common.protocol.schema import CgSolutionLanguage
from ..cg_service import CgAsyncService, CgAsyncServiceHelper

if TYPE_CHECKING:
    from ...client import CgAsyncClient


class CgAsyncProgrammingLanguageServiceHelper(CgAsyncServiceHelper["CgAsyncProgrammingLanguageService"]):
    """Helper methods for CgAsyncProgrammingLanguageService. Currently empty."""


class CgAsyncProgrammingLanguageService(CgAsyncService):
    """Async ProgrammingLanguage service endpoint."""
    
    def __init__(self, client: CgAsyncClient) -> None:
        super().__init__(client, "ProgrammingLanguage")
        self.helper = CgAsyncProgrammingLanguageServiceHelper(self)

    async def find_all_ids(self) -> list[CgSolutionLanguage]:
        """Find the IDs of all programming languages supported for contribution reference solutions.

        Returns:
            A list of `CgSolutionLanguage` strings, e.g. "Python3", "Java", "C++".

        Raises:
            CgAuthenticationError:
                If the session is not authenticated and cannot implicitly login.
            CgAsyncClientHttpError:
                If a transport error occurs, if the response content could not be decoded at all,
                if the status code is not 2xx, or if the decoded content is not a list.
        """
        raw_ids = await self.service_request_to_list("findAllIds", [])
        return cast(list[CgSolutionLanguage], raw_ids)
