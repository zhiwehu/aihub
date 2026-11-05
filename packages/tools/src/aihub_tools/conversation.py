"""Ordinary conversation must not claim tool actions that never ran."""
import contextlib
import re

_ACTIONS=r'(?:设置|设定|添加|创建|取消|删除|记录|同步|优化|修改|更新|安排|完成)'
_UNEXECUTED=re.compile(r'(?:已经?|已为.{0,8}).{0,4}'+_ACTIONS+
    r'|(?:帮你|为你|为您|给你).{0,4}'+_ACTIONS+r'(?:好|完|了|成功)')


async def reply(pipeline, history, instructions):
    instructions+='\n本轮没有执行任何工具或程序修改。不得声称已设置、已记录、已同步、已优化或已修改；不要模仿或输出回复状态标记。'
    # Session speech also waits for sentence boundaries. Validate each sentence
    # before either the client or TTS can receive a false completion claim.
    pending=''
    async with contextlib.aclosing(pipeline.raw_chat(history,system_prompt=instructions)) as source:
        async for part in source:
            pending+=part
            if len(pending)>5000:
                yield '这轮没有执行设置或修改操作。';return
            while match:=re.search(r'[。！？!?\n]',pending):
                sentence,pending=pending[:match.end()],pending[match.end():]
                sentence=sentence.replace('（回复被打断）','')
                if _UNEXECUTED.search(sentence):
                    yield '这轮没有执行设置或修改操作。';return
                yield sentence
        if pending:
            pending=pending.replace('（回复被打断）','')
            yield '这轮没有执行设置或修改操作。' if _UNEXECUTED.search(pending) else pending
