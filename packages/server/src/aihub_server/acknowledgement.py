"""A bounded, context-specific first response for app-owned background work."""
import asyncio
import contextlib
import re


async def acknowledgement(pipeline, history, request, timeout=1.2):
    subject=re.sub(r'\s+', ' ', request or '').strip('，。！？,.!? ')[:36]
    fallback=f'关于“{subject}”，我先处理，有结果就告诉你。' if subject else '我先处理这件事，有结果就告诉你。'
    if not hasattr(pipeline,'raw_chat'):return fallback
    prompt=('用户的请求将由后台处理。请结合最后一条请求和必要的对话上下文，用一句自然中文立即回应，'
            '具体提到这次要处理的事情。说明你会开始处理，不要声称已完成或已经查到结果，'
            '像面对面聊天，避免“已收到”“处理任务”等生硬措辞。不要解释工具、后台或队列，不问新问题，不输出列表、思考过程或固定套话。最多45个汉字。')
    try:
        output=''
        async with asyncio.timeout(timeout), contextlib.aclosing(pipeline.raw_chat(history[-8:],system_prompt=prompt,max_tokens=72)) as source:
            async for part in source:
                output+=part
                if len(output)>100:break
        output=re.sub(r'<think>.*?</think>','',output,flags=re.S).strip().strip('"')
        if not output or len(output)>80 or '<think>' in output or re.search(r'已完成|已经完成|执行成功|查到了|结果是',output):return fallback
        return re.sub(r'\s+',' ',output)
    except asyncio.CancelledError:raise
    except Exception:return fallback
