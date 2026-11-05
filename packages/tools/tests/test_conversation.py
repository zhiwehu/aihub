from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from aihub_tools.conversation import reply
from aihub_tools.extension_routing import is_conversational_turn

class ConversationTests(IsolatedAsyncioTestCase):
    async def test_unexecuted_actions_are_blocked_even_across_stream_chunks(self):
        async def raw_chat(*args,**kwargs):
            for part in ('已','优化响应逻辑','，将更快速调用工具。','（回复被打断）'):yield part
        text=''.join([v async for v in reply(SimpleNamespace(raw_chat=raw_chat),[], '普通交流')])
        self.assertEqual(text,'这轮没有执行设置或修改操作。')

    async def test_plain_conversation_remains_faithful_without_status_markers(self):
        async def raw_chat(*args,**kwargs):yield '我明白你的意思。（回复被打断）（回复被打断）'
        text=''.join([v async for v in reply(SimpleNamespace(raw_chat=raw_chat),[], '普通交流')])
        self.assertEqual(text,'我明白你的意思。')

    def test_feedback_is_conversation_but_real_tool_requests_are_not(self):
        for text in ('还要优化。','我刚才三个工具嘛：天气、新闻、日程。','不用说了'):
            self.assertTrue(is_conversational_turn(text),text)
        for text in ('查看明天的日程','今天天气怎么样','下午六点提醒我下班'):
            self.assertFalse(is_conversational_turn(text),text)

    async def test_capability_explanation_is_not_a_completion_claim(self):
        async def raw_chat(*args,**kwargs):yield '我可以帮你设置提醒，但需要明确日期和时间。'
        text=''.join([v async for v in reply(SimpleNamespace(raw_chat=raw_chat),[], '普通交流')])
        self.assertEqual(text,'我可以帮你设置提醒，但需要明确日期和时间。')
