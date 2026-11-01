import os
import unittest
from pathlib import Path
from unittest.mock import patch

from aihub_tools.rex_planner import RexPlanner, worker_env


class RexPlannerEnvTests(unittest.TestCase):
    def test_worker_is_told_which_data_root_holds_the_models(self):
        # The worker resolves data_root() from its own cwd (aihub-tools/src after
        # the split), so the server's root has to travel in the environment.
        with patch.dict(os.environ,{'AIHUB_DATA_ROOT':'/ambient/elsewhere','PATH':'/usr/bin'}):
            env=worker_env(Path('/workspace/data'))
            self.assertEqual(env['AIHUB_DATA_ROOT'],'/workspace/data')
            self.assertEqual(env['PATH'],'/usr/bin')

    def test_worker_environment_keeps_credentials_out(self):
        with patch.dict(os.environ,{'VOICE_LLM_KEY':'secret','HF_TOKEN':'secret'}):
            env=worker_env(Path('/workspace/data'))
            self.assertNotIn('VOICE_LLM_KEY',env)
            self.assertNotIn('HF_TOKEN',env)
            self.assertNotIn('AIHUB_DATA_ROOT',worker_env())

    def test_planner_remembers_the_root_it_was_built_with(self):
        self.assertEqual(RexPlanner(Path('/workspace/data')).root,Path('/workspace/data'))
        self.assertIsNone(RexPlanner().root)
