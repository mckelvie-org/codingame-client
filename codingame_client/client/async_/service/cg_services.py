"""Async service endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cg_service import CgAsyncService
from .services.achievement import CgAsyncAchievementService
from .services.clash_of_code import CgAsyncClashOfCodeService
from .services.clash_of_code_description import CgAsyncClashOfCodeDescriptionService
from .services.codingamer import CgAsyncCodingamerService
from .services.codingamer_puzzle_topic import CgAsyncCodingamerPuzzleTopicService
from .services.contribution import CgAsyncContributionService
from .services.featured_event import CgAsyncFeaturedEventService
from .services.intercom import CgAsyncIntercomService
from .services.last_activities import CgAsyncLastActivitiesService
from .services.notification import CgAsyncNotificationService
from .services.programming_language import CgAsyncProgrammingLanguageService
from .services.puzzle import CgAsyncPuzzleService
from .services.quest import CgAsyncQuestService
from .services.search import CgAsyncSearchService
from .services.survey import CgAsyncSurveyService
from .services.user import CgAsyncUserService

if TYPE_CHECKING:
    from ..client import CgAsyncClient

__all__ = [
    "CgAsyncService",
    "CgAsyncClient",
    "CgAsyncServices",
    "CgAsyncAchievementService",
    "CgAsyncClashOfCodeService",
    "CgAsyncClashOfCodeDescriptionService",
    "CgAsyncCodingamerService",
    "CgAsyncCodingamerPuzzleTopicService",
    "CgAsyncContributionService",
    "CgAsyncFeaturedEventService",
    "CgAsyncIntercomService",
    "CgAsyncLastActivitiesService",
    "CgAsyncNotificationService",
    "CgAsyncProgrammingLanguageService",
    "CgAsyncPuzzleService",
    "CgAsyncQuestService",
    "CgAsyncSearchService",
    "CgAsyncSurveyService",
    "CgAsyncUserService",
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
    achievement: CgAsyncAchievementService
    clash_of_code: CgAsyncClashOfCodeService
    clash_of_code_description: CgAsyncClashOfCodeDescriptionService
    codingamer: CgAsyncCodingamerService
    codingamer_puzzle_topic: CgAsyncCodingamerPuzzleTopicService
    contribution: CgAsyncContributionService
    featured_event: CgAsyncFeaturedEventService
    intercom: CgAsyncIntercomService
    last_activities: CgAsyncLastActivitiesService
    notification: CgAsyncNotificationService
    programming_language: CgAsyncProgrammingLanguageService
    puzzle: CgAsyncPuzzleService
    quest: CgAsyncQuestService
    search: CgAsyncSearchService
    survey: CgAsyncSurveyService
    user: CgAsyncUserService

    def __init__(self, client: CgAsyncClient) -> None:
        self.client = client
        self.achievement = CgAsyncAchievementService(client)
        self.clash_of_code = CgAsyncClashOfCodeService(client)
        self.clash_of_code_description = CgAsyncClashOfCodeDescriptionService(client)
        self.codingamer = CgAsyncCodingamerService(client)
        self.codingamer_puzzle_topic = CgAsyncCodingamerPuzzleTopicService(client)
        self.contribution = CgAsyncContributionService(client)
        self.featured_event = CgAsyncFeaturedEventService(client)
        self.intercom = CgAsyncIntercomService(client)
        self.last_activities = CgAsyncLastActivitiesService(client)
        self.notification = CgAsyncNotificationService(client)
        self.programming_language = CgAsyncProgrammingLanguageService(client)
        self.puzzle = CgAsyncPuzzleService(client)
        self.quest = CgAsyncQuestService(client)
        self.search = CgAsyncSearchService(client)
        self.survey = CgAsyncSurveyService(client)
        self.user = CgAsyncUserService(client)
