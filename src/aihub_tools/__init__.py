"""AIHub tool layer: MCP tools, workflows, calendars and the local Rex planner.

This package is imported by ``aihub-server`` in the same process — tool planning
sits on every conversation turn, so it is deliberately *not* a network service.

It must not import ``aihub_server``: everything it needs from the server arrives
through the object the caller passes in (see ``context.ToolPipeline``).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
