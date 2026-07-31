"""Async service endpoints for the async CodinGame client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cg_service import CgAsyncService, CgAsyncServiceHelper
from .services.achievement import CgAsyncAchievementService, CgAsyncAchievementServiceHelper
from .services.clash_of_code import CgAsyncClashOfCodeService, CgAsyncClashOfCodeServiceHelper
from .services.clash_of_code_description import (
    CgAsyncClashOfCodeDescriptionService,
    CgAsyncClashOfCodeDescriptionServiceHelper,
)
from .services.codingamer import CgAsyncCodingamerService, CgAsyncCodingamerServiceHelper
from .services.codingamer_puzzle_topic import (
    CgAsyncCodingamerPuzzleTopicService,
    CgAsyncCodingamerPuzzleTopicServiceHelper,
)
from .services.contribution import CgAsyncContributionService, CgAsyncContributionServiceHelper
from .services.featured_event import CgAsyncFeaturedEventService, CgAsyncFeaturedEventServiceHelper
from .services.intercom import CgAsyncIntercomService, CgAsyncIntercomServiceHelper
from .services.last_activities import CgAsyncLastActivitiesService, CgAsyncLastActivitiesServiceHelper
from .services.notification import CgAsyncNotificationService, CgAsyncNotificationServiceHelper
from .services.programming_language import CgAsyncProgrammingLanguageService, CgAsyncProgrammingLanguageServiceHelper
from .services.puzzle import CgAsyncPuzzleService, CgAsyncPuzzleServiceHelper
from .services.quest import CgAsyncQuestService, CgAsyncQuestServiceHelper
from .services.report import CgAsyncReportService, CgAsyncReportServiceHelper
from .services.search import CgAsyncSearchService, CgAsyncSearchServiceHelper
from .services.survey import CgAsyncSurveyService, CgAsyncSurveyServiceHelper
from .services.test_session import CgAsyncTestSessionService, CgAsyncTestSessionServiceHelper
from .services.test_session_question_submission import (
    CgAsyncTestSessionQuestionSubmissionService,
    CgAsyncTestSessionQuestionSubmissionServiceHelper,
)
from .services.user import CgAsyncUserService, CgAsyncUserServiceHelper
from .services.vote import CgAsyncVoteService, CgAsyncVoteServiceHelper

if TYPE_CHECKING:
    from ..client import CgAsyncClient

__all__ = [
    "CgAsyncService",
    "CgAsyncServiceHelper",
    "CgAsyncClient",
    "CgAsyncServices",
    "CgAsyncAchievementService",
    "CgAsyncAchievementServiceHelper",
    "CgAsyncClashOfCodeService",
    "CgAsyncClashOfCodeServiceHelper",
    "CgAsyncClashOfCodeDescriptionService",
    "CgAsyncClashOfCodeDescriptionServiceHelper",
    "CgAsyncCodingamerService",
    "CgAsyncCodingamerServiceHelper",
    "CgAsyncCodingamerPuzzleTopicService",
    "CgAsyncCodingamerPuzzleTopicServiceHelper",
    "CgAsyncContributionService",
    "CgAsyncContributionServiceHelper",
    "CgAsyncFeaturedEventService",
    "CgAsyncFeaturedEventServiceHelper",
    "CgAsyncIntercomService",
    "CgAsyncIntercomServiceHelper",
    "CgAsyncLastActivitiesService",
    "CgAsyncLastActivitiesServiceHelper",
    "CgAsyncNotificationService",
    "CgAsyncNotificationServiceHelper",
    "CgAsyncProgrammingLanguageService",
    "CgAsyncProgrammingLanguageServiceHelper",
    "CgAsyncPuzzleService",
    "CgAsyncPuzzleServiceHelper",
    "CgAsyncQuestService",
    "CgAsyncQuestServiceHelper",
    "CgAsyncReportService",
    "CgAsyncReportServiceHelper",
    "CgAsyncSearchService",
    "CgAsyncSearchServiceHelper",
    "CgAsyncSurveyService",
    "CgAsyncSurveyServiceHelper",
    "CgAsyncTestSessionService",
    "CgAsyncTestSessionServiceHelper",
    "CgAsyncTestSessionQuestionSubmissionService",
    "CgAsyncTestSessionQuestionSubmissionServiceHelper",
    "CgAsyncUserService",
    "CgAsyncUserServiceHelper",
    "CgAsyncVoteService",
    "CgAsyncVoteServiceHelper",
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
    report: CgAsyncReportService
    search: CgAsyncSearchService
    survey: CgAsyncSurveyService
    test_session: CgAsyncTestSessionService
    test_session_question_submission: CgAsyncTestSessionQuestionSubmissionService
    user: CgAsyncUserService
    vote: CgAsyncVoteService

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
        self.report = CgAsyncReportService(client)
        self.search = CgAsyncSearchService(client)
        self.survey = CgAsyncSurveyService(client)
        self.test_session = CgAsyncTestSessionService(client)
        self.test_session_question_submission = CgAsyncTestSessionQuestionSubmissionService(client)
        self.user = CgAsyncUserService(client)
        self.vote = CgAsyncVoteService(client)
