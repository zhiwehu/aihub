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

    async def test_logged_misleading_feedback_never_reaches_the_user(self):
        cases=[
            ('今天天气怎么样？','我得先查查天气，你所在的城市是哪里呀？'),
            ('今天天气怎么样？','抱歉，我无法获取实时天气信息。'),
            ('最近有什么新闻？','最近有多个科技公司发布新品，引发广泛关注。'),
            ('最近有什么新闻？','刚查到，合肥新站区将建智慧社区，提升居民生活便利性，具体进展稍后更新。'),
        ]
        for request,bad in cases:
            with self.subTest(bad=bad):
                async def raw_chat(*args,**kwargs):yield bad
                result=await acknowledgement(SimpleNamespace(raw_chat=raw_chat),[],request)
                self.assertNotEqual(result,bad)
                for forbidden in ('刚查到','新品','智慧社区','无法获取','城市是哪里'):
                    self.assertNotIn(forbidden,result)
                self.assertIn(request.strip('？'),result)

    async def test_structured_focus_must_be_a_literal_part_of_current_request(self):
        async def raw_chat(*args,**kwargs):yield '{"focus":"合肥新站区将建智慧社区","variant":0}'
        result=await acknowledgement(SimpleNamespace(raw_chat=raw_chat),[], '最近有什么新闻？')
        self.assertNotIn('智慧社区',result)
        self.assertIn('最近有什么新闻',result)

    async def test_valid_focus_and_variant_are_rendered_without_model_prose(self):
        async def raw_chat(*args,**kwargs):yield '{"focus":"杭州天气","variant":1}'
        result=await acknowledgement(SimpleNamespace(raw_chat=raw_chat),[], '查询杭州天气')
        self.assertIn('杭州天气',result)
        self.assertIn('核对',result)
        self.assertNotIn('{',result)
