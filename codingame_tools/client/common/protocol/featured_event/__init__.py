"""
Protocol schema definitions for the FeaturedEvent service.
"""

from __future__ import annotations

from ..clash_of_code import CgClashMode
from ..schema import CgSolutionLanguage
from .schema import CgClashSlot, CgFeaturedEvent, CgFeaturedEventType

__all__ = [
    "CgClashMode", "CgClashSlot", "CgFeaturedEvent", "CgFeaturedEventType", "CgSolutionLanguage",
]
