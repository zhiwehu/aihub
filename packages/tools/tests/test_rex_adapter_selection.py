import json
import tempfile
import unittest
from pathlib import Path

from aihub_tools.rex_planner_worker import DEFAULT_ADAPTER, active_adapter


class ActiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'adapters'/'rex-everyday-v5').mkdir(parents=True)
        (self.root/'adapters'/'rex-mcp-router-r16-slots-v2').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def marker(self,value):
        (self.root/'rex-planner-active.json').write_text(json.dumps({'adapter':value}))

    def test_without_a_marker_the_core_slot_adapter_is_used(self):
        self.assertEqual(Path(active_adapter(self.root)),(self.root/DEFAULT_ADAPTER).resolve())

    def test_workspace_relative_and_data_relative_values_resolve_to_the_same_adapter(self):
        # The evaluation script records "data/adapters/…" because it runs from the
        # workspace; the worker resolves against the data root.
        self.marker('data/adapters/rex-everyday-v5')
        workspace_relative = Path(active_adapter(self.root))
        self.marker('adapters/rex-everyday-v5')
        self.assertEqual(workspace_relative,Path(active_adapter(self.root)))
        self.assertEqual(workspace_relative,(self.root/'adapters'/'rex-everyday-v5').resolve())

    def test_an_adapter_outside_the_data_root_is_refused(self):
        self.marker('../elsewhere/adapter')
        with self.assertRaises(ValueError):
            active_adapter(self.root)
