import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

import psutil
from aihub_server.workspace_process import owned, stop


class WorkspaceProcessTests(TestCase):
    def test_reused_pid_and_unrelated_module_are_never_signalled(self):
        with TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'server.pid'
            process = psutil.Process(os.getpid())
            pidfile.write_text(str(process.pid))
            Path(str(pidfile) + '.identity').write_text(json.dumps({
                'pid': process.pid, 'created': process.create_time() - 10}))
            self.assertIsNone(owned(pidfile, 'aihub_server'))
            with mock.patch.object(psutil.Process, 'terminate') as terminate:
                stop(pidfile, 'aihub_server')
                terminate.assert_not_called()
            self.assertFalse(pidfile.exists())

    def test_legacy_pidfile_is_not_sufficient_proof_of_ownership(self):
        with TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'media.pid'
            pidfile.write_text(str(os.getpid()))
            self.assertIsNone(owned(pidfile, 'aihub_models'))
