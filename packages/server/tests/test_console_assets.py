import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from aihub_server.app import create_app


class ConsoleAssetTests(unittest.IsolatedAsyncioTestCase):
    """The console and the USB flasher are separate repositories."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base/'data'; self.root.mkdir()
        web = base/'web'; web.mkdir()
        (web/'index.html').write_text('<!doctype html><title>console</title>')
        (web/'app.js').write_text('export {};')
        flash = base/'flash'; flash.mkdir()
        (flash/'echoear-installer.js').write_text('window.AIHubFlasher={};')
        self.env = patch.dict('os.environ',{'AIHUB_WEB_ROOT':str(web),'AIHUB_FIRMWARE_ROOT':str(flash)})
        self.env.start()
        self.client = TestClient(TestServer(create_app(self.root)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close(); self.env.stop(); self.tmp.cleanup()

    async def test_console_serves_the_flashing_module_from_aihub_firmware(self):
        self.assertEqual((await self.client.get('/')).status,200)
        r = await self.client.get('/firmware/echoear-installer.js')
        self.assertEqual(r.status,200)
        self.assertEqual(r.content_type,'text/javascript')
        self.assertIn('AIHubFlasher',await r.text())
        self.assertEqual((await self.client.get('/firmware/../data/settings.json')).status,404)


class ConsoleWithoutFlasherTests(unittest.IsolatedAsyncioTestCase):
    """An unset flashing directory costs the panel, never the console."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base/'data'; self.root.mkdir()
        web = base/'web'; web.mkdir()
        (web/'index.html').write_text('<!doctype html><title>console</title>')
        self.env = patch.dict('os.environ',{'AIHUB_WEB_ROOT':str(web),
            'AIHUB_FIRMWARE_ROOT':str(base/'missing-flash')})
        self.env.start()
        self.client = TestClient(TestServer(create_app(self.root)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close(); self.env.stop(); self.tmp.cleanup()

    async def test_console_still_loads_and_reports_its_clients(self):
        self.assertEqual((await self.client.get('/')).status,200)
        self.assertEqual((await self.client.get('/firmware/echoear-installer.js')).status,404)
        r = await self.client.get('/api/connections')
        self.assertEqual(r.status,200)
        self.assertEqual([c['id'] for c in (await r.json())['clients']],['web','echoear-s3'])
