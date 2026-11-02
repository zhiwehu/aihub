"""Private, immutable local backups. Device writes still require browser validation."""
import asyncio
import hashlib
import json
import os
import re
import stat
import struct
import time
import uuid
from pathlib import Path
from aiohttp import web

MAGIC = b'VOICEHUB-DEVICE/1\n'
MAGIC_V2 = b'VOICEHUB-DEVICE/2\n'
MAX_SIZE = 33 * 1024 * 1024
ID = re.compile(r'[0-9]{20}-[a-f0-9]{32}')
HEX = re.compile(r'[a-f0-9]{64}')
MAC = re.compile(r'(?:[A-Fa-f0-9]{2}:){5}[A-Fa-f0-9]{2}')
# Only regions this project can overwrite are backed up, so a backup stays
# small enough to take before every connection setup.
REGIONS = {'table': (0x8000, 4096), 'otadata': (0xd000, 0x2000), 'nvs': (0x9000, 0x4000),
           'app0': (0x20000, 0x3F0000), 'app1': (0x410000, 0x3F0000)}
KINDS = {'settings': ('table', 'otadata', 'nvs'), 'full': ('table', 'otadata', 'nvs', 'app0', 'app1')}


def metadata(body):
    """Validate a stored backup and return its metadata.

    Version 1 is a complete 16/32MB image; version 2 lists the regions it
    carries with a digest each. Both must describe one coherent device.
    """
    if body.startswith(MAGIC_V2):
        return metadata_v2(body)
    if not body.startswith(MAGIC) or not len(MAGIC) + 4 < len(body) <= MAX_SIZE:
        raise ValueError('invalid_device_backup')
    length = struct.unpack_from('<I', body, len(MAGIC))[0]
    if not 1 <= length <= 4096 or len(MAGIC) + 4 + length >= len(body):
        raise ValueError('invalid_device_backup')
    start = len(MAGIC) + 4
    value = json.loads(body[start:start + length])
    if not isinstance(value, dict) or not MAC.fullmatch(value.get('mac', '')):
        raise ValueError('invalid_device_backup')
    if any(not isinstance(value.get(key), str) or not HEX.fullmatch(value[key]) for key in ('sha256', 'layout', 'current_sha256')):
        raise ValueError('invalid_device_backup')
    data = memoryview(body)[start + length:]
    if len(data) != {'16MB': 16 << 20, '32MB': 32 << 20}.get(value.get('flashSize'), 0):
        raise ValueError('invalid_device_backup')
    if hashlib.sha256(data).hexdigest() != value['sha256'] or hashlib.sha256(data[0x8000:0x8000 + 3072]).hexdigest() != value['layout']:
        raise ValueError('backup_checksum_failed')
    return value


def metadata_v2(body):
    start = len(MAGIC_V2) + 4
    if not start < len(body) <= MAX_SIZE:
        raise ValueError('invalid_device_backup')
    length = struct.unpack_from('<I', body, len(MAGIC_V2))[0]
    if not 1 <= length <= 4096 or start + length >= len(body):
        raise ValueError('invalid_device_backup')
    value = json.loads(body[start:start + length])
    if not isinstance(value, dict) or value.get('version') != 2 or value.get('kind') not in KINDS:
        raise ValueError('invalid_device_backup')
    if not MAC.fullmatch(value.get('mac', '')) or value.get('flashSize') not in ('16MB', '32MB'):
        raise ValueError('invalid_device_backup')
    if any(not isinstance(value.get(key), str) or not HEX.fullmatch(value[key]) for key in ('layout',)):
        raise ValueError('invalid_device_backup')
    if 'firmware' in value and (not isinstance(value['firmware'], str) or not HEX.fullmatch(value['firmware'])):
        raise ValueError('invalid_device_backup')
    entries = value.get('regions')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise ValueError('invalid_device_backup')
    names = []
    for item in entries:
        if not isinstance(item, dict) or item.get('name') not in REGIONS or item['name'] in names:
            raise ValueError('invalid_device_backup')
        if (item.get('address'), item.get('size')) != REGIONS[item['name']]:
            raise ValueError('invalid_device_backup')
        if not isinstance(item.get('sha256'), str) or not HEX.fullmatch(item['sha256']):
            raise ValueError('invalid_device_backup')
        names.append(item['name'])
    if sorted(names) != sorted(KINDS[value['kind']]):
        raise ValueError('invalid_device_backup')
    offset = start + length
    if offset + sum(item['size'] for item in entries) != len(body):
        raise ValueError('invalid_device_backup')
    for item in entries:
        if hashlib.sha256(memoryview(body)[offset:offset + item['size']]).hexdigest() != item['sha256']:
            raise ValueError('backup_checksum_failed')
        offset += item['size']
    return value


def device_folder(root, mac):
    folder = Path(root) / 'device-backups' / mac.replace(':', '').upper()
    for path in (folder.parent, folder):
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise OSError('invalid_backup_directory')
        path.chmod(0o700)
    return folder


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SIZE:
            raise ValueError('invalid_device_backup')
        return stream.read(MAX_SIZE + 1)


def save(root, body):
    value = metadata(body)
    folder = device_folder(root, value['mac'])
    identity = f'{time.time_ns():020d}-{uuid.uuid4().hex}'
    temporary, target = folder / (identity + '.partial'), folder / (identity + '.vhdevice')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        if read_private(temporary) != body:
            raise OSError('backup_readback_failed')
        os.replace(temporary, target)
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return identity


def latest(root, query, identity=None):
    folder = device_folder(root, query['mac'])
    paths = [folder / (identity + '.vhdevice')] if identity else sorted(folder.glob('*.vhdevice'), reverse=True)
    for path in paths:
        identity = path.stem
        if not ID.fullmatch(identity) or query.get('before') and identity >= query['before']:
            continue
        try:
            body = read_private(path)
            value = metadata(body)
            if value['mac'].upper() == query['mac'].upper() and all(value[key] == query[key] for key in ('layout', 'flashSize')):
                return identity, body
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            continue
    return None


async def backups(request):
    from .app import HUB, local_admin, same_origin
    if not local_admin(request):
        raise web.HTTPUnauthorized()
    if request.headers.get('Origin') and not same_origin(request, request.headers['Origin']):
        raise web.HTTPForbidden()
    root = request.app[HUB].root
    try:
        if request.method == 'POST':
            if request.content_type != 'application/octet-stream':
                raise ValueError('invalid_device_backup')
            body = await request.clone(client_max_size=MAX_SIZE).read()
            identity = await asyncio.to_thread(save, root, body)
            return web.json_response({'id': identity}, status=201)
        query = dict(request.query)
        if set(query) - {'mac', 'layout', 'flashSize', 'before'} or not MAC.fullmatch(query.get('mac', '')) or not HEX.fullmatch(query.get('layout', '')) or query.get('flashSize') not in ('16MB', '32MB') or 'before' in query and not ID.fullmatch(query['before']):
            raise ValueError('invalid_backup_identity')
        identity = request.match_info.get('identity')
        if identity and not ID.fullmatch(identity):
            raise ValueError('invalid_backup_identity')
        result = await asyncio.to_thread(latest, root, query, identity)
        if not result:
            return web.json_response({'error': {'code': 'backup_not_found', 'message': '这台喵伴还没有可用的自动备份。'}}, status=404)
        identity, body = result
        return web.Response(body=body, content_type='application/octet-stream', headers={'X-Backup-Id': identity})
    except (ValueError, TypeError, KeyError, UnicodeError):
        return web.json_response({'error': {'code': 'invalid_device_backup', 'message': '备份格式、设备信息或校验无效。'}}, status=400)
    except OSError:
        return web.json_response({'error': {'code': 'backup_storage_failed', 'message': '本机备份保存或读取失败，请检查磁盘空间和权限。'}}, status=507)
