"""Ground first feedback in the request; model output can never become a result."""
import asyncio
import contextlib
import json
import re


def feedback(request, selection=None):
    # The model may select a literal focus and wording, never supply spoken prose.
    subject=re.sub(r'\s+', ' ', request or '').strip('，。！？,.!? ')
    focus,variant=subject[:36],0
    if isinstance(selection,dict) and set(selection)=={'focus','variant'}:
        chosen=selection['focus']
        if (isinstance(chosen,str) and 1<=len(chosen)<=24 and chosen in subject
                and type(selection['variant']) is int and 0<=selection['variant']<3):
            focus,variant=chosen,selection['variant']
    topic=f'“{focus}”' if focus else '这件事'
    if re.search(r'天气|气温|下雨|降雨|新闻|资讯',subject):
        lines=(f'我先核查{topic}的相关信息，确认后再回复你。',
               f'关于{topic}，我先核对信息再回复你。',
               f'我会先核实{topic}，再向你说明结果。')
    else:
        lines=(f'关于{topic}，我先处理，确认结果后再回复你。',
               f'我先核对{topic}的相关内容，再向你说明进展。',
               f'我会按你的要求处理{topic}，再回复你确认的结果。')
    return lines[variant]


async def acknowledgement(pipeline, history, request, timeout=1.2):
    fallback=feedback(request)
    if not hasattr(pipeline,'raw_chat'):return fallback
    prompt=('你只为一条正在准备处理的请求选择回应样式，不回答用户问题。'
            '仅输出JSON对象，且只能有focus和variant两个字段。'
            'focus必须是最后一条用户请求中逐字存在的1到24字连续片段；variant为0、1或2。'
            '不要从历史回答提取事实，不输出新闻、天气、结果、能力判断、追问或任何回应正文。'
            '例如用户说“查询杭州天气”，可输出{"focus":"杭州天气","variant":1}。')
    try:
        output=''
        async with asyncio.timeout(timeout), contextlib.aclosing(pipeline.raw_chat(history[-8:],system_prompt=prompt,max_tokens=72)) as source:
            async for part in source:
                output+=part
                if len(output)>160:return fallback
        return feedback(request,json.loads(output))
    except asyncio.CancelledError:raise
    except Exception:return fallback
