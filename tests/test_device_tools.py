"""Import guards for tool modules whose helpers are imported lazily.

``tool_chat.device_turn`` imports the device error type inside the function, so
a wrong module path only fails when a volume command is actually spoken. That
happened once during the repository split; this test is here so it cannot
happen silently again.
"""

import importlib


def test_every_moved_error_type_imports_from_its_new_home():
    import aihub_tools.errors as errors

    assert hasattr(errors, 'DeviceMCPError')
    for module in ('aihub_tools.tool_chat', 'aihub_tools.mcp_tools.device_volume'):
        importlib.import_module(module)


def test_device_volume_tool_is_registered():
    from aihub_tools.mcp_tools import TOOLS

    assert 'device_volume' in TOOLS
    assert TOOLS['device_volume'].DEVICE_TOOL is True
