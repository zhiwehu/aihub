"""Command-line switches for headless and server-only deployments."""
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from aihub_server import __main__ as cli


class ClientListenerFlagTests(TestCase):
    def _run(self, argv):
        with TemporaryDirectory() as tmp, \
                mock.patch.object(cli, 'create_app', return_value={}) as create, \
                mock.patch.object(cli.web, 'run_app'), \
                mock.patch.object(sys, 'argv', ['aihub-server', '--data', tmp, *argv]):
            cli.main()
        return create

    def test_web_client_listener_is_on_loopback_by_default(self):
        create = self._run([])
        self.assertEqual(create.call_args.kwargs['client_host'], '127.0.0.1')

    def test_no_client_skips_the_web_client_listener(self):
        create = self._run(['--no-client'])
        self.assertIsNone(create.call_args.kwargs['client_host'])
