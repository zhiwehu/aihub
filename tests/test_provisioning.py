import unittest
import tempfile
import socket
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from aihub_server.app import create_app,HUB
from aihub_server.provisioning import interfaces

class Provisioning(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.client=TestClient(TestServer(create_app(self.tmp.name)));await self.client.start_server()
 async def asyncTearDown(self):
  await self.client.close();self.tmp.cleanup()
 async def test_prepare_starts_authenticated_listener_and_is_idempotent(self):
  hub=self.client.app[HUB]
  with socket.socket() as probe:probe.bind(('127.0.0.1',0));hub.connections.device_port=probe.getsockname()[1]
  with patch('aihub_server.provisioning.interfaces',return_value=[{'interface':'fixture','address':'127.0.0.1'}]),patch('aihub_server.provisioning.default_address',return_value='127.0.0.1'):
   r=await self.client.post('/api/clients/echoear-s3/prepare',json={});self.assertEqual(r.status,200)
   cfg=await r.json();runner=hub.connections.device_runner
   self.assertTrue(hub.connections.device_ready);self.assertEqual(cfg['websocket']['token'],hub.auth['device_token'])
   self.assertEqual(r.headers['Cache-Control'],'no-store')
   self.assertEqual((await self.client.post('/api/clients/echoear-s3/prepare',json={})).status,200)
   self.assertIs(hub.connections.device_runner,runner)
   ota=await self.client.session.get(cfg['ota_url']);self.assertEqual(ota.status,200)
   denied=await self.client.session.get(cfg['ota_url'].replace(hub.auth['device_token'],'wrong'));self.assertEqual(denied.status,404)
 async def test_ambiguous_network_requires_selection_and_unknown_fields_rejected(self):
  choices=[{'interface':'en0','address':'192.168.1.10'},{'interface':'en1','address':'10.0.0.10'}]
  with patch('aihub_server.provisioning.interfaces',return_value=choices),patch('aihub_server.provisioning.default_address',return_value=None):
   r=await self.client.post('/api/clients/echoear-s3/prepare',json={});self.assertEqual(r.status,409);self.assertEqual((await r.json())['interfaces'],choices)
   self.assertEqual((await self.client.post('/api/clients/echoear-s3/prepare',json={'host':'8.8.8.8'})).status,400)
   self.assertEqual((await self.client.post('/api/clients/echoear-s3/prepare',json={'password':'never-send'})).status,400)
  self.assertFalse(self.client.app[HUB].connections.device_ready)
 async def test_cross_origin_and_untrusted_host_cannot_enable_listener(self):
  self.assertEqual((await self.client.post('/api/clients/echoear-s3/prepare',json={},headers={'Origin':'https://foreign.invalid'})).status,403)
  self.assertEqual((await self.client.post('/api/clients/echoear-s3/prepare',json={},headers={'Host':'foreign.invalid'})).status,401)
  self.assertFalse(self.client.app[HUB].connections.device_ready)

 async def test_container_prepare_uses_the_advertised_host(self):
  hub=self.client.app[HUB]
  hub.connections.device_host='192.168.0.105';hub.connections.device_ready=True
  with patch('aihub_server.provisioning.deployment',return_value='docker'), \
       patch('aihub_server.provisioning.interfaces',return_value=[]):
   r=await self.client.post('/api/clients/echoear-s3/prepare',json={})
  self.assertEqual(r.status,200)
  cfg=await r.json()
  self.assertEqual(cfg['host'],'192.168.0.105')
  self.assertEqual(cfg['websocket']['url'],'ws://192.168.0.105:8766/xiaozhi/v1/')
  self.assertEqual(cfg['ota_url'],'http://192.168.0.105:8766/xiaozhi/ota/'+hub.auth['device_token']+'/')

 async def test_container_never_offers_its_bridge_address(self):
  # Found in production: the wizard picked the container's eth0 and wrote 172.19.0.2
  # into the device's NVS, which no device can reach.
  with patch('aihub_server.provisioning.deployment',return_value='docker'):
   self.assertEqual(interfaces(),[])
   r=await self.client.post('/api/clients/echoear-s3/prepare',json={})
   self.assertEqual(r.status,409)
   body=await r.json()
   self.assertEqual(body['error']['code'],'no_local_network')
   self.assertIn('容器',body['error']['message'])
 async def test_idle_listener_moves_off_an_old_network_but_active_devices_are_preserved(self):
  from types import SimpleNamespace
  from unittest.mock import AsyncMock
  from aihub_server.connections import ConnectionError
  hub=self.client.app[HUB];connections=hub.connections
  connections.device_ready=True;connections.device_host='172.20.10.3'
  async def action(value):
   if value=='stop':connections.device_ready=False
   if value=='start':connections.device_ready=True
  connections.websocket_action=AsyncMock(side_effect=action)
  async def save(value):connections.device_host=value['host']
  connections.save_websocket=AsyncMock(side_effect=save)
  with patch('aihub_server.provisioning.interfaces',return_value=[{'interface':'en0','address':'10.159.134.213','label':'Wi-Fi'}]):
   r=await self.client.post('/api/clients/echoear-s3/prepare',json={});self.assertEqual(r.status,200);self.assertEqual((await r.json())['host'],'10.159.134.213')
   self.assertEqual([call.args[0] for call in connections.websocket_action.call_args_list],['stop','start'])
   connections.websocket_action.reset_mock();connections.device_host='172.20.10.3'
   hub.sessions['active']=SimpleNamespace(device_listener=True,closed=False)
   try:
    r=await self.client.post('/api/clients/echoear-s3/prepare',json={});self.assertEqual(r.status,409);self.assertEqual((await r.json())['error']['code'],'listener_on_other_network')
    connections.websocket_action.assert_not_called()
   finally:hub.sessions.pop('active')

class PhysicalNetworks(unittest.TestCase):
 def test_fake_ethernet_tunnels_are_excluded_from_setup_choices(self):
  from types import SimpleNamespace as NS
  from aihub_server.provisioning import interfaces
  addrs={name:[NS(family=socket.AF_INET,address=address)] for name,address in [('feth2177','172.23.55.123'),('feth2916','10.147.18.10'),('en0','10.159.134.213'),('utun8','10.126.126.234')]}
  with patch('aihub_server.provisioning.hardware_ports',return_value={'en0':'Wi-Fi'}),patch('aihub_server.provisioning.psutil.net_if_addrs',return_value=addrs),patch('aihub_server.provisioning.psutil.net_if_stats',return_value={}):
   self.assertEqual(interfaces(),[{'interface':'en0','address':'10.159.134.213','label':'Wi-Fi'}])

class CurrentWifi(unittest.IsolatedAsyncioTestCase):
 async def test_ssid_is_best_effort_and_never_returns_a_password_or_assumes_band(self):
  import subprocess
  from types import SimpleNamespace
  tmp=tempfile.TemporaryDirectory();client=TestClient(TestServer(create_app(tmp.name)));await client.start_server()
  try:
   with patch('aihub_server.provisioning.sys.platform','darwin'),patch('aihub_server.provisioning.hardware_ports',return_value={'en0':'Wi-Fi'}),patch('aihub_server.provisioning.subprocess.run',return_value=SimpleNamespace(stdout='Current Wi-Fi Network: TestWifi\n')) as run:
    response=await client.get('/api/clients/echoear-s3/current-wifi');self.assertEqual(response.status,200)
    self.assertEqual(await response.json(),{'ssid':'TestWifi','band':None});self.assertEqual(run.call_args.args[0],['/usr/sbin/networksetup','-getairportnetwork','en0'])
   with patch('aihub_server.provisioning.sys.platform','darwin'),patch('aihub_server.provisioning.hardware_ports',return_value={'en0':'Wi-Fi'}),patch('aihub_server.provisioning.subprocess.run',side_effect=subprocess.TimeoutExpired('networksetup',2)):
    self.assertEqual((await(await client.get('/api/clients/echoear-s3/current-wifi')).json())['ssid'],None)
  finally:await client.close();tmp.cleanup()
