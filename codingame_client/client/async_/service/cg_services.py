"""Async service endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cg_service import CgAsyncService
from .services.codingamer import CgAsyncCodingamerService
from .services.contribution import CgAsyncContributionService
from .services.notification import CgAsyncNotificationService
from .services.programming_language import CgAsyncProgrammingLanguageService
from .services.search import CgAsyncSearchService

if TYPE_CHECKING:
    from ..client import CgAsyncClient
    
__all__ = [
    "CgAsyncService",
    "CgAsyncClient",
    "CgAsyncServices",
    "CgAsyncCodingamerService",
    "CgAsyncContributionService",
    "CgAsyncNotificationService",
    "CgAsyncProgrammingLanguageService",
    "CgAsyncSearchService",
]

class CgAsyncServices:
    """
    Service endpoints for the async CodinGame client.
    
    An instance of this class is created on CgAsyncClient, giving users well-typed access to all service endpoints.
    For example, to find a codingamer's points stats by their handle:
    
        async with CgAsyncClient() as client:
            stats = await client.services.codingamer.find_codingame_points_stats_by_handle("some_handle")
    """
    
    client: CgAsyncClient
    """The client through which endpoint requests are made."""
    
    # well-typed service endpoints
    codingamer: CgAsyncCodingamerService
    contribution: CgAsyncContributionService
    notification: CgAsyncNotificationService
    programming_language: CgAsyncProgrammingLanguageService
    search: CgAsyncSearchService

    def __init__(self, client: CgAsyncClient) -> None:
        self.client = client
        self.codingamer = CgAsyncCodingamerService(client)
        self.contribution = CgAsyncContributionService(client)
        self.notification = CgAsyncNotificationService(client)
        self.programming_language = CgAsyncProgrammingLanguageService(client)
        self.search = CgAsyncSearchService(client)
