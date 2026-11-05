"""Minimal settings snapshot for tests.

The tool layer only reads ``settings.json``'s ``tools`` section, so tests do not
need the server's full config schema.
"""

import copy

from aihub_tools.settings import TOOL_DEFAULTS


def default_config():
    return {'tools': copy.deepcopy(TOOL_DEFAULTS)}


DEFAULT = default_config()
