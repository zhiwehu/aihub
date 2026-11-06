import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from aihub_server.app import create_app, HUB
from tests import test_mqtt_security


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/'mqtt/config.json'
        self.path.parent.mkdir()
        self.cfg = test_mqtt_security.MqttSecurityTests().config()
        self.path.write_text(json.dumps(self.cfg)); self.path.chmod(0o600)
        self.client = TestClient(TestServer(create_app(self.root)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_status_masks_secrets_and_marks_websocket_protocol(self):
        r = await self.client.get('/api/connections')
        self.assertEqual(r.status,200)
        data = await r.json()
        self.assertEqual(data['mqtt']['state'],'stopped')
        self.assertTrue(data['mqtt']['configured'])
        self.assertNotIn('password',json.dumps(data))
        self.assertNotIn('provision_token',json.dumps(data))
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'type':'hello','version':1,'device_id':'web-test',
            'audio':{'format':'pcm_s16le','sample_rate':16000}})
        await ws.receive_json()
        data = await (await self.client.get('/api/connections')).json()
        self.assertEqual(data['devices'][0]['protocol'],'websocket_v1')
        await ws.close()

    async def test_device_bind_host_listens_on_all_interfaces_and_advertises_lan_address(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        client = TestClient(TestServer(create_app(root, device_host='127.0.0.1',
                                                  device_bind='0.0.0.0', device_port=18766)))
        try:
            await client.start_server()
            hub = client.server.app[HUB]
            self.assertTrue(hub.connections.device_ready)
            self.assertEqual(hub.connections.device_host, '127.0.0.1')
            self.assertEqual(hub.connections.device_port, 18766)
            data = await (await client.get('/api/connections')).json()
            self.assertEqual(data['websocket']['device_ready'], True)
        finally:
            await client.close()
            tmp.cleanup()

    async def test_save_preserves_credentials_and_rejects_secret_changes(self):
        data = await (await self.client.get('/api/connections')).json()
        value = data['mqtt']['config']
        value['broker_port'] = 1884
        r = await self.client.put('/api/connections/mqtt',json=value)
        self.assertEqual(r.status,200)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['broker_port'],1884)
        self.assertEqual(saved['devices'],self.cfg['devices'])
        self.assertEqual(saved['password'],self.cfg['password'])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
        value['password']='replacement'
        self.assertEqual((await self.client.put('/api/connections/mqtt',json=value)).status,400)

    async def test_controls_stop_is_idempotent_and_cross_origin_denied(self):
        self.assertEqual((await self.client.post('/api/connections/mqtt/stop')).status,200)
        self.assertEqual((await self.client.post('/api/connections/mqtt/shell')).status,400)
        r = await self.client.post('/api/connections/mqtt/start',headers={'Origin':'https://foreign.invalid'})
        self.assertEqual(r.status,403)

    async def test_missing_optional_mqtt_extra_still_renders_the_client_page(self):
        # Without the [mqtt] extra the transport modules cannot import. The
        # console asks for /api/connections on page load, so a 500 there blanks
        # the whole 客户端接入 page even though the web client never needs MQTT.
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules,{'aihub_server.mqtt_service':None}):
            r = await self.client.get('/api/connections')
            self.assertEqual(r.status,200)
            data = await r.json()
            self.assertEqual(data['mqtt']['error'],'mqtt_dependency_missing')
            self.assertTrue(data['mqtt']['dependency_missing'])
            self.assertFalse(data['mqtt']['configured'])
            self.assertEqual([c['id'] for c in data['clients']],['web','echoear-s3'])
            self.assertEqual((await self.client.post('/api/connections/mqtt/start')).status,409)
            self.assertEqual((await self.client.put('/api/connections/mqtt',json={})).status,409)
        self.assertFalse(self.client.app[HUB].connections.status()['mqtt']['dependency_missing'])

    async def test_bind_failure_does_not_break_console(self):
        from unittest.mock import patch, AsyncMock
        with patch('aihub_server.mqtt_service.MqttService.start',new=AsyncMock(side_effect=OSError(49,'unavailable'))):
            r = await self.client.post('/api/connections/mqtt/start')
            self.assertEqual(r.status,409)
        data = await (await self.client.get('/api/connections')).json()
        self.assertEqual(data['mqtt']['error'],'udp_address_unavailable')
        self.assertEqual((await self.client.get('/api/status')).status,200)

    async def test_device_listener_controls_keep_console_and_other_connections_alive(self):
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        r=await self.client.put('/api/connections/websocket',json={'host':'127.0.0.1','port':port})
        self.assertEqual(r.status,200)
        r=await self.client.post('/api/connections/websocket/start')
        self.assertEqual(r.status,200)
        ws=await self.client.ws_connect('/ws')
        await ws.send_json({'type':'hello','version':1,'device_id':'console-peer'})
        await ws.receive_json()
        r=await self.client.get('/api/clients/echoear-s3/connection?protocol=xiaozhi_websocket')
        self.assertEqual(r.status,200)
        self.assertEqual((await r.json())['websocket']['token'],self.client.app[HUB].auth['device_token'])
        self.assertIn('attachment',r.headers['Content-Disposition'])
        self.assertEqual((await self.client.put('/api/connections/websocket',json={'host':'127.0.0.1','port':port})).status,409)
        await self.client.post('/api/connections/websocket/stop')
        self.assertFalse(ws.closed)
        await ws.send_json({'type':'ping'})
        import asyncio
        async with asyncio.timeout(1):
            while (await ws.receive_json())['type'] != 'pong': pass
        await ws.close()
        self.assertEqual((await self.client.get('/api/status')).status,200)

    async def test_firmware_download_requires_a_matching_registered_artifact(self):
        import hashlib
        root=self.root/'firmware/echoear-s3';root.mkdir(parents=True)
        r=await self.client.get('/api/connections')
        self.assertEqual([c['id'] for c in (await r.json())['clients']],['web','echoear-s3'])
        self.assertEqual((await self.client.get('/api/clients/echoear-s3/firmware')).status,404)
        binary=b'\xe9'+b'\0'*1023
        (root/'application.bin').write_bytes(binary)
        manifest={'board':'echoear-s3','kind':'application','file':'application.bin',
            'version':'test','sha256':hashlib.sha256(binary).hexdigest()}
        (root/'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual((await self.client.get('/api/clients/echoear-s3/firmware')).status,200)
        (root/'application.bin').write_bytes(binary+b'changed')
        self.assertEqual((await self.client.get('/api/clients/echoear-s3/firmware')).status,404)

    async def test_management_and_connection_download_require_administrator(self):
        from unittest.mock import patch
        with patch('aihub_server.app.admin',return_value=False):
            for path in ('/api/connections','/api/clients/echoear-s3/connection?protocol=xiaozhi_websocket'):
                self.assertEqual((await self.client.get(path)).status,401)
