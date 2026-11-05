import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

spec=importlib.util.spec_from_file_location('install_client',Path(__file__).parents[1]/'scripts/install-client.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ClientArtifactTests(TestCase):
    def test_verified_artifact_installs_and_tampered_input_does_not_overwrite_it(self):
        with TemporaryDirectory() as tmp:
            source=Path(tmp)/'release';source.mkdir()
            target=Path(tmp)/'installed'
            files={}
            for name in installer.FILES:
                data=('content for '+name).encode()
                (source/name).write_bytes(data)
                files[name]=hashlib.sha256(data).hexdigest()
            (source/'manifest.json').write_text(json.dumps({'protocol_version':1,'files':files}))
            with mock.patch('sys.argv',['install-client',str(source),'--destination',str(target)]):
                installer.main()
                previous=(target/'client.js').read_bytes()
                (source/'client.js').write_text('tampered')
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                    installer.main()
                self.assertEqual((target/'client.js').read_bytes(),previous)
