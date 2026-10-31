"""Shared primitives for AIHub services.

This package is the leaf of the dependency graph: it must not import any other
AIHub package. Everything here is a pure function, a plain exception type, or a
model-free algorithm over numpy arrays.
"""

from .env import env_value
from .errors import ProviderError
from .pcm import TARGET_RATE, to_pcm16
from .speaker import SpeakerTracker, SpeakerUnavailable, normalize
from .speech_text import spoken_text
from .stamp import stamp_ms, stamp_text

__all__ = [
    "ProviderError",
    "env_value",
    "SpeakerTracker",
    "SpeakerUnavailable",
    "TARGET_RATE",
    "normalize",
    "to_pcm16",
    "spoken_text",
    "stamp_ms",
    "stamp_text",
]

__version__ = "0.2.0"
