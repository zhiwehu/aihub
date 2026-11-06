import tempfile
import time
import unittest
from types import SimpleNamespace
from aihub_tools.background import Operations
from aihub_tools.everyday_store import EverydayStore
from aihub_tools.timer_reminders import TimerReminders


class TimerReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ops = Operations(self.tmp.name)
        self.store = EverydayStore(self.tmp.name)
        self.sessions = {}
        self.scheduler = TimerReminders(self.tmp.name, self.ops, self.sessions, lambda: True)
        self.now = time.time()

    async def asyncTearDown(self):
        await self.ops.close()
        self.tmp.cleanup()

    def create(self):
        result = self.store.timer('start', name='tea', duration_seconds=60,
                                  device='robot', session='s1', now=self.now)
        return result['items'][0]

    async def test_offline_timer_is_expired_and_not_replayed(self):
        timer = self.create()
        await self.scheduler.tick(timer['deadline'] + 1)
        self.assertEqual(self.store.due(timer['deadline'] + 1), [])
        self.assertEqual(self.ops.recent(), [])
        self.sessions['s1'] = SimpleNamespace(id='s1', device_id='robot', closed=False, notification_ids=set())
        await self.scheduler.tick(timer['deadline'] + 2)
        self.assertEqual(self.ops.recent(), [])
        row = self.store.timer('status', name='tea', device='robot', now=timer['deadline'] + 2)['items'][0]
        self.assertEqual(row['state'], 'expired')

    async def test_connected_timer_is_queued_once(self):
        timer = self.create()
        self.sessions['s1'] = SimpleNamespace(id='s1', device_id='robot', closed=False, notification_ids=set())
        await self.scheduler.tick(timer['deadline'] + 1)
        records = self.ops.recent()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['kind'], 'timer')
        await self.scheduler.tick(timer['deadline'] + 2)
        self.assertEqual(len(self.ops.recent()), 1)
