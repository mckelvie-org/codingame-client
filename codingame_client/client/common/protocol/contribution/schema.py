"""
JSON-serializable dataclasses for the findContribution and updateContribution Codingame API methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .....common.dataclass_wizard_x import Alias, CatchAll, JSONWizardX

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
    class _(JSONWizardX.Meta):
        skip_defaults = True
    id: int
    handle: str
    category: str              # e.g. "FUNDAMENTALS", "ADVANCED", "INTERMEDIATE"
    label_map: dict[str, str]  # language-code → label, e.g. {"1": "Parsing", "2": "Parsing"}
    puzzle_count: int
    parent_topic_id: int
    page_title: str | None = None
    content_details_id: int | None = None
    
    extra_data: CatchAll = field(default_factory=dict)


@dataclass
class CgTestCase(JSONWizardX):
    """A single test case for the contribution, including the input and expected
       output for the test. May represent either a local test case or a server-sideq validator test case.
       Tests are numbers in the order given, separately for local tests and validator tests.
       The server-side validator test cases are not shared with the puzzler, and used to validate the solution and score the submission."""
    class _(JSONWizardX.Meta):
        skip_defaults = True

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
    class _(JSONWizardX.Meta):
        skip_defaults = True
        
    title: str
    """The title of the puzzle, e.g. "Grid Pathfinding" or "Sorting Challenge"."""
    
    statement: CgMarkdown | None = None
    """The problem statement, in simplified Markdown format, including the description
       of the problem, input/output formats, and examples."""
       
    input_description: CgMarkdown | None = None
    """The description of the provided stdin input format, in simplified Markdown format."""
    
    output_description: CgMarkdown | None = None
    """The description of the expected stdout output format, in simplified Markdown format."""
    
    constraints: CgMarkdown | None = None
    """The constraints for the problem, in simplified Markdown format, e.g. "1 ≤ N ≤ 1000" or "1 ≤ A[i] ≤ 10^9"."""
    
    difficulty: str | None = None            # e.g. "easy", "medium", "hard"
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
    
    solution_language: CgSolutionLanguage | None = None     # e.g. "Python3"
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

    extra_data: CatchAll = field(default_factory=dict)

@dataclass
class CgContributionVersion(JSONWizardX):
    """
    The wrapper for a specific version of a contribution, including
    the contribution data and metadata such as version number.
    """
    class _(JSONWizardX.Meta):
        skip_defaults = True
        
    version: int
    """A sequentially incrementing version number for the contribution, starting at 1 for the first version.
       When submitting an edit, the previous version number must be provided as a parameter to
       updateContribution; this serves to make the API idempotent and prevent race conditions from concurrent edits."""
       
    data: CgContributionData
    """The actual contribution content, including the problem statement, input/output descriptions,
       constraints, difficulty, solution language,"""

    autoclose_time: int | None = None   # millisecond epoch timestamp
    """The time at which the contribution will be automatically closed for voting and comments, in millisecond epoch timestamp.
       This may be None if the contribution does not have an autoclose time set."""
       
    draft: bool | None = None
    """Whether this version of the contribution is a draft. Draft versions are private to
       the contributor and are not shared for comment/approval. This field is only present in the response from findContribution,
       and is not included when submitting an update."""
       
    ready_for_moderation: bool | None = None
    """Whether this version of the contribution is ready for moderation.
       This field is only present in the response from findContribution, and is not included when submitting an update.
    """
    
    statement_html: CgHtml | None = None
    """server-derived HTML rendering of the statement, input/output descriptions, and constraints.
       This field is only present in the response from findContribution, and is not included when submitting an update.
    """
    
    extra_data: CatchAll = field(default_factory=dict)
    
@dataclass
class CgContribution(JSONWizardX):
    """The complete response to findContribution"""
    class _(JSONWizardX.Meta):
        skip_defaults = True

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
    
    contribution_type: CgPuzzleType = Alias("type")   # e.g. "PUZZLE_INOUT"
    """The type of the contribution, e.g. "PUZZLE_INOUT" for a standard noninteractive solo puzzle."""
    
    status_history: list[Any] = field(default_factory=list)
    """The history of status changes for the contribution."""

    extra_data: CatchAll = field(default_factory=dict)
    
__all__ = [
    "CgContribution", "CgContributionData", "CgContributionVersion", "CgTestCase",
    "CgMarkdown", "CgHtml", "CgStubGenerator", "CgTopic", "CgContributionId", "CgPuzzleType",
     "CgSolutionLanguage", "cg_extension_to_solution_language", "cg_solution_language_to_extension",
]
