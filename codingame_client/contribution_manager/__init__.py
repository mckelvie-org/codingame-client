"""Local working-directory management for CodinGame contributions (puzzles)--analogous to a git
   working directory backed by a remote repo.

   See `CgContributionManager` for `import_`/`commit`/`rebase`/`merge_start`/`merge_continue`/
   `merge_abort`/`merge_discard_local`/`merge_discard_server`/`revert`; `codingame_client.
   contribution_manager.schema` for the working directory's own manifest files
   (`CgContributionIdentity`/`CgContributionView`); `codingame_client.contribution_manager.
   contribution_commit_data` for `CgContributionCommitData` (remote commit metadata present in
   server-originated views); `codingame_client.contribution_manager.tree_diff` for 2-way/3-way
   directory comparison; `codingame_client.contribution_manager.merge_tools` for external
   diff/merge tool integration; and `codingame_client.contribution_manager.resolver` for how a
   contribution directory is located.
"""

from __future__ import annotations

from .contribution_commit_data import (
    CONTRIBUTION_COMMIT_DATA_FILE_NAME,
    CgContributionCommitData,
    redact_commit_contribution,
)
from .layout import (
    COVER_IMAGE_FILE_NAME,
    DATA_SUBDIR_NAME,
    LAST_COMMITTED_SUBDIR_NAME,
    MERGE_LOCAL_SUBDIR_NAME,
    MERGE_SUBDIR_NAME,
    META_SUBDIR_NAME,
    REMOTE_SUBDIR_NAME,
    SOLUTION_FILE_NAME,
)
from .manager import (
    CONSTRAINTS_FILE_NAME,
    INPUT_DESCRIPTION_FILE_NAME,
    OUTPUT_DESCRIPTION_FILE_NAME,
    STATEMENT_FILE_NAME,
    STUB_GENERATOR_FILE_NAME,
    CgContributionManager,
    CgContributionManagerError,
    CgMergeStartResult,
    CgMergeStartStatus,
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
from .schema import (
    CONTRIBUTION_DATA_FILE_NAME,
    CONTRIBUTION_IDENTITY_FILE_NAME,
    CONTRIBUTION_SCHEMA_VERSION,
    CgContributionIdentity,
    CgContributionView,
)
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
    compute_diff3_merge,
    diff_three_trees,
    diff_two_trees,
    looks_like_text,
    read_view_files,
    render_three_way_diff,
    render_two_way_diff,
)

__all__ = [
    "CgContributionManager",
    "CgContributionManagerError",
    "CgRebaseStatus",
    "CgMergeStartStatus",
    "CgMergeStartResult",
    "CgContributionIdentity",
    "CgContributionView",
    "CONTRIBUTION_IDENTITY_FILE_NAME",
    "CONTRIBUTION_DATA_FILE_NAME",
    "CONTRIBUTION_SCHEMA_VERSION",
    "CgContributionCommitData",
    "CONTRIBUTION_COMMIT_DATA_FILE_NAME",
    "redact_commit_contribution",
    "STATEMENT_FILE_NAME",
    "INPUT_DESCRIPTION_FILE_NAME",
    "OUTPUT_DESCRIPTION_FILE_NAME",
    "CONSTRAINTS_FILE_NAME",
    "STUB_GENERATOR_FILE_NAME",
    "SOLUTION_FILE_NAME",
    "COVER_IMAGE_FILE_NAME",
    "DATA_SUBDIR_NAME",
    "LAST_COMMITTED_SUBDIR_NAME",
    "REMOTE_SUBDIR_NAME",
    "META_SUBDIR_NAME",
    "MERGE_SUBDIR_NAME",
    "MERGE_LOCAL_SUBDIR_NAME",
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
    "read_view_files",
    "render_two_way_diff",
    "render_three_way_diff",
    "compute_diff3_merge",
    "DEFAULT_MERGE_TOOL",
    "MERGE_TOOL_COMMANDS",
    "CgMergeToolNotFoundError",
    "launch_merge_tool",
]
