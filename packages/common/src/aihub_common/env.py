"""Environment lookups that tolerate the pre-split ``VOICEHUB_`` prefix.

AIHub was split out of the single ``voicehub`` package. Every knob used to be
``VOICEHUB_*``; renaming them all at once would break existing shells and
launch scripts, so the new name is read first and the old name is kept as a
fallback. Drop the fallback once no deployment sets the old names.

Usage: ``env_value('WORKER_TOKEN')`` reads ``AIHUB_WORKER_TOKEN`` and then
``VOICEHUB_WORKER_TOKEN``.
"""

import os

__all__ = ["env_value"]

PREFIXES = ('AIHUB_', 'VOICEHUB_')


def env_value(name, default=None):
    """Return the first set value among ``AIHUB_<name>`` and ``VOICEHUB_<name>``."""
    for prefix in PREFIXES:
        raw = os.environ.get(prefix + name)
        if raw is not None:
            return raw
    return default
