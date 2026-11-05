import asyncio
from aiohttp.test_utils import TestClient, TestServer
from tests import test_web_client
from unittest import IsolatedAsyncioTestCase
from aihub_server.app import create_device_app


class DeviceCredentials(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_web_client.WebClientTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await test_web_client.WebClientTests.asyncTearDown(self)

    async def issue(self, device):
        response = await self.admin.post('/api/device-credentials', json={'device_id': device})
        self.assertEqual(response.status, 201)
        return await response.json()

    async def device_connect(self, client, token, **extra):
        ws = await client.ws_connect('/ws')
        await ws.send_json({'type':'hello', 'version':1, 'token':token, 'device_id':'forged', **extra})
        return ws, await ws.receive_json()

    async def test_binding_ota_revocation_and_legacy_compatibility(self):
        issued = await self.issue('aa:bb:cc:dd:ee:01')
        client = TestClient(TestServer(create_device_app(self.hub)))
        await client.start_server()
        try:
            ws, hello = await self.device_connect(client, issued['token'])
            self.assertEqual(hello['type'], 'hello')
            self.assertEqual(self.hub.store.owner(hello['session_id']), issued['device_id'])
            source = self.hub.store.source_for(hello['session_id'])
            self.assertEqual(source['client_instance'], 'ws-device:' + issued['device_id'])
            data = await (await client.get('/xiaozhi/ota/' + issued['token'] + '/')).json()
            self.assertEqual(data['websocket']['token'], issued['token'])
            self.assertNotIn(self.hub.auth['device_token'], str(data))
            listed = await (await self.admin.get('/api/device-credentials')).json()
            self.assertNotIn(issued['token'], str(listed))
            self.assertEqual((await client.get('/api/device-credentials')).status, 404)
            await self.admin.delete('/api/device-credentials/' + issued['id'])
            async def drain():
                async for _ in ws: pass
            await asyncio.wait_for(drain(), 1)
            self.assertTrue(ws.closed)
            retry, error = await self.device_connect(client, issued['token'])
            self.assertEqual(error['code'], 'unauthorized')
            await retry.close()
            self.assertEqual((await client.get('/xiaozhi/ota/' + issued['token'] + '/')).status, 404)
            old, hello = await self.device_connect(client, self.hub.auth['device_token'])
            self.assertEqual(hello['type'], 'hello')
            self.assertEqual(self.hub.store.owner(hello['session_id']), 'forged')
            await old.close()
        finally:
            await client.close()

    async def test_other_credentials_cannot_resume_a_bound_device_session(self):
        first, second = await self.issue('device-1'), await self.issue('device-2')
        client = TestClient(TestServer(create_device_app(self.hub)))
        await client.start_server()
        try:
            ws, hello = await self.device_connect(client, first['token'])
            await ws.close()
            for _ in range(30):
                if hello['session_id'] not in self.hub.sessions: break
                await asyncio.sleep(.01)
            for token in (second['token'], self.hub.auth['device_token']):
                other, error = await self.device_connect(client, token, session_id=hello['session_id'], resume_token=hello['resume_token'])
                self.assertEqual(error['code'], 'invalid_resume')
                await other.close()
            own, resumed = await self.device_connect(client, first['token'], session_id=hello['session_id'], resume_token=hello['resume_token'])
            self.assertEqual(resumed['session_id'], hello['session_id'])
            await own.close()
        finally:
            await client.close()

    async def test_new_provisioning_binds_a_device_without_changing_legacy_prepare(self):
        from unittest.mock import patch
        self.hub.connections.device_host='192.168.0.105'
        self.hub.connections.device_ready=True
        with patch('aihub_server.provisioning.deployment',return_value='docker'), patch('aihub_server.provisioning.interfaces',return_value=[]):
            response = await self.admin.post('/api/clients/echoear-s3/prepare',json={'device_id':'AA:BB:CC:DD:EE:01'})
            self.assertEqual(response.status,200)
            config = await response.json()
            self.assertEqual(config['device_id'],'aa:bb:cc:dd:ee:01')
            self.assertNotEqual(config['websocket']['token'],self.hub.auth['device_token'])
            self.assertIn(config['websocket']['token'],config['ota_url'])
            from aihub_server.device_credentials import authenticate
            self.assertEqual(authenticate(self.hub,config['websocket']['token'])['device_id'],config['device_id'])
            old = await (await self.admin.post('/api/clients/echoear-s3/prepare',json={})).json()
            self.assertEqual(old['websocket']['token'],self.hub.auth['device_token'])

    async def test_replacement_preserves_identity_and_browser_credentials_are_not_device_credentials(self):
        from aihub_server.device_credentials import authenticate
        first = await self.issue('device-rotation')
        replacement = await self.issue('device-rotation')
        digest = self.hub.store.db.execute('SELECT digest FROM device_credentials WHERE id=?',(first['id'],)).fetchone()[0]
        self.assertNotEqual(digest,first['token'])
        client = TestClient(TestServer(create_device_app(self.hub)))
        await client.start_server()
        try:
            ws, hello = await self.device_connect(client,replacement['token'])
            self.assertEqual(self.hub.store.source_for(hello['session_id'])['client_instance'],'ws-device:device-rotation')
            await self.admin.delete('/api/device-credentials/'+first['id'])
            self.assertIsNone(authenticate(self.hub,first['token']))
            self.assertIsNotNone(authenticate(self.hub,replacement['token']))
            other, error = await self.device_connect(client,self.first['token'])
            self.assertEqual(error['code'],'unauthorized')
            await other.close()
            await ws.close()
        finally:
            await client.close()
        response=await self.admin.post('/api/device-credentials',json={'device_id':'invalid/device'})
        self.assertEqual(response.status,400)
