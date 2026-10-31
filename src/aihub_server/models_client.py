"""Client for the aihub-models service (media jobs and meeting minutes).

The server no longer runs inference or post-processing in-process, so anything
that used to call ``rediarize``, ``clean_wav`` or ``MinutesService`` now goes
through this module. The service is optional: when no token is configured the
helpers raise ``ModelsUnavailable`` and the HTTP layer turns that into a clear
503 instead of a silent hang.
"""

import json
from urllib.parse import urlsplit

import aiohttp
from aihub_common import env_value

DEFAULT_URL = 'http://127.0.0.1:8790'
TIMEOUT = aiohttp.ClientTimeout(total=1800, connect=5, sock_read=60)


class ModelsUnavailable(RuntimeError):
    """The model service is not configured or not reachable."""


def base_url():
    return (env_value('MODELS_URL') or DEFAULT_URL).rstrip('/')


def token():
    return env_value('MODELS_TOKEN') or ''


def configured():
    return bool(token())


def headers():
    value = token()
    if not value:
        raise ModelsUnavailable('models_unconfigured')
    return {'Authorization': 'Bearer ' + value}


async def submit(recording_id, kind, options=None):
    """Queue one media job and return its record."""
    payload = {'kind': kind, 'recording_id': recording_id}
    if options is not None:
        payload['options'] = options
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as client:
            async with client.post(base_url() + '/v1/media/jobs', json=payload,
                                   headers=headers()) as response:
                body = await response.json()
                if response.status >= 400:
                    error = (body or {}).get('error') or {}
                    raise ModelsUnavailable(error.get('code') or f'models_http_{response.status}')
                return body['job']
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise ModelsUnavailable('models_unreachable') from None


async def wait(job_id, timeout=1800):
    """Poll one job until it finishes; raise when it fails."""
    import asyncio
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as client:
            while True:
                async with client.get(f'{base_url()}/v1/media/jobs/{job_id}',
                                      headers=headers()) as response:
                    body = await response.json()
                    if response.status >= 400:
                        error = (body or {}).get('error') or {}
                        raise ModelsUnavailable(error.get('code') or f'models_http_{response.status}')
                job = body['job']
                if job.get('status') in ('done', 'failed', 'cancelled', 'interrupted'):
                    return job
                if asyncio.get_running_loop().time() > deadline:
                    raise ModelsUnavailable('models_timeout')
                await asyncio.sleep(1)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise ModelsUnavailable('models_unreachable') from None


async def run(recording_id, kind, options=None, timeout=1800):
    """Submit a job and wait for it in one call."""
    job = await submit(recording_id, kind, options)
    return await wait(job['id'], timeout)


async def proxy(request):
    """Forward one admin request to the matching ``/v1`` route on the service."""
    from aiohttp import web

    path = request.path
    target = '/v1' + path[len('/api'):] if path.startswith('/api') else path
    query = request.query_string
    if query:
        target += '?' + query
    body = await request.read() if request.can_read_body else None
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as client:
            async with client.request(request.method, base_url() + target, data=body,
                                      headers={**headers(), 'Content-Type': request.content_type}
                                      if body is not None else headers()) as response:
                raw = await response.read()
                passthrough = {key: response.headers[key]
                               for key in ('Content-Type', 'Content-Disposition')
                               if key in response.headers}
                return web.Response(body=raw, status=response.status,
                                    headers={**passthrough, 'Cache-Control': 'no-store'})
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return web.json_response(
            {'error': {'code': 'models_unreachable',
                       'message': '本机的模型服务没有运行，暂时无法处理这个请求。'}},
            status=503, headers={'Cache-Control': 'no-store'})


async def get_json(path):
    """GET a JSON document from the service."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as client:
            async with client.get(base_url() + path, headers=headers()) as response:
                body = await response.json()
                if response.status >= 400:
                    error = (body or {}).get('error') or {}
                    raise ModelsUnavailable(error.get('code') or f'models_http_{response.status}')
                return body
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise ModelsUnavailable('models_unreachable') from None


async def post_json(path, payload):
    """POST a JSON document to the service."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as client:
            async with client.post(base_url() + path, json=payload, headers=headers()) as response:
                body = await response.json()
                if response.status >= 400:
                    error = (body or {}).get('error') or {}
                    raise ModelsUnavailable(error.get('code') or f'models_http_{response.status}')
                return body
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise ModelsUnavailable('models_unreachable') from None
