"""Local working-directory management for CodinGame contributions (puzzles)--analogous to a git
   working directory backed by a remote repo. See `CgContributionManager` for
   `import_`/`commit`/`rebase`/`merge_discard_local`/`merge_discard_server`,
   `CgContributionWorkingDir` for the `contribution.json` manifest format,
   `CgLastCommittedContribution` for the `last_committed/` cached-base format,
   `codingame_client.contribution_manager.tree_diff` for 2-way/3-way directory comparison, and
   `codingame_client.contribution_manager.resolver` for how a contribution directory is located.
"""

from __future__ import annotations

from .last_committed import (
    LAST_COMMITTED_CONTRIBUTION_FILE_NAME,
    LAST_COMMITTED_COVER_FILE_NAME,
    LAST_COMMITTED_SUBDIR_NAME,
    CgLastCommittedContribution,
)
from .manager import (
    CONSTRAINTS_FILE_NAME,
    COVER_IMAGE_FILE_NAME,
    INPUT_DESCRIPTION_FILE_NAME,
    OUTPUT_DESCRIPTION_FILE_NAME,
    STATEMENT_FILE_NAME,
    STUB_GENERATOR_FILE_NAME,
    CgContributionManager,
    CgContributionManagerError,
    CgRebaseStatus,
)
from .merge_tools import (
    DEFAULT_MERGE_TOOL,
    MERGE_TOOL_COMMANDS,
    CgMergeToolNotFoundError,
    launch_merge_tool,
)
from .resolver import (
    CG_CONTRIBUTION_DIR_ENV_VAR,
    DEFAULT_CONTRIBUTION_SUBDIR_NAME,
    CgContributionDirNotFoundError,
    find_contribution_dir,
    resolve_contribution_dir,
)
from .schema import CONTRIBUTION_FILE_NAME, CgContributionWorkingDir
from .test_cases_dir import (
    LOCAL_SUBDIR_NAME,
    TEST_META_FILE_NAME,
    TESTS_SUBDIR_NAME,
    VALIDATOR_SUBDIR_NAME,
    CgContributionTestCaseError,
    CgTestCaseFileMeta,
    commit_test_cases,
    import_test_cases,
    normalize_test_title,
    renormalize_test_case_dirs,
)
from .tree_diff import (
    ThreeWayEntry,
    TwoWayEntry,
    diff_three_trees,
    diff_two_trees,
    looks_like_text,
    render_three_way_diff,
    render_two_way_diff,
)

__all__ = [
    "CgContributionManager",
    "CgContributionManagerError",
    "CgRebaseStatus",
    "CgContributionWorkingDir",
    "CONTRIBUTION_FILE_NAME",
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
    "CgLastCommittedContribution",
    "LAST_COMMITTED_SUBDIR_NAME",
    "LAST_COMMITTED_CONTRIBUTION_FILE_NAME",
    "LAST_COMMITTED_COVER_FILE_NAME",
    "CgContributionDirNotFoundError",
    "find_contribution_dir",
    "resolve_contribution_dir",
    "CG_CONTRIBUTION_DIR_ENV_VAR",
    "DEFAULT_CONTRIBUTION_SUBDIR_NAME",
    "TESTS_SUBDIR_NAME",
    "TEST_META_FILE_NAME",
    "LOCAL_SUBDIR_NAME",
    "VALIDATOR_SUBDIR_NAME",
    "CgContributionTestCaseError",
    "CgTestCaseFileMeta",
    "normalize_test_title",
    "import_test_cases",
    "commit_test_cases",
    "renormalize_test_case_dirs",
    "TwoWayEntry",
    "ThreeWayEntry",
    "diff_two_trees",
    "diff_three_trees",
    "looks_like_text",
    "render_two_way_diff",
    "render_three_way_diff",
    "DEFAULT_MERGE_TOOL",
    "MERGE_TOOL_COMMANDS",
    "CgMergeToolNotFoundError",
    "launch_merge_tool",
]
