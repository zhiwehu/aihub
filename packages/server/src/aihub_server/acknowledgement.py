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
    # Render only preparation verbs. Topic words come from the current request,
    # never from a model's unverified factual answer or the quoted whole question.
    if re.search(r'天气|气温|下雨|降雨',subject):
        days=[day for day in ('今天','明天','后天') if day in subject]
        topic=(days[0]+'的' if len(days)==1 else '')+'天气'
        lines=(f'我查一下{topic}。',f'我看看{topic}情况。',f'我来查查{topic}。')
    elif re.search(r'新闻|资讯',subject):
        themes=[word for word in ('科技','国际','国内','体育','财经') if word in subject]
        topic=(themes[0] if len(themes)==1 else '最近的')+'新闻'
        lines=(f'我看看{topic}。',f'我找几条{topic}。',f'我查一下{topic}。')
    elif re.search(r'日程|提醒|安排',subject):
        if re.search(r'取消|删除',subject):lines=('我来处理这条日程。','我先找一下这条日程。','我看看要取消的日程。')
        elif re.search(r'提醒我|添加|创建|设置',subject):lines=('我来看看这条提醒。','我先看看提醒的时间和事项。','我来处理这条日程。')
        else:lines=('我看看你的日程。','我查一下你的日程。','我翻一下日程记录。')
    elif re.search(r'音乐|歌曲|播放|首歌',subject):
        lines=('我找一下本地音乐。','我看看曲库里有哪些歌。','我找找适合播放的本地音乐。')
    elif re.search(r'CPU|内存|磁盘|电脑状态',subject,re.I):
        lines=('我看看电脑状态。','我查一下这台电脑的运行情况。','我看一眼当前的系统信息。')
    else:
        topic=focus if 1<=len(focus)<=8 and not re.search(r'我|你|请|什么|怎么|如何|哪些|[？?]',focus) else '这件事'
        lines=(f'我来处理{topic}。',f'我先看看{topic}。',f'我看一下{topic}怎么处理。')
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
