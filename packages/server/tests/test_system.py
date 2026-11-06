import tempfile
import unittest
from aiohttp.test_utils import TestClient, TestServer
from aihub_server.app import create_app
from aihub_server.system import _health_url, deployment, model_tier, snapshot


class DeploymentTests(unittest.TestCase):
    def test_explicit_environment_override_wins(self):
        self.assertEqual(deployment({'AIHUB_DEPLOYMENT': 'docker'}), 'docker')
        self.assertEqual(deployment({'AIHUB_DEPLOYMENT': 'native'}), 'native')

    def test_unknown_override_falls_back_to_detection(self):
        self.assertIn(deployment({'AIHUB_DEPLOYMENT': 'maybe'}), ('docker', 'native'))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_reports_every_section(self):
        with tempfile.TemporaryDirectory() as root:
            value = snapshot(root)
        for key in ('deployment', 'hostname', 'uptime_seconds',
                    'cpu', 'memory', 'disk', 'network', 'process'):
            self.assertIn(key, value)
        self.assertIn(value['deployment'], ('docker', 'native'))
        self.assertGreater(value['cpu']['cores'], 0)
        self.assertGreater(value['memory']['total'], 0)
        self.assertGreater(value['disk']['total'], 0)
        self.assertGreaterEqual(value['disk']['data_bytes'], 0)
        self.assertEqual(value['disk']['path'], root)

    def test_network_rates_are_non_negative(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot(root)
            value = snapshot(root)
        self.assertGreaterEqual(value['network']['rx_rate'], 0)
        self.assertGreaterEqual(value['network']['tx_rate'], 0)


class SystemApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(TestServer(create_app(self.tmp.name)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_system_endpoint_reports_the_runtime_footprint(self):
        response = await self.client.get('/api/system')
        self.assertEqual(response.status, 200)
        value = await response.json()
        self.assertIn(value['deployment'], ('docker', 'native'))
        self.assertIn('percent', value['memory'])
        self.assertIn('rx_rate', value['network'])
        self.assertIn('rss', value['process'])
        self.assertIn('model_tier', value)
        self.assertIn('app_bytes', value['disk'])

    async def test_health_url_strips_the_openai_suffix(self):
        self.assertEqual(_health_url('http://host:8781/v1'), 'http://host:8781/health')
        self.assertEqual(_health_url('http://host:8781/v1/'), 'http://host:8781/health')
        self.assertEqual(_health_url('http://host:8790'), 'http://host:8790/health')

    async def test_model_tier_survives_unreachable_services(self):
        config = {'asr': {'provider': 'http', 'url': 'http://127.0.0.1:1/v1',
                          'key_env': 'AIHUB_TEST_ASR_KEY'},
                  'llm': {'provider': 'http', 'url': 'http://127.0.0.1:2/v1',
                          'key_env': 'AIHUB_TEST_LLM_KEY'},
                  'tts': {'provider': 'http', 'url': 'http://127.0.0.1:3/v1',
                          'key_env': 'AIHUB_TEST_TTS_KEY'}}
        value = await model_tier(config, None, timeout=.5)
        self.assertEqual(value['total'], 3)
        self.assertEqual(value['reachable'], 0)
        self.assertEqual(value['rss'], 0)
        self.assertEqual([row['kind'] for row in value['processes']], ['asr', 'llm', 'tts'])
        self.assertTrue(all(not row['reachable'] and row['external'] is False for row in value['processes']))
        self.assertEqual(value['planner'], 'llm')
