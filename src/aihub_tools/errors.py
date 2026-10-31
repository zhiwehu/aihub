"""Error types shared between the tool layer and the server.

``DeviceMCPError`` used to live in the server's ``device_mcp`` module, but the
device-volume tool raises it and the tool package must not import the server.
The class therefore lives here; the server imports it from this package.
"""

__all__ = ["DeviceMCPError"]


class DeviceMCPError(RuntimeError):
    """The device-side MCP channel failed; ``code`` reaches the client verbatim."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)
