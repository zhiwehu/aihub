import asyncio
from unittest import IsolatedAsyncioTestCase
from types import SimpleNamespace
from aihub_server.acknowledgement import acknowledgement

class AcknowledgementTests(IsolatedAsyncioTestCase):
    async def test_timeout_falls_back_to_current_request_and_closes_generation(self):
        closed=asyncio.Event()
        async def raw_chat(*args,**kwargs):
            try:
                await asyncio.Event().wait()
                yield ''
            finally:closed.set()
        result=await acknowledgement(SimpleNamespace(raw_chat=raw_chat),[],'查询杭州天气',timeout=.01)
        self.assertIn('查询杭州天气',result)
        self.assertTrue(closed.is_set())

    async def test_premature_completion_is_rejected(self):
        async def raw_chat(*args,**kwargs):yield '已完成，结果是晴天。'
        result=await acknowledgement(SimpleNamespace(raw_chat=raw_chat),[],'查询天气')
        self.assertIn('查询天气',result)
        self.assertNotIn('已完成',result)
