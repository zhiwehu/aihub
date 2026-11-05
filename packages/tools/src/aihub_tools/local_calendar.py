"""Answer explicit local calendar questions from the host clock, without model routing."""
import re
from datetime import datetime, timedelta

# Politeness around the question is stripped before matching: 「麻烦你，今天星期几」
# and 「我想问一下，今天是几号」 are the same question. Whatever survives the strip
# still has to match the date pattern in full, so mixed requests and unrelated
# sentences keep going to the normal conversation path.
_COURTESY = re.compile(r'^(?:麻烦你|麻烦您|麻烦|请问你|请问一下|请问|请|帮我看看|帮我查一下|帮我看一下'
                       r'|帮我|告诉我|你知道|你能告诉我|我想问一下|我想请教一下|想问一下|问一下'
                       r'|我想知道|我想问|我是问)+')
_TRAILING = re.compile(r'(?:谢谢|谢啦|多谢|呀|呢|啊|吧|来着|哦|噢)+$')
# English phrasings the ASR can hand over; these are answered in English.
_ENGLISH = re.compile(r"(?:what(?:'s| is)?(?: the)?(?: date| day)(?: is it)?(?: today)?"
                      r"|what day is it(?: today)?|today'?s date)")
_DAYS = {'今天': 0, '今日': 0, '现在': 0, '明天': 1, '昨天': -1}
_WEEKDAY_EN = 'Mon Tue Wed Thu Fri Sat Sun'.split()


def _strip_courtesy(text):
    while True:
        stripped = _TRAILING.sub('', _COURTESY.sub('', text))
        stripped = stripped.strip().strip('，。？！,.?!、').strip()
        if stripped == text:
            return text
        text = stripped


def calendar_answer(text, now=None):
    # Full matching intentionally leaves mixed requests, quotations, translations
    # and foreign time zones to the normal conversation path.
    text = _strip_courtesy(text)
    compact = re.sub(r'[\s，。？！,.?!、]', '', text)
    question = r'(?:的)?(?:是)?(?:星期几|周几|礼拜几|几月几[号日]|几[号日]|日期)'
    match = re.fullmatch(r'(?:本地|上海|北京|北京时间)?(今天|今日|现在|明天|昨天)' + question
                         + r'(?:吗|呢|啊|呀|来着)*', compact)
    now = now if now is not None else datetime.now().astimezone()
    if not match:
        english = re.sub(r'\s+', ' ', re.sub(r'[，。？！,.?!、]', ' ', text)).strip().lower()
        if _ENGLISH.fullmatch(english):
            date = now.date()
            return (f'Today is {date.year}-{date.month:02d}-{date.day:02d}, '
                    f'{_WEEKDAY_EN[date.weekday()]}.')
        return None
    day = match.group(1)
    date = now.date() + timedelta(days=_DAYS[day])
    weekday = '一二三四五六日'[date.weekday()]
    return f'{day}是{date.year}年{date.month}月{date.day}日，星期{weekday}。'
