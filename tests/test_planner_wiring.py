import tempfile
import unittest
from pathlib import Path

from aihub_server.app import HUB, create_app


class PlannerWiringTests(unittest.TestCase):
    def test_the_local_planner_uses_the_hub_data_root(self):
        # The worker subprocess cannot infer it: <repo>/src/data is not the data
        # directory, so the planner must be constructed with hub.root.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'data'
            app = create_app(root)
            hub = app[HUB]
            try:
                self.assertEqual(hub.planner.root,hub.root)
            finally:
                hub.store.close()
