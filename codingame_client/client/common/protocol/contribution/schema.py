"""
JSON-serializable dataclasses for the findContribution and updateContribution Codingame API methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .....common.dataclass_wizard_x import Alias, CatchAll, CgEpochMillis, JSONWizardX

CgSolutionLanguage = str
"""The programming language used for the reference solution, e.g. "Python3", "Java", "C++", etc."""

_extension_map = {
        "sh": "Bash",
        "py": "Python3",
        "java": "Java",
        "cpp": "C++",
        "c": "C",
        "cs": "C#",
        "d": "DMD",
        "clj": "Clojure",
        "dart": "Dart",
        "fs": "F#",
        "groovy": "Groovy",
        "hs": "Haskell",
        "kt": "Kotlin",
        "lua": "Lua",
        "m": "Objective-C",
        "ml": "OCaml",
        "pas": "Pascal",
        "pl": "Perl",
        "php": "PHP",
        "scala": "Scala",
        "swift": "Swift",
        "vb": "VB.NET",
        "js": "JavaScript",
        "ts": "TypeScript",
        "rb": "Ruby",
        "go": "Go",
        "rs": "Rust",
        # Add more mappings as needed
    } 

def cg_extension_to_solution_language(filename_or_extension: str) -> CgSolutionLanguage | None:
    """Map a file extension to the corresponding Codingame solution language string used in the protocol.
       Returns None if the extension is not recognized."""
    ext = filename_or_extension.lower()
    if ext.startswith("."):
        ext = ext[1:]
    return _extension_map.get(ext)

_language_to_extension_map: dict[str, str] = {lang: ext for ext, lang in _extension_map.items()}

def cg_solution_language_to_extension(language: CgSolutionLanguage) -> str | None:
    """Map a Codingame solution language string to a file extension.
       Returns None if the language is not recognized."""
    return _language_to_extension_map.get(language)

CgMarkdown = str
"""A simplified markdown format used by Codingame for problem statements,
   input/output descriptions, and constraints. It allowsa highlighting of certain text, as:
   
    <<Bold Text>>
    [[Variable]] 
    {{Constant}} For example, {{pi}} = 3.14159
    `Monospace` Renders as a monospace code block. Forces line breaks.

    ```
    block style mono
    ```
    
    See https://www.codingame.com/playgrounds/40701/help-center/statement for more details.
"""

CgPuzzleType = str
"""The type of contribution, e.g. "PUZZLE_INOUT" for a standard noninteractive solo puzzle.
"""

CgHtml = str
"""Rendered HTML for display of the problem statement, input/output descriptions, and constraints.
   This is derived from the CgMarkdown content. It is rendered by the server and returned in the API response.
"""

CgStubGenerator = str
"""A script in CodingGame's stub generation language that can generate a stub solution
   for the puzzle in any supported programming language.
       See https://www.codingame.com/playgrounds/40701/help-center/stub-generator
"""

CgContributionId = str
"""A Contribution ID is a long, opaque string that uniquely identifies a contribution on the Codingame service.
   It is used in the findContribution and updateContribution API methods to retrieve or update a contribution
   and is not intended to be human-readable. It is returned in the response from findContribution."""
   
@dataclass
class CgTopic(JSONWizardX):
    """A topic associated with a contribution, e.g. "Parsing", "Sorting", etc. Most of
       the fields are fetched from the server in a search for topics."""
    id: int
    """The topic's unique identifier."""

    handle: str
    """Opaque short identifier for the topic, e.g. "parsing"."""

    category: str
    """e.g. "FUNDAMENTALS", "ADVANCED", "INTERMEDIATE"."""

    label_map: dict[str, str]
    """Localized display label for the topic (language code -> label), e.g. {"1": "Parsing", "2": "Parsing"}."""

    puzzle_count: int
    """The number of puzzles tagged with this topic."""

    parent_topic_id: int
    """The ID of this topic's parent topic in the topic hierarchy."""

    # `extra_data` is deliberately the first field with a default: dataclass_wizard 1.0.0 mis-binds
    # any defaulted field positioned immediately before it (silently, no error) to the CatchAll's
    # own value. Keeping it first among the defaulted fields makes that impossible.
    extra_data: CatchAll = field(default_factory=dict)

    page_title: str | None = None
    """Title of the topic's help-center page, if it has one."""

    content_details_id: int | None = None
    """ID of the topic's help-center content, if it has one."""


@dataclass
class CgTestCase(JSONWizardX):
    """A single test case for the contribution, including the input and expected
       output for the test. May represent either a local test case or a server-sideq validator test case.
       Tests are numbers in the order given, separately for local tests and validator tests.
       The server-side validator test cases are not shared with the puzzler, and used to validate the solution and score the submission."""
    title: str
    """Friendly title for the test case, e.g. "Large grid test case"""

    test_in: str
    """stdin text content for the test case"""

    test_out: str
    """Expected stdout text content for the test case"""

    is_test: bool
    """True if a local test shown to player during development prior to submission"""

    is_validator: bool
    """True if a server-side validator test case, hidden from player; used for validation / scoring"""

    need_validation: bool
    """Unclear what this field means; it is always true in current protocol tests."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgContributionData(JSONWizardX):
    """The actual contribution content, including the problem statement,
       input/output descriptions, constraints, difficulty, solution language,
       stub generator, topics, and test cases."""

    title: str
    """The title of the puzzle, e.g. "Grid Pathfinding" or "Sorting Challenge"."""

    # See the note in CgTopic: `extra_data` is deliberately the first field with a default.
    extra_data: CatchAll = field(default_factory=dict)

    statement: CgMarkdown | None = None
    """The problem statement, in simplified Markdown format, including the description
       of the problem, input/output formats, and examples."""
       
    input_description: CgMarkdown | None = None
    """The description of the provided stdin input format, in simplified Markdown format."""
    
    output_description: CgMarkdown | None = None
    """The description of the expected stdout output format, in simplified Markdown format."""
    
    constraints: CgMarkdown | None = None
    """The constraints for the problem, in simplified Markdown format, e.g. "1 ≤ N ≤ 1000" or "1 ≤ A[i] ≤ 10^9"."""
    
    difficulty: str | None = None
    """The difficulty category for the puzzle, e.g. "easy", "medium", or "hard"."""
    
    stub_generator: CgStubGenerator | None = None
    """The stub generator used for the puzzle."""
    
    topics: list[CgTopic] = field(default_factory=list)
    """The topics associated with the puzzle. Topic objects include metadata that is retrieved from the server
       when searching for topics by name."""
    
    test_cases: list[CgTestCase] = field(default_factory=list)
    """The test cases for the puzzle. Both local test cases shown to the player during development
       and server-side validator test cases are included here.
       The server-side validator test cases are not shared with the puzzler,
       and used to validate the solution and score the submission.
       
       When rendered, test cases are numbered in the order given, begining at 1, separately for local tests
       and validator tests.
       
       The way the input form is set up, the list will always consist of contiguous
       pairs of tests, with local test first and validator test second.
       """
    
    solution_language: CgSolutionLanguage | None = None
    """The programming language used for the reference solution, e.g. "Python3", "Java", "C++", etc.
       May be missing if the reference solution is not yet provided.
       See `cg_extension_to_solution_language` for mapping from file extension
       to solution language string.
    """
    
    solution: str | None = None
    """The reference solution code for the puzzle, in the specified solution language.
       May be missing if the reference solution is not yet provided.
       When a submission is made, this solution must pass all test cases for the submission to be accepted.
    """
    
    cover_binary_id: int | None = None
    """The ID of an uploaded graphical cover image for the puzzle. The image is uploaded separately
       and the server returns a binary ID for the image, which can be included here to associate
       the image with the contribution."""

@dataclass
class CgContributionVersion(JSONWizardX):
    """
    The wrapper for a specific version of a contribution, including
    the contribution data and metadata such as version number.
    """

    version: int
    """A sequentially incrementing version number for the contribution, starting at 1 for the first version.
       When submitting an edit, the previous version number must be provided as a parameter to
       updateContribution; this serves to make the API idempotent and prevent race conditions from concurrent edits."""
       
    data: CgContributionData
    """The actual contribution content, including the problem statement, input/output descriptions,
       constraints, difficulty, solution language,"""

    # See the note in CgTopic: `extra_data` is deliberately the first field with a default.
    extra_data: CatchAll = field(default_factory=dict)

    _autoclose_time: CgEpochMillis | None = Alias("autocloseTime", default=None)
    """The time at which the contribution will be automatically closed for voting and comments.
       This may be None if the contribution does not have an autoclose time set."""

    _freeze_time: CgEpochMillis | None = Alias("freezeTime", default=None)
    """Unclear precise semantics (not documented)--observed alongside `autoclose_time` with a value
       a couple of days earlier, so possibly when the contribution's content becomes locked from
       further edits, ahead of the later autoclose. May be None if not set."""

    draft: bool | None = None
    """Whether this version of the contribution is a draft. Draft versions are private to
       the contributor and are not shared for comment/approval. This field is only present in the response from findContribution,
       and is not included when submitting an update."""
       
    ready_for_moderation: bool | None = None
    """Whether this version of the contribution is ready for moderation.
       This field is only present in the response from findContribution, and is not included when submitting an update.
    """
    
    statement_html: CgHtml | None = Alias("statementHTML", default=None)
    """server-derived HTML rendering of the statement, input/output descriptions, and constraints.
       This field is only present in the response from findContribution, and is not included when submitting an update.

       Explicitly aliased: the server sends "statementHTML" (all-caps acronym), which the automatic
       camelCase transform doesn't produce from `statement_html` (it produces "statementHtml").
    """

    @property
    def autoclose_time(self) -> datetime | None:
        """The time at which the contribution will be automatically closed for voting and comments,
           always UTC. None if the contribution does not have an autoclose time set."""
        return self._autoclose_time

    @autoclose_time.setter
    def autoclose_time(self, value: datetime | None) -> None:
        self._autoclose_time = None if value is None else CgEpochMillis.upcast(value)

    @property
    def freeze_time(self) -> datetime | None:
        """See the field docstring for `_freeze_time`. Always UTC. None if not set."""
        return self._freeze_time

    @freeze_time.setter
    def freeze_time(self, value: datetime | None) -> None:
        self._freeze_time = None if value is None else CgEpochMillis.upcast(value)

@dataclass
class CgValidateAction(JSONWizardX):
    """The status of an asynchronous server-side validation action for a contribution (e.g.
       triggered by editing/submitting a puzzle). Only a single example has been observed so far,
       so field optionality is not yet well established--all three fields are currently required."""

    action_id: int
    """Opaque identifier for the validation action."""

    progress: float
    """Fractional progress of the validation action, from 0.0 to 1.0."""

    already_done: bool
    """Whether the validation action has already completed."""

    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgContribution(JSONWizardX):
    """The complete response to findContribution"""
    id: int
    """The unique identifier for the contribution, assigned by the server."""
    
    active_version: int
    """The version number of the currently active version of the contribution."""
    
    score: int
    """The score of the contribution."""
    
    votable_id: int
    """The unique identifier for the votable entity associated with the contribution."""
    
    codingamer_id: int
    """The unique identifier for the codingamer (contributor) who created the contribution."""
    
    views: int
    """The number of views the contribution has received."""
    
    commentable_id: int
    """The unique identifier for the commentable entity associated with the contribution."""
    
    title: str
    """The title of the contribution."""
    
    status: str
    """The status of the contribution, e.g. "PENDING", "APPROVED", "REJECTED"."""
    
    nickname: str
    """The nickname of the contributor."""
    
    public_handle: str
    """The public handle of the contribution. This is the identifier used for finding the contribution and updating it."""
    
    codingamer_handle: str
    """The long, opaque string identifier for the contributor."""
    
    last_version: CgContributionVersion
    """The most recent version of the contribution, including all content."""
    
    avatar: int
    """The binary image ID of the contributor's avatar image."""
    
    comment_count: int
    """The number of comments on the contribution."""
    
    up_votes: int
    """The number of up votes on the contribution."""
    
    down_votes: int
    """The number of down votes on the contribution."""
    
    editable: bool
    """Whether the contribution is currently editable by the contributor."""
    
    draft: bool
    """Whether the contribution is currently a draft."""
    
    ready_for_moderation: bool
    """Whether the contribution is ready for moderation."""
    
    contribution_type: CgPuzzleType = Alias("type")
    """The type of the contribution, e.g. "PUZZLE_INOUT" for a standard noninteractive solo puzzle."""

    # See the note in CgTopic: `extra_data` is deliberately the first field with a default.
    extra_data: CatchAll = field(default_factory=dict)

    status_history: list[Any] = field(default_factory=list)
    """The history of status changes for the contribution."""

    validate_action: CgValidateAction | None = None
    """The status of an in-progress server-side validation action for the contribution, if any."""

__all__ = [
    "CgContribution", "CgContributionData", "CgContributionVersion", "CgTestCase",
    "CgMarkdown", "CgHtml", "CgStubGenerator", "CgTopic", "CgContributionId", "CgPuzzleType",
    "CgSolutionLanguage", "CgValidateAction",
    "cg_extension_to_solution_language", "cg_solution_language_to_extension",
]
