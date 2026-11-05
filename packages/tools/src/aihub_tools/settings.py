"""Data root and tool enable flags — the only settings the tool layer reads.

The server owns ``settings.json`` and validates the whole snapshot (models,
wake, audio, prompt). The tool layer must not import that schema: it is a leaf
package and the subprocess that runs MCP tools has no business knowing how TTS
is configured.

So this module reads exactly one section, ``tools``, and nothing else. A missing
or unreadable file falls back to the defaults below rather than raising, because
a tool subprocess that cannot read settings should report "not enabled" instead
of crashing the conversation.
"""

import copy
import json
from pathlib import Path

from aihub_common import env_value

__all__ = ["data_root", "load_tool_settings", "tool_enabled", "TOOL_DEFAULTS"]

#: Mirrors ``voicehub.config.DEFAULT['tools']`` for the boolean flags. Directory
#: and free-text knobs are not needed here.
TOOL_DEFAULTS = {
    'shopping_list': False,
    'timer': False,
    'item_memory': False,
    'calendar': True,
    'weather': True,
    'news': True,
    'system_info': True,
    'music': False,
    'file_organizer': False,
    'device_volume': True,
    'music_directory': '',
    'file_directory': '',
    'default_city': '',
    'news_source': 'bbc',
    'news_limit': 3,
    'timeout_seconds': 20,
    'planner': 'llm',
}


def data_root():
    """Return the AIHub data directory.

    ``AIHUB_DATA_ROOT`` (or the legacy ``VOICEHUB_DATA_ROOT``) wins; otherwise
    ``./data`` relative to the working directory.
    """
    raw = env_value('DATA_ROOT')
    return Path(raw).expanduser() if raw else Path.cwd() / 'data'


def load_tool_settings(root=None):
    """Return the merged ``tools`` section, or the defaults when unreadable."""
    root = Path(root) if root is not None else data_root()
    settings = copy.deepcopy(TOOL_DEFAULTS)
    try:
        snapshot = json.loads((root / 'settings.json').read_text())
    except (OSError, ValueError):
        return settings
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('tools'), dict):
        return settings
    settings.update({key: value for key, value in snapshot['tools'].items()
                     if key in TOOL_DEFAULTS})
    return settings


def tool_enabled(root, name):
    """True when ``settings.json`` enables the tool ``name``."""
    return bool(load_tool_settings(root).get(name, False))
