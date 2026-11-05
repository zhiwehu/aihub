"""Administrator-issued device bindings; raw credentials are returned once."""
import hashlib
import re
import secrets
import time
import uuid

from aiohttp import web


def device_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w.:-]{1,80}', value):
        raise ValueError('invalid_device_id')
    return value.lower() if re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}', value) else value


def authenticate(hub, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        return None
    row = hub.store.db.execute('SELECT id,device_id FROM device_credentials WHERE digest=?',
                              (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return dict(row) if row else None


def issue(hub, identity):
    identity = device_id(identity)
    if hub.store.db.execute('SELECT count(*) FROM device_credentials').fetchone()[0] >= 100:
        raise ValueError('device_credential_limit')
    token = secrets.token_urlsafe(32)
    record = {'id': uuid.uuid4().hex, 'device_id': identity, 'created': time.time()}
    hub.store.db.execute('INSERT INTO device_credentials VALUES (?,?,?,?)',
                         (record['id'], identity, hashlib.sha256(token.encode()).hexdigest(), record['created']))
    hub.store.db.commit()
    return {**record, 'token': token}


async def api(request):
    from .app import HUB
    hub = request.app[HUB]
    if request.method == 'GET':
        return web.json_response({'devices': [dict(row) for row in hub.store.db.execute(
            'SELECT id,device_id,created FROM device_credentials ORDER BY created DESC LIMIT 100')]})
    if request.method == 'DELETE':
        identity = request.match_info['identity']
        hub.store.db.execute('DELETE FROM device_credentials WHERE id=?', (identity,))
        hub.store.db.commit()
        for session in list(hub.sessions.values()):
            if getattr(session, 'device_credential_id', None) == identity:
                await session.transport_socket.close(code=1008, message=b'credential revoked')
        return web.json_response({'ok': True})
    body = await request.json()
    if not isinstance(body, dict) or set(body) != {'device_id'}:
        raise web.HTTPBadRequest()
    try:
        value = issue(hub, body['device_id'])
    except ValueError as exc:
        return web.json_response({'error': {'code': str(exc)}}, status=409 if str(exc) == 'device_credential_limit' else 400)
    connections = hub.connections
    if connections.device_ready:
        host, port = connections.device_host, connections.device_port
        value['websocket'] = {'url': f'ws://{host}:{port}/xiaozhi/v1/', 'token': value['token'], 'version': 1}
        value['ota_url'] = f'http://{host}:{port}/xiaozhi/ota/{value["token"]}/'
    return web.json_response(value, status=201, headers={'Cache-Control': 'no-store'})
