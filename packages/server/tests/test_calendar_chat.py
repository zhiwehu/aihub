from datetime import date,datetime,timedelta
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from aihub_tools.calendar_store import CalendarStore
from aihub_tools.calendar_chat import route,resolve_date
from aihub_server.config import DEFAULT
from aihub_tools.tools import ToolNotice
class CalendarChatTests(unittest.IsolatedAsyncioTestCase):
 async def test_missing_time_and_recurring_request_do_not_create_events(self):
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):yield json.dumps({'title':'开会','date':'明天'})
   p=Pipeline();stream=route(p,[{'role':'user','content':'明天提醒我开会'}]);self.assertIsInstance(await anext(stream),ToolNotice)
   replies=[v async for v in stream];self.assertIn('几点',replies[-1]);self.assertFalse(store.load()['events'])
   replies=[v async for v in route(p,[{'role':'user','content':'每天提醒我开会'}])];self.assertIn('单次',replies[-1]);self.assertFalse(store.load()['events'])
   self.assertIsNone(route(p,[{'role':'user','content':'今天星期几'}]))
 def test_relative_date_uses_host_calendar_and_next_week_is_unambiguous(self):
  today=date(2026,10,30)
  self.assertEqual(resolve_date('明天',today),date(2026,10,31));self.assertEqual(resolve_date('下周一',today),date(2026,11,2));self.assertEqual(resolve_date('周一',today),date(2026,11,2))
 async def test_missing_time_can_be_completed_in_next_turn_without_losing_title(self):
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT;calls=0
    async def raw_chat(self,*args,**kwargs):
     self.calls+=1
     yield json.dumps({'title':'开会','date':'明天'} if self.calls==1 else {'title':'开会','date':'明天','time':'15:00'})
   p=Pipeline();[v async for v in route(p,[{'role':'user','content':'明天提醒我开会'}])]
   self.assertTrue(p._calendar_pending)
   self.assertIsNone(route(p,[{'role':'user','content':'今天星期几'}]))
   [v async for v in route(p,[{'role':'user','content':'下午三点'}])]
   self.assertEqual(len(store.load()['events']),1);self.assertIsNone(p._calendar_pending)
 async def test_model_operation_metadata_must_match_host_cancellation_intent(self):
  from datetime import timezone
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root);future=datetime.now(timezone.utc)+timedelta(days=1);event=store.create('取快递',future.isoformat(),remind_minutes=0)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):yield json.dumps({'operation':'cancel','title':'取快递'})
   p=Pipeline();[v async for v in route(p,[{'role':'user','content':'取消取快递的提醒'}])]
   self.assertEqual(store.get(event['event_id'])['status'],'cancelled')
   async def invalid(*args,**kwargs):yield json.dumps({'operation':'create','title':'其他事项','date':'明天','time':'15:00'})
   p.raw_chat=invalid;[v async for v in route(p,[{'role':'user','content':'查一下明天日程'}])]
   self.assertEqual(len(store.load()['events']),1)

 async def test_tool_discussion_does_not_request_calendar_work(self):
  with tempfile.TemporaryDirectory() as root:
   p=SimpleNamespace(runtime=SimpleNamespace(calendar=CalendarStore(root)),session_id='one',config=DEFAULT)
   for text in ('我刚才三个工具嘛：天气、新闻、日程。','但这个里面是要有优化的。','这三个工具包括日程。'):
    with self.subTest(text=text):self.assertIsNone(route(p,[{'role':'user','content':text}]))

 async def test_today_and_tomorrow_query_uses_both_days_without_model_guesses(self):
  from zoneinfo import ZoneInfo
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root);now=datetime.now(ZoneInfo(store.settings()['timezone']))
   for days,title in ((0,'下班'),(1,'开会')):
    start=(now+timedelta(days=days)).replace(hour=23,minute=59,second=0,microsecond=0)
    store.create(title,start.isoformat(),remind_minutes=0)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):raise AssertionError('explicit period must not require model slots');yield ''
   replies=[v async for v in route(Pipeline(),[{'role':'user','content':'我今天和明天一共有哪些日程？'}])]
   self.assertIn('查到2项日程',replies[-1]);self.assertIn('下班',replies[-1]);self.assertIn('开会',replies[-1])

 async def test_weekday_query_keeps_specific_day_instead_of_whole_week(self):
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root);calls=[]
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):calls.append(True);yield '{"date":"下周一"}'
   replies=[v async for v in route(Pipeline(),[{'role':'user','content':'下周一有哪些日程？'}])]
   started=next(v for v in replies if getattr(v,'phase',None)=='started')
   begin=datetime.fromisoformat(started.arguments['range_start']);end=datetime.fromisoformat(started.arguments['range_end'])
   self.assertEqual(calls,[True]);self.assertEqual(begin.weekday(),0);self.assertEqual((end-begin).days,1)

 async def test_timer_triggered_reminder_is_rejected_without_calendar_state(self):
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):raise AssertionError('timer reminder must not call the calendar model')
   p=Pipeline();replies=[v async for v in route(p,[{'role':'user','content':'倒计时结束的时候，告诉我，提醒我去跑步。'}])]
   self.assertIn('计时器结束提醒暂不支持',replies[-1]);self.assertIsNone(p._calendar_pending)
   self.assertFalse(store.load()['events'])

 async def test_new_topic_clears_a_pending_calendar_question(self):
  with tempfile.TemporaryDirectory() as root:
   store=CalendarStore(root)
   class Pipeline:
    runtime=SimpleNamespace(calendar=store,data_root=root);session_id='one';device_id='fixture';config=DEFAULT
    async def raw_chat(self,*args,**kwargs):yield json.dumps({'title':'开会','date':'明天'})
   p=Pipeline();[v async for v in route(p,[{'role':'user','content':'明天提醒我开会'}])]
   self.assertTrue(p._calendar_pending)
   self.assertIsNone(route(p,[{'role':'user','content':'下个月想买一台洗衣机'}]))
   self.assertIsNone(p._calendar_pending)
   self.assertFalse(store.load()['events'])
