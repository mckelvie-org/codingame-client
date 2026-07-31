"""Package logger"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__.rsplit(".", 1)[0])

_all__ = [
    "logger",
]
