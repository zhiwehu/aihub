"""Separate client ingress: no administrator routes or loopback trust."""
import hashlib
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from aihub_common import env_value

CLIENT_SOCKETS = web.AppKey('client_sockets', set)
CLIENT_ONLY = web.AppKey('client_only', bool)
CLIENT_ID = web.RequestKey('client_id', str)


def authenticate(hub, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        return None
    row = hub.store.db.execute('SELECT id FROM client_credentials WHERE digest=?',
                              (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return row[0] if row else None


def client_entry(request):
    from .app import HUB
    configured=env_value('CLIENT_PUBLIC_URL')
    if configured:
        parsed=urlsplit(configured)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('invalid_client_public_url')
        return configured
    port=env_value('CLIENT_PUBLIC_PORT') or getattr(request.app[HUB],'client_port',None)
    if port is None:return None
    port=int(port)
    if not 1 <= port <= 65535:raise ValueError('invalid_client_public_port')
    host=urlsplit('//'+request.host).hostname
    if ':' in host:host='['+host+']'
    return f'{request.scheme}://{host}:{port}/demo/'


async def credentials(request):
    from .app import HUB
    hub = request.app[HUB]
    if request.method == 'GET':
        return web.json_response({'client_url':client_entry(request),'clients': [dict(row) for row in hub.store.db.execute(
            'SELECT id,name,created FROM client_credentials ORDER BY created DESC LIMIT 100')]})
    if request.method == 'DELETE':
        identity = request.match_info['identity']
        hub.store.db.execute('DELETE FROM client_credentials WHERE id=?', (identity,))
        hub.store.db.commit()
        for session in list(hub.sessions.values()):
            if getattr(session, 'client_instance', None) == identity:
                await session.transport_socket.close(code=1008, message=b'credential revoked')
        return web.json_response({'ok': True})
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'name'} or not isinstance(data['name'], str) or not 1 <= len(data['name']) <= 80:
        raise web.HTTPBadRequest()
    if hub.store.db.execute('SELECT count(*) FROM client_credentials').fetchone()[0] >= 100:
        raise web.HTTPConflict(text='Client credential limit reached')
    identity, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
    hub.store.db.execute('INSERT INTO client_credentials VALUES (?,?,?,?)',
                         (identity, data['name'], hashlib.sha256(token.encode()).hexdigest(), time.time()))
    hub.store.db.commit()
    return web.json_response({'id': identity, 'token': token, 'name': data['name']}, status=201)


def owns_session(hub, sid, client_id):
    if not isinstance(sid, str) or not re.fullmatch('[a-f0-9]{32}', sid):
        return False
    source = hub.store.source_for(sid)
    return source['client_type'] == 'web' and source['client_instance'] == client_id


async def client_api(request):
    from .app import HUB
    from .recording_api import recording_api
    from .minutes_proxy import minutes_proxy
    hub, identity = request.app[HUB], request[CLIENT_ID]
    path = request.path
    if path == '/client/v1/sessions':
        return web.json_response({'sessions': [s for s in hub.store.sessions(client_type='web', client_instance=identity)
                                  if owns_session(hub, s['id'], identity)]})
    if path == '/client/v1/operations':
        fields=('id','session_id','turn_id','label','status','delivery','created','updated','text','last_tool')
        return web.json_response({'operations': [{k:r[k] for k in fields if k in r}
            for r in hub.operations.recent() if r.get('kind')!='progress' and owns_session(hub,r.get('session_id'),identity)]})
    if 'sid' in request.match_info:
        sid = request.match_info['sid']
        if not owns_session(hub, sid, identity):
            raise web.HTTPNotFound()
        if path.endswith('/tool-calls'):
            from .app import tool_calls
            return await tool_calls(request)
        return web.json_response(hub.store.messages(sid))
    if path == '/client/v1/meeting-templates':
        return await minutes_proxy(request)
    if path == '/client/v1/recordings':
        if request.method == 'GET':
            return web.json_response({'recordings': [r for r in hub.recordings.list()
                                     if owns_session(hub, r.get('session_id'), identity)]})
        body = await request.json()
        if not isinstance(body, dict) or not owns_session(hub, body.get('session_id'), identity):
            raise web.HTTPNotFound()
        return await recording_api(request)
    rid = request.match_info.get('identity', '')
    if not re.fullmatch('[a-f0-9]{32}', rid):
        raise web.HTTPNotFound()
    recording = hub.recordings.get(rid)
    if not recording or not owns_session(hub, recording.get('session_id'), identity):
        raise web.HTTPNotFound()
    if '/minutes' in path:
        return await minutes_proxy(request)
    if path == '/client/v1/recordings/' + rid:
        return web.json_response({'recording': recording})
    return await recording_api(request)


def create_client_app(hub):
    from .app import HUB, gateway, same_origin
    loopback_proxy = env_value('CLIENT_LOOPBACK_PROXY') == '1'
    allowed_origins = set(filter(None, (value.strip() for value in env_value('CLIENT_ORIGINS', '').split(','))))
    # Explicit opt-in for a trusted LAN: any page origin may call the token-gated
    # client API. The credential, not the origin, remains the access boundary.
    allow_any_origin = '*' in allowed_origins
    def origin_allowed(origin):
        return bool(origin) and (allow_any_origin or origin in allowed_origins)
    @web.middleware
    async def guard(request, handler):
        origin = request.headers.get('Origin')
        if origin and not same_origin(request, origin, loopback_proxy=loopback_proxy) and not origin_allowed(origin):
            raise web.HTTPForbidden()
        if request.method == 'OPTIONS' and request.path.startswith('/client/'):
            response = web.Response(status=204)
            response.headers.update({'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                                     'Access-Control-Allow-Headers': 'Authorization, Content-Type'})
            if origin_allowed(origin):
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Vary'] = 'Origin'
            return response
        if request.path.startswith('/client/'):
            token = request.headers.get('Authorization', '').removeprefix('Bearer ')
            identity = authenticate(hub, token)
            if not identity:
                raise web.HTTPUnauthorized()
            request[CLIENT_ID] = identity
        try:
            response = await handler(request)
        except (ValueError, TypeError, KeyError):
            response = web.json_response({'error': {'code': 'invalid_request'}}, status=400)
        response.headers.update({
            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if origin_allowed(origin):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
        return response

    app = web.Application(middlewares=[guard], client_max_size=65536)
    app[HUB], app[CLIENT_ONLY] = hub, True
    app[CLIENT_SOCKETS] = set()
    async def shutdown(app):
        import asyncio
        await asyncio.gather(*(ws.close(code=1001, message=b'client listener shutdown')
                               for ws in list(app[CLIENT_SOCKETS])), return_exceptions=True)
    app.on_shutdown.append(shutdown)
    app.router.add_get('/ws', gateway)
    prefix = '/client/v1'
    app.router.add_get(prefix + '/operations', client_api)
    app.router.add_get(prefix + '/sessions', client_api)
    app.router.add_get(prefix + '/sessions/{sid}/tool-calls', client_api)
    app.router.add_get(prefix + '/sessions/{sid}/messages', client_api)
    app.router.add_get(prefix + '/meeting-templates', client_api)
    for method in ('GET', 'POST'):
        app.router.add_route(method, prefix + '/recordings', client_api)
    app.router.add_get(prefix + '/recordings/{identity}', client_api)
    for suffix in ('audio', 'transcript', 'speech', 'speech-map', 'clean', 'ready'):
        app.router.add_get(prefix + '/recordings/{identity}/' + suffix, client_api)
    app.router.add_post(prefix + '/recordings/{identity}/stop', client_api)
    app.router.add_get(prefix + '/recordings/{identity}/minutes', client_api)
    app.router.add_post(prefix + '/recordings/{identity}/minutes', client_api)
    app.router.add_get(prefix + '/recordings/{identity}/minutes/{job_id}', client_api)
    app.router.add_get(prefix + '/recordings/{identity}/minutes/{job_id}/export', client_api)
    static = Path(env_value('CLIENT_ROOT') or hub.root / 'client-web')
    async def index(request):
        if not (static / 'index.html').is_file():
            return web.Response(text='Web client artifact is not installed; set AIHUB_CLIENT_ROOT.', status=503)
        return web.FileResponse(static / 'index.html')
    app.router.add_get('/', index)
    app.router.add_get('/demo/', index)
    if static.is_dir():
        app.router.add_static('/demo/assets', static)
    return app
