"""Async per-service endpoint implementations."""

from __future__ import annotations

from .achievement import CgAsyncAchievementService
from .clash_of_code import CgAsyncClashOfCodeService
from .clash_of_code_description import CgAsyncClashOfCodeDescriptionService
from .codingamer import CgAsyncCodingamerService
from .codingamer_puzzle_topic import CgAsyncCodingamerPuzzleTopicService
from .contribution import CgAsyncContributionService
from .featured_event import CgAsyncFeaturedEventService
from .intercom import CgAsyncIntercomService
from .last_activities import CgAsyncLastActivitiesService
from .notification import CgAsyncNotificationService
from .programming_language import CgAsyncProgrammingLanguageService
from .puzzle import CgAsyncPuzzleService
from .quest import CgAsyncQuestService
from .report import CgAsyncReportService
from .search import CgAsyncSearchService
from .survey import CgAsyncSurveyService
from .test_session import CgAsyncTestSessionService
from .test_session_question_submission import CgAsyncTestSessionQuestionSubmissionService
from .user import CgAsyncUserService

__all__ = [
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
    "CgAsyncReportService",
    "CgAsyncSearchService",
    "CgAsyncSurveyService",
    "CgAsyncTestSessionService",
    "CgAsyncTestSessionQuestionSubmissionService",
    "CgAsyncUserService",
]
