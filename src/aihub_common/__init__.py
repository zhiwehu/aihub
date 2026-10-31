"""Shared primitives for AIHub services.

This package is the leaf of the dependency graph: it must not import any other
AIHub package. Everything here is a pure function or a plain exception type.
"""

from .errors import ProviderError
from .pcm import TARGET_RATE, to_pcm16
from .speech_text import spoken_text
from .stamp import stamp_ms, stamp_text

__all__ = [
    "ProviderError",
    "TARGET_RATE",
    "to_pcm16",
    "spoken_text",
    "stamp_ms",
    "stamp_text",
]

__version__ = "0.1.0"
