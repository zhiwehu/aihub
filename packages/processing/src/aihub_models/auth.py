"""Loopback-only request guard shared by the model services.

The old ``voicehub/qwen_tts.py`` imported ``local_admin`` from the web
application module. Nothing in this package may depend on the server, so the
check lives here: every model endpoint must come from loopback (or an explicit
``localhost`` host header) and must not carry a cross-site ``Origin``.
"""

import ipaddress
from urllib.parse import urlsplit

from aiohttp import web

__all__ = ["is_loopback", "same_origin_guard"]


def is_loopback(request):
    """True when the peer address and the Host header both name this machine."""
    try:
        address = ipaddress.ip_address(request.remote or '')
        host = urlsplit('//' + request.host).hostname
        return address.is_loopback and (host == 'localhost' or ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False


@web.middleware
async def same_origin_guard(request, handler):
    """Reject non-loopback peers and cross-site browser origins."""
    if not is_loopback(request):
        raise web.HTTPForbidden()
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden()
    return await handler(request)
