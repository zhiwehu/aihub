import os
import unittest
from pathlib import Path
from unittest.mock import patch

from aihub_tools.rex_planner import RexPlanner, worker_env
from aihub_tools.rex_planner_worker import runtime_root


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

    def test_a_container_can_point_the_worker_at_a_linux_runtime(self):
        # The vendored <data>/rex-runtime is a macOS pip tree; containers mount a
        # Linux build elsewhere and select it through AIHUB_REX_RUNTIME.
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('AIHUB_REX_RUNTIME',None)
            self.assertEqual(runtime_root(Path('/workspace/data')),
                             Path('/workspace/data/rex-runtime'))
            os.environ['AIHUB_REX_RUNTIME']='/data/rex-runtime-linux'
            self.assertEqual(runtime_root(Path('/workspace/data')),
                             Path('/data/rex-runtime-linux'))
            self.assertEqual(worker_env(Path('/workspace/data'))['AIHUB_REX_RUNTIME'],
                             '/data/rex-runtime-linux')
