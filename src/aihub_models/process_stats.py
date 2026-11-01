"""Self-reported process footprint.

The console runs in a container while ASR/LLM/TTS workers run natively on the
host, so nothing can inspect the other side's processes. Each service therefore
reports its own numbers through ``/health`` and the server adds them up.
"""
import os

import psutil

_process = None


def _current():
    global _process
    if _process is None or _process.pid != os.getpid() or not _process.is_running():
        _process = psutil.Process()
    return _process


def stats():
    """``pid``/``rss``/``cpu_percent``/``threads`` for this process, or {} on failure."""
    try:
        process = _current()
        return {'pid': process.pid,
                'rss': process.memory_info().rss,
                # First call after start reports 0.0; the console polls.
                'cpu_percent': round(process.cpu_percent(interval=None), 1),
                'threads': process.num_threads()}
    except psutil.Error:
        return {}
