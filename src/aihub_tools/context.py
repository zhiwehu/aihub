"""The surface the tool layer needs from the server, declared as Protocols.

``aihub-tools`` is imported by ``aihub-server``, so it must never import the
server back. Historically the tool code reached into a grab-bag object
(``pipeline.local``) that the server stuffed with a dozen attributes, which made
the dependency invisible. The split makes it explicit:

* the server passes a ``pipeline`` whose ``runtime`` attribute is a
  ``ToolRuntime``;
* ``pipeline.chat`` / ``pipeline.raw_chat`` stream LLM text;
* ``pipeline.device`` is the current session's device-MCP bridge (or ``None``).

Nothing here is enforced at runtime beyond what python does; the Protocols exist
so that the contract is written down and type checkers can catch drift.
"""

from typing import Any, Protocol, runtime_checkable

__all__ = ["ToolPipeline", "ToolRuntime"]


@runtime_checkable
class ToolRuntime(Protocol):
    """Long-lived objects owned by the server and shared with the tool layer."""

    #: Data directory (recordings, calendars, workflow storage, adapters).
    data_root: Any
    #: Local Rex planner, or a stub that raises when it is not configured.
    planner: Any
    #: User-imported MCP extensions.
    extensions: Any
    #: Task-chain manager.
    workflows: Any
    #: Background operation records.
    operations: Any
    #: Skill definitions.
    skills: Any
    #: Calendar store plus reminders.
    calendar: Any
    #: Meeting-minutes service (may live in aihub-models).
    minutes: Any
    #: Model worker supervisor.
    services: Any
    #: Speaker embeddings (may live in aihub-models).
    speakers: Any


@runtime_checkable
class ToolPipeline(Protocol):
    """What one conversation turn exposes to the tool layer."""

    runtime: ToolRuntime
    #: Device-MCP bridge for the current session, or ``None`` when offline.
    device: Any

    def chat(self, history):
        """Yield reply text, running tool planning and calls when needed."""
        ...

    def raw_chat(self, history, *, system_prompt=None, max_tokens=None):
        """Yield plain LLM text without the tool layer."""
        ...
