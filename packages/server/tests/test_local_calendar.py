import copy
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from aihub_server.config import DEFAULT
from aihub_tools.local_calendar import calendar_answer
from aihub_tools.tool_chat import chat


class CalendarTests(unittest.TestCase):
    def test_weekday_uses_clock_and_handles_day_boundaries(self):
        now=datetime(2026,10,29,0,5,tzinfo=timezone(timedelta(hours=8)))
        for text in ('今天星期几？','你知道今天星期几吗？','请问今天是周几啊','上海今天星期几？'):
            self.assertEqual(calendar_answer(text,now),'今天是2026年10月29日，星期四。')
        self.assertIn('星期三',calendar_answer('昨天星期几',now))
        self.assertIn('2026年10月30日，星期五',calendar_answer('明天是周几',now))
        self.assertIn('2026年10月29日',calendar_answer('今天几月几号',now))

    def test_politeness_wrappers_do_not_hide_a_calendar_question(self):
        # Found by the 895-case daily-conversation corpus: 96 phrasings like these
        # fell through to the planner instead of the host clock.
        now=datetime(2026,10,29,0,5,tzinfo=timezone(timedelta(hours=8)))
        for text in ('麻烦你，今天星期几','麻烦你，请问今日星期几','我想问一下，今天是几月几号',
                     '今天星期几，谢谢','麻烦你，今天几号','现在是周几','告诉我现在的日期'):
            answer=calendar_answer(text,now)
            self.assertIsNotNone(answer,text)
            self.assertIn('2026年10月29日',answer,text)

    def test_english_date_questions_are_answered_in_english(self):
        now=datetime(2026,10,29,0,5,tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(calendar_answer('what day is it today',now),'Today is 2026-10-29, Thu.')
        self.assertEqual(calendar_answer('麻烦你，what day is it today',now),'Today is 2026-10-29, Thu.')

    def test_does_not_swallow_weather_or_calendar_discussions(self):
        for text in ('上海今天天气怎么样','今天星期几，顺便查上海天气','解释星期几是什么意思',
                     '把今天星期几翻译成英文','写首关于星期一的诗','明天会下雨吗','伦敦今天星期几','请解释什么是CPU',
                     '麻烦你，打开卧室的灯','我想问一下，上海今天天气怎么样'):
            self.assertIsNone(calendar_answer(text))


class CalendarPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_planners_bypass_weather_and_clear_pending_city(self):
        for planner in ('rex','llm'):
            cfg=copy.deepcopy(DEFAULT);cfg['tools'].update(planner=planner,default_city='上海')
            p=SimpleNamespace(config=cfg,_previous_tool_plan={'tool':'weather','arguments':{'city':'上海'}})
            with patch('aihub_tools.tool_chat.calendar_answer',return_value='今天是2026年10月29日，星期四。'), \
                 patch('aihub_tools.tool_chat.CommonToolsClient',side_effect=AssertionError('No MCP')):
                reply=[item async for item in chat(p,[{'role':'user','content':'今天星期几？'}])]
            self.assertEqual(reply,['今天是2026年10月29日，星期四。'])
            self.assertIsNone(p._previous_tool_plan)
