import tempfile
from unittest import IsolatedAsyncioTestCase

from aiohttp.test_utils import TestClient, TestServer
from aihub_server.app import HUB, create_app
from aihub_server.web_client import create_client_app
from tests.test_sessions import Pipeline


class WebClientTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.admin = TestClient(TestServer(create_app(self.tmp.name, pipeline_factory=lambda c,h,r: Pipeline())))
        await self.admin.start_server()
        self.hub = self.admin.app[HUB]
        self.client = TestClient(TestServer(create_client_app(self.hub)))
        await self.client.start_server()
        self.first = await (await self.admin.post('/api/client-credentials', json={'name': 'first'})).json()
        self.second = await (await self.admin.post('/api/client-credentials', json={'name': 'second'})).json()

    async def asyncTearDown(self):
        await self.client.close()
        await self.admin.close()
        self.tmp.cleanup()

    def auth(self, identity=None):
        return {'Authorization': 'Bearer ' + (identity or self.first)['token']}

    async def connect(self, identity=None, **extra):
        identity = identity or self.first
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'type': 'hello', 'version': 1, 'token': identity['token'], **extra})
        return ws, await ws.receive_json()

    async def test_client_listener_has_no_management_routes_or_local_auth_bypass(self):
        self.assertEqual((await self.client.get('/client/v1/recordings')).status, 401)
        for path in ['/api/config', '/api/services', '/api/events', '/api/client-credentials']:
            self.assertEqual((await self.client.get(path, headers=self.auth())).status, 404)
        self.assertEqual((await self.client.get('/client/v1/recordings', headers=self.auth())).status, 200)

    async def test_websocket_identity_is_server_assigned_and_resume_is_scoped(self):
        ws, hello = await self.connect(device_id='forged-device')
        sid = hello['session_id']
        self.assertEqual(self.hub.store.owner(sid), 'web:' + self.first['id'])
        await ws.close()
        import asyncio
        for _ in range(20):
            if sid not in self.hub.sessions:
                break
            await asyncio.sleep(.01)
        other, error = await self.connect(self.second, session_id=sid, resume_token=hello['resume_token'])
        self.assertEqual(error['type'], 'error')
        self.assertEqual(error['code'], 'invalid_resume')
        await other.close()

    async def test_other_clients_cannot_read_recordings_transcripts_audio_or_minutes(self):
        record = self.hub.recordings.start('1' * 32, 'web:' + self.first['id'], 'client')
        rid = record.id
        self.hub.store.session('1' * 32, 'web:' + self.first['id'])
        self.hub.store.source('1' * 32, 'web', self.first['id'])
        self.hub.recordings.stop(rid, 'test')
        for suffix in ['', '/audio', '/transcript', '/minutes', '/minutes/' + '2' * 32 + '/export']:
            response = await self.client.get('/client/v1/recordings/' + rid + suffix, headers=self.auth(self.second))
            self.assertEqual(response.status, 404, suffix)
        rows = await (await self.client.get('/client/v1/recordings', headers=self.auth(self.second))).json()
        self.assertEqual(rows['recordings'], [])
        own = await (await self.client.get('/client/v1/recordings', headers=self.auth())).json()
        self.assertEqual(own['recordings'][0]['id'], rid)
        self.assertEqual((await self.client.post('/client/v1/recordings/' + rid + '/stop', headers=self.auth(self.second))).status, 404)

    async def test_revoked_credential_no_longer_authenticates(self):
        await self.admin.delete('/api/client-credentials/' + self.first['id'])
        self.assertEqual((await self.client.get('/client/v1/recordings', headers=self.auth())).status, 401)

    async def test_cross_origin_websocket_is_denied(self):
        response = await self.client.get('/ws', headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(response.status, 403)

    async def test_pause_resume_validated_and_audio_is_not_written_while_paused(self):
        ws, hello = await self.connect()
        session = self.hub.sessions[hello['session_id']]
        record = await session.start_recording('client')
        record.write(b'\0\0' * 1600)
        await session.pause_recording(True)
        record.write(b'\0\0' * 1600)
        self.assertEqual(record.samples, 1600)
        with self.assertRaisesRegex(ValueError, 'invalid_recording_transition'):
            await session.pause_recording(True)
        await session.pause_recording(False)
        record.write(b'\0\0' * 1600)
        self.assertEqual(record.samples, 3200)
        await session.stop_recording('client', speak=False)
        metadata = self.hub.recordings.get(record.id)
        self.assertEqual(metadata['client_type'], 'web')
        self.assertEqual(metadata['client_instance'], self.first['id'])
        with self.assertRaisesRegex(ValueError, 'recording_not_active'):
            await session.pause_recording(False)
        await ws.close()

    async def test_static_client_is_independent_and_contains_no_admin_api(self):
        response = await self.client.get('/demo/')
        self.assertEqual(response.status, 200)
        script = await (await self.client.get('/demo/assets/client.js')).text()
        self.assertNotIn('/api/', script)
        self.assertNotIn('admin_token', script)
        self.assertIn('/client/v1/', script)

    async def test_client_credential_cannot_authenticate_on_device_listener(self):
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'type': 'hello', 'version': 1, 'token': self.hub.auth['device_token']})
        error = await ws.receive_json()
        self.assertEqual(error['code'], 'unauthorized')
        await ws.close()

    async def test_sources_and_admin_device_filters_do_not_guess_legacy_ownership(self):
        self.hub.store.session('1' * 32, 'legacy-device')
        self.hub.store.session('2' * 32, 'web:' + self.first['id'])
        self.hub.store.source('2' * 32, 'web', self.first['id'])
        rows = await (await self.admin.get('/api/sessions?client_type=unknown')).json()
        self.assertEqual([r['id'] for r in rows], ['1' * 32])
        rows = await (await self.admin.get('/api/sessions?device_id=legacy-device')).json()
        self.assertEqual([r['id'] for r in rows], ['1' * 32])
        legacy = self.hub.recordings.start('1' * 32, 'legacy-device', 'test')
        self.hub.recordings.stop(legacy.id, 'test')
        self.assertEqual(self.hub.recordings.get(legacy.id)['client_type'], 'unknown')
        response = await self.client.get('/client/v1/recordings/' + legacy.id, headers=self.auth())
        self.assertEqual(response.status, 404)

    async def test_explicit_cross_origin_policy_allows_only_configured_origins(self):
        from unittest import mock
        with mock.patch.dict('os.environ', {'AIHUB_CLIENT_ORIGINS': 'https://client.example'}):
            client = TestClient(TestServer(create_client_app(self.hub)))
            await client.start_server()
            try:
                response = await client.options('/client/v1/recordings', headers={'Origin': 'https://client.example'})
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://client.example')
                response = await client.get('/client/v1/recordings', headers={**self.auth(), 'Origin': 'https://client.example'})
                self.assertEqual(response.status, 200)
                response = await client.get('/client/v1/recordings', headers={**self.auth(), 'Origin': 'https://evil.example'})
                self.assertEqual(response.status, 403)
            finally:
                await client.close()

    async def test_loopback_origin_port_omission_needs_same_origin_browser_metadata(self):
        host = self.client.make_url('/').host
        response = await self.client.get('/demo/assets/client.js', headers={
            'Origin': 'http://' + host, 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(response.status, 200)
        response = await self.client.get('/demo/assets/client.js', headers={'Origin': 'http://' + host})
        self.assertEqual(response.status, 403)
