import hashlib
import json
import io
import os
import struct
import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from aihub_server.app import create_app

MAC = 'AA:BB:CC:DD:EE:FF'
DATA = b'\xff' * (16 * 1024 * 1024)
LAYOUT = hashlib.sha256(DATA[0x8000:0x8000 + 3072]).hexdigest()
META = dict(mac=MAC, layout=LAYOUT, flashSize='16MB', sha256=hashlib.sha256(DATA).hexdigest(), current_sha256='a' * 64)
HEADER = json.dumps(META).encode()
BACKUP = b'VOICEHUB-DEVICE/1\n' + struct.pack('<I', len(HEADER)) + HEADER + DATA
QUERY = dict(mac=MAC, layout=LAYOUT, flashSize='16MB')
URL = '/api/clients/echoear-s3/backups'

MAGIC_V2 = b'VOICEHUB-DEVICE/2\n'
REGIONS = {'table': (0x8000, 4096), 'otadata': (0xD000, 0x2000), 'nvs': (0x9000, 0x4000),
           'app0': (0x20000, 0x3F0000), 'app1': (0x410000, 0x3F0000)}
KINDS = {'settings': ('table', 'otadata', 'nvs'), 'full': ('table', 'otadata', 'nvs', 'app0', 'app1')}
LAYOUT_V2 = hashlib.sha256(DATA[0x8000:0x8000 + 3072]).hexdigest()


def v2_backup(kind='settings', mutate=None):
    region_data = {name: (DATA[REGIONS[name][0]:REGIONS[name][0] + REGIONS[name][1]]) for name in KINDS[kind]}
    if mutate:
        mutate(region_data)
    entries = [dict(name=name, address=REGIONS[name][0], size=REGIONS[name][1],
                    sha256=hashlib.sha256(region_data[name]).hexdigest()) for name in KINDS[kind]]
    meta = dict(version=2, kind=kind, mac=MAC, layout=LAYOUT_V2, flashSize='16MB', firmware='b' * 64, regions=entries)
    header = json.dumps(meta).encode()
    return MAGIC_V2 + struct.pack('<I', len(header)) + header + b''.join(region_data[name] for name in KINDS[kind])

class DeviceBackups(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp = tempfile.TemporaryDirectory()
  self.client = TestClient(TestServer(create_app(self.tmp.name)))
  await self.client.start_server()
 async def asyncTearDown(self):
  await self.client.close()
  self.tmp.cleanup()
 async def save(self, body=BACKUP, **kwargs):
  return await self.client.post(URL, data=io.BytesIO(body), headers={'Content-Type': 'application/octet-stream', **kwargs})
 async def test_automatic_save_readback_and_persistence(self):
  response = await self.save()
  self.assertEqual(response.status, 201)
  identity = (await response.json())['id']
  files = list(Path(self.tmp.name).glob('device-backups/*/*.vhdevice'))
  self.assertEqual(len(files), 1)
  self.assertEqual(files[0].read_bytes(), BACKUP)
  self.assertEqual(os.stat(files[0]).st_mode & 0o777, 0o600)
  self.assertEqual(os.stat(files[0].parent).st_mode & 0o777, 0o700)
  await self.client.close()
  self.client = TestClient(TestServer(create_app(self.tmp.name)))
  await self.client.start_server()
  result = await self.client.get(URL + '/latest', params=QUERY)
  self.assertEqual(result.status, 200)
  self.assertEqual(result.headers['X-Backup-Id'], identity)
  self.assertEqual(result.headers['Cache-Control'], 'no-store')
  self.assertEqual(await result.read(), BACKUP)
 async def test_recent_corrupt_backup_is_skipped_without_overwriting_older_copy(self):
  first = await self.save(); first_id = (await first.json())['id']
  second = await self.save(); second_id = (await second.json())['id']
  self.assertNotEqual(first_id, second_id)
  latest = await self.client.get(URL + '/latest', params=QUERY)
  self.assertEqual(latest.headers['X-Backup-Id'], second_id)
  older = await self.client.get(URL + '/latest', params={**QUERY, 'before': second_id})
  self.assertEqual(older.headers['X-Backup-Id'], first_id)
  path = next(Path(self.tmp.name).glob('device-backups/*/' + second_id + '.vhdevice'))
  with path.open('r+b') as stream:
   stream.seek(-1, 2); stream.write(b'\x00')
  latest = await self.client.get(URL + '/latest', params=QUERY)
  self.assertEqual(latest.status, 200)
  self.assertEqual(latest.headers['X-Backup-Id'], first_id)
  self.assertEqual(await latest.read(), BACKUP)
 async def test_invalid_backup_identity_paths_and_cross_origin_are_rejected(self):
  self.assertEqual((await self.save(BACKUP[:-1])).status, 400)
  self.assertEqual((await self.save(Origin='https://foreign.invalid')).status, 403)
  self.assertEqual((await self.save(Host='foreign.invalid')).status, 401)
  self.assertEqual(list(Path(self.tmp.name).glob('device-backups/*/*.vhdevice')), [])
  self.assertEqual((await self.client.get(URL+'/latest', params={**QUERY, 'mac':'../private'})).status, 400)
  await self.save()
  for query in [{**QUERY, 'mac':'11:22:33:44:55:66'}, {**QUERY, 'layout':'b'*64}, {**QUERY, 'flashSize':'32MB'}]:
   self.assertEqual((await self.client.get(URL+'/latest', params=query)).status, 404)
  self.assertEqual((await self.client.get(URL+'/latest', params={**QUERY, 'before':'../../auth.json'})).status, 400)
  self.assertEqual((await self.client.get(URL+'/latest', params=QUERY, headers={'Host':'foreign.invalid'})).status, 401)


class DeviceBackupsV2(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp = tempfile.TemporaryDirectory()
  self.client = TestClient(TestServer(create_app(self.tmp.name)))
  await self.client.start_server()
 async def asyncTearDown(self):
  await self.client.close()
  self.tmp.cleanup()
 async def save(self, body):
  return await self.client.post(URL, data=io.BytesIO(body), headers={'Content-Type': 'application/octet-stream'})
 async def test_settings_backup_round_trips_and_matches_the_device_identity(self):
  body = v2_backup('settings')
  response = await self.save(body)
  self.assertEqual(response.status, 201)
  identity = (await response.json())['id']
  latest = await self.client.get(URL + '/latest', params=QUERY)
  self.assertEqual(latest.headers['X-Backup-Id'], identity)
  self.assertEqual(await latest.read(), body)
  path = next(Path(self.tmp.name).glob('device-backups/*/' + identity + '.vhdevice'))
  self.assertEqual(path.stat().st_size, len(body))
  self.assertLess(len(body), 64 * 1024, 'a settings backup must stay small enough to take every time')
 async def test_full_backup_is_stored_with_both_application_slots(self):
  body = v2_backup('full')
  self.assertEqual((await self.save(body)).status, 201)
  header=struct.unpack_from('<I',body,len(MAGIC_V2))[0]
  self.assertEqual(len(body),len(MAGIC_V2)+4+header+4096+0x2000+0x4000+2*0x3F0000)
  self.assertGreater(len(body),2*0x3F0000,'both application slots are carried')
  self.assertEqual((await self.client.get(URL + '/latest', params=QUERY)).status, 200)
 async def test_tampered_region_payload_is_rejected(self):
  body = v2_backup('settings')
  tampered = body[:-1] + bytes([body[-1] ^ 0xFF])
  self.assertEqual((await self.save(tampered)).status, 400)
  self.assertEqual(list(Path(self.tmp.name).glob('device-backups/*/*.vhdevice')), [])
 async def test_region_set_must_match_the_declared_kind_and_canonical_ranges(self):
  body = v2_backup('settings')
  start = len(MAGIC_V2) + 4
  length = struct.unpack_from('<I', body, len(MAGIC_V2))[0]
  meta = json.loads(body[start:start + length])
  payload = body[start + length:]
  for change in ({'name': 'app0', 'address': REGIONS['app0'][0], 'size': REGIONS['app0'][1], 'sha256': 'c' * 64},
                 {'name': 'nvs', 'address': 0, 'size': REGIONS['nvs'][1], 'sha256': 'c' * 64}):
   for altered in (dict(meta, regions=meta['regions'] + [change]), dict(meta, regions=meta['regions'][:-1] + [change])):
    header = json.dumps(altered).encode()
    candidate = MAGIC_V2 + struct.pack('<I', len(header)) + header + payload
    self.assertEqual((await self.save(candidate)).status, 400)
 async def test_a_backup_without_a_verifiable_table_layout_is_rejected(self):
  body = v2_backup('settings')
  start = len(MAGIC_V2) + 4
  length = struct.unpack_from('<I', body, len(MAGIC_V2))[0]
  meta = json.loads(body[start:start + length])
  for broken in (dict(meta, layout='short'), dict(meta, version=3), dict(meta, flashSize='8MB'), dict(meta, mac='not-a-mac')):
   header = json.dumps(broken).encode()
   candidate = MAGIC_V2 + struct.pack('<I', len(header)) + header + body[start + length:]
   self.assertEqual((await self.save(candidate)).status, 400)
