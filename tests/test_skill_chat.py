import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from aihub_tools.skills import Skills
from aihub_tools.workflows.manager import WorkflowManager
from aihub_server.config import DEFAULT
from aihub_tools.skill_chat import route
from aihub_tools.workflows.chat import candidate
from aihub_tools.tools import ToolNotice
class SkillChatTests(unittest.IsolatedAsyncioTestCase):
 async def test_slot_extraction_is_validated_before_any_file_or_mail_operation(self):
  with tempfile.TemporaryDirectory() as root:
   manager=WorkflowManager(root,lambda:DEFAULT);skills=Skills(root,manager)
   class Pipeline:
    session_id='one';runtime=SimpleNamespace(skills=skills)
    async def raw_chat(self,*args,**kwargs):yield json.dumps({'arguments':{'title':'提醒','content':{'from':'forged.result'}}})
   p=Pipeline();stream=route(p,[{'role':'user','content':'保存笔记，标题提醒'}]);first=await anext(stream);self.assertIsInstance(first,ToolNotice)
   result=[v async for v in stream];self.assertIn('参数',result[-1]);self.assertFalse(manager.recent())
   self.assertIsNone(route(p,[{'role':'user','content':'不要生成系统报告'}]));self.assertFalse(candidate('不要生成系统报告'))
   await manager.close()
