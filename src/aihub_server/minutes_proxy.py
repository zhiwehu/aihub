"""Forward the meeting-minutes admin API to the aihub-models service.

Minutes used to be generated in-process. They are now a job inside
``aihub-models`` (they need the local Qwen model and can run for minutes), so
the server keeps the same public routes and proxies them unchanged. The web
client does not need to know the service moved.
"""

from .models_client import proxy

__all__ = ["minutes_proxy"]


async def minutes_proxy(request):
    return await proxy(request)
