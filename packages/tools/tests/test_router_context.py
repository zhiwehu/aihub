import unittest
from types import SimpleNamespace

from aihub_tools.tool_chat import chat
from aihub_tools.tools import catalogue


class RouterContextTests(unittest.IsolatedAsyncioTestCase):
    """The LLM router must not be handed the whole conversation.

    Regression: with a chatty transcript the small local model answered as the
    assistant instead of emitting a routing object, so every ordinary question
    ended in 「这次没能正确确定查询内容」.
    """

    def pipeline(self, seen, router_payload='{"tool":null,"arguments":{}}'):
        tools = {tool['name']: True for tool in catalogue()}
        tools.update(default_city='合肥', news_source='bbc', news_limit=3,
                     timeout_seconds=20, planner='llm', music_directory='',
                     file_directory='')

        class Pipeline:
            config = {'tools': tools, 'system_prompt': '你是小宝。'}
            runtime = SimpleNamespace(operations=None, skills=None, extensions=None,
                                      planner=None, workflows=None, data_root=None)

            async def raw_chat(self, history, *, system_prompt=None, max_tokens=None):
                seen.append((system_prompt or '', history))
                if '工具路由器' in (system_prompt or ''):
                    yield router_payload
                else:
                    yield '我在听。'

        return Pipeline()

    async def test_router_sees_only_the_current_request(self):
        seen = []
        history = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好呀。'},
            {'role': 'user', 'content': '今天天气怎么样'},
            {'role': 'assistant', 'content': '有结果了，今天合肥有雨。'},
            {'role': 'user', 'content': '能听见我说话吗？'},
        ]
        async for _ in chat(self.pipeline(seen), history):
            pass
        router = [h for prompt, h in seen if '工具路由器' in prompt]
        self.assertEqual(router, [[{'role': 'user', 'content': '能听见我说话吗？'}]])

    async def test_followups_still_carry_the_previous_user_turn(self):
        seen = []
        history = [
            {'role': 'user', 'content': '今天天气怎么样'},
            {'role': 'assistant', 'content': '有结果了，今天合肥有雨。'},
            {'role': 'user', 'content': '那明天呢'},
        ]
        async for _ in chat(self.pipeline(seen), history):
            pass
        router = [h for prompt, h in seen if '工具路由器' in prompt]
        self.assertEqual([m['content'] for m in router[0]], ['今天天气怎么样', '那明天呢'])

    async def test_basic_news_skips_unavailable_rex_and_uses_configured_source(self):
        from unittest.mock import AsyncMock
        from aihub_tools.rex_planner import PlannerError
        from aihub_tools.tools import ToolStatus
        import contextlib
        seen=[];pipeline=self.pipeline(seen)
        pipeline.config['tools']['planner']='rex'
        pipeline.config['tools']['news_source']='chinanews'
        pipeline.runtime.planner=SimpleNamespace(plan=AsyncMock(side_effect=PlannerError('planner_unavailable')))
        started=None
        async with contextlib.aclosing(chat(pipeline,[{'role':'user','content':'最近有什么新闻'}])) as source:
            async for item in source:
                if isinstance(item,ToolStatus) and item.phase=='started':started=item;break
        self.assertIsNotNone(started)
        self.assertEqual(started.name,'news');self.assertEqual(started.arguments,{'source':'chinanews','limit':3})
        self.assertEqual(started.planner,'news_rules');pipeline.runtime.planner.plan.assert_not_awaited()
        self.assertEqual(seen,[])

    async def test_unavailable_rex_falls_back_to_bounded_llm_for_specific_news(self):
        from unittest.mock import AsyncMock
        from aihub_tools.rex_planner import PlannerError
        from aihub_tools.tools import ToolStatus
        import contextlib
        seen=[];pipeline=self.pipeline(seen,'{"tool":"news","arguments":{"keyword":"科技"}}')
        pipeline.config['tools']['planner']='rex'
        pipeline.runtime.planner=SimpleNamespace(plan=AsyncMock(side_effect=PlannerError('planner_unavailable')))
        started=None
        async with contextlib.aclosing(chat(pipeline,[{'role':'user','content':'帮我查一下科技方面的新闻'}])) as source:
            async for item in source:
                if isinstance(item,ToolStatus) and item.phase=='started':started=item;break
        self.assertIsNotNone(started);self.assertEqual(started.arguments['keyword'],'科技')
        self.assertEqual(started.planner,'llm_fallback')
        self.assertEqual(len([p for p,h in seen if '工具路由器' in p]),1)

    async def test_both_planners_failing_is_reported_as_a_failure_not_completed_work(self):
        from unittest.mock import AsyncMock
        from aihub_tools.rex_planner import PlannerError
        from aihub_tools.tools import ToolStatus
        pipeline=self.pipeline([],router_payload='not-json');pipeline.config['tools']['planner']='rex'
        pipeline.runtime.planner=SimpleNamespace(plan=AsyncMock(side_effect=PlannerError('planner_unavailable')))
        values=[v async for v in chat(pipeline,[{'role':'user','content':'帮我查一下科技方面的新闻'}])]
        self.assertTrue(any(isinstance(v,ToolStatus) and v.phase=='failed' and v.code=='planning_failed' for v in values))
        self.assertFalse(any(isinstance(v,ToolStatus) and v.phase=='started' for v in values))
