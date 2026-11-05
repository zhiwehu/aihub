import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock


class LinuxConfigurationTests(TestCase):
    def test_http_profile_uses_explicit_models_and_never_overwrites_existing_settings(self):
        script = Path(__file__).parents[3] / 'deploy/linux/configure.py'
        spec = importlib.util.spec_from_file_location('linux_configure', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            vad = root / 'vad.onnx'
            vad.write_bytes(b'test-path-only')
            output = root / 'settings.json'
            args = ['configure', '--output', str(output), '--vad-model', str(vad), '--tts-voice', 'voice']
            for kind in ('asr', 'llm', 'tts'):
                args += ['--' + kind + '-url', 'http://127.0.0.1:1234/v1', '--' + kind + '-model', kind + '-actual-id']
            with mock.patch('sys.argv', args):
                module.main()
                saved = output.read_bytes()
                config = json.loads(saved)
                self.assertTrue(all(config[k]['provider'] == 'http' for k in ('asr', 'llm', 'tts')))
                self.assertEqual(config['tts']['voice'], 'voice')
                self.assertFalse(config['tools']['music'])
                self.assertEqual(config['tools']['planner'], 'llm')
                with self.assertRaises(FileExistsError):
                    module.main()
                self.assertEqual(output.read_bytes(), saved)
