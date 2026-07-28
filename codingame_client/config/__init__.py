"""Persistent configuration and data-directory discovery for CodinGame client tools (CLI,
   contribution manager, and potentially the client itself).
"""

from __future__ import annotations

from .cg_config import CgConfigData
from .resolver import (
    APP_NAME,
    CG_CONFIG_ENV_VAR,
    CONFIG_FILE_NAME,
    CONFIG_SUBDIR_NAME,
    DATA_SUBDIR_NAME,
    PROJECT_CONFIG_MARKER_DIR_NAME,
    VENDOR_NAME,
    CgConfig,
    CgConfigNotFoundError,
    default_global_config_file,
    default_global_data_dir,
    find_config_file,
    resolve_config,
    write_config,
)

__all__ = [
    "CgConfigData",
    "CgConfig",
    "CgConfigNotFoundError",
    "find_config_file",
    "resolve_config",
    "write_config",
    "default_global_config_file",
    "default_global_data_dir",
    "CG_CONFIG_ENV_VAR",
    "PROJECT_CONFIG_MARKER_DIR_NAME",
    "CONFIG_SUBDIR_NAME",
    "DATA_SUBDIR_NAME",
    "CONFIG_FILE_NAME",
    "APP_NAME",
    "VENDOR_NAME",
]
