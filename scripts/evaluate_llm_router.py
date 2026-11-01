"""Score the LLM tool router against the daily-conversation corpus.

The router is the only thing standing between a normal sentence and an MCP call,
so it is exercised here with production's own prompt (``router_prompt``) and the
same request shape the server sends after the context fix: the latest user turn,
plus the previous one for follow-ups.

    python scripts/evaluate_llm_router.py --output /tmp/router-eval
    python scripts/evaluate_llm_router.py --mode chatty --limit 200

``--mode chatty`` prefixes a long everyday conversation to every case, which is
the situation that used to make the model answer in prose instead of routing.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'src'))

from router_stress_cases import cases                      # noqa: E402
from aihub_tools.tool_chat import router_prompt             # noqa: E402
from aihub_tools.tools import catalogue, parse_plan         # noqa: E402
from aihub_tools.extension_routing import is_followup       # noqa: E402

CHATTY_HISTORY = [
    ('user', '小宝同学，我回来啦。'),
    ('assistant', '欢迎回来！今天过得怎么样？'),
    ('user', '还行吧，就是有点累。'),
    ('assistant', '累的话就先歇一会儿，别硬撑着。'),
    ('user', '你记得我昨天说的事吗？'),
    ('assistant', '记得呀，你说想早点睡，结果又熬夜了吧？'),
    ('user', '哈哈哈哈，被你说中了。'),
    ('assistant', '那今晚可别再刷手机停不下来啦。'),
    ('user', '知道了知道了，你真是操心。'),
    ('assistant', '关心你嘛，谁让你是我的老搭档。'),
]


def load_config(path):
    document = json.loads(Path(path).read_text())
    tools = document['tools']
    return document['llm'], tools


def load_token(path, key='VOICE_LLM_KEY'):
    path = Path(path)
    if not path.exists():
        return os.environ.get(key, '')
    for line in path.read_text().splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return os.environ.get(key, '')


async def ask(session, url, model, token, system, messages, max_tokens, timeout=30):
    payload = {'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
               'max_tokens': max_tokens, 'stream': True}
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    text = []
    async with session.post(url.rstrip('/') + '/chat/completions', json=payload,
                            headers=headers) as response:
        if response.status != 200:
            raise ValueError(f'http_{response.status}')
        buffer = []
        while True:
            line = await response.content.readline()
            if not line:
                break
            line = line.decode('utf-8').strip()
            if not line:
                if buffer:
                    event = '\n'.join(buffer)
                    buffer = []
                    if event == '[DONE]':
                        break
                    choice = json.loads(event)['choices'][0]
                    text.append(choice.get('delta', {}).get('content', ''))
                continue
            if line.startswith('data:'):
                buffer.append(line[5:].lstrip())
    return ''.join(text)


def verdict(expected, actual):
    """Return (routing_ok, params_ok) for one case."""
    expected_tool = expected.get('tool')
    actual_tool = actual.get('tool')
    routing = expected_tool == actual_tool
    params = routing and expected.get('arguments') == actual.get('arguments')
    return routing, params


async def run(args):
    llm, tools = load_config(args.settings)
    token = load_token(args.token_file)
    available = [tool for tool in catalogue() if tools.get(tool['name'])]
    prompt = router_prompt(tools, available)
    rows = cases()
    if args.category:
        rows = [row for row in rows if row.get('category') == args.category]
    if args.limit:
        rows = rows[:args.limit]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    semaphore = asyncio.Semaphore(args.concurrency)
    results = []

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def one(row):
            async with semaphore:
                history = []
                if args.mode == 'chatty':
                    history.extend({'role': role, 'content': text} for role, text in CHATTY_HISTORY)
                if row.get('previous_user'):
                    history.append({'role': 'user', 'content': row['previous_user']})
                history.append({'role': 'user', 'content': row['text']})
                # Same trimming rule as production: the router sees the current
                # request, plus the previous user turn for follow-ups only.
                users = [message for message in history if message['role'] == 'user']
                router = users[-1:]
                if len(users) > 1 and is_followup(users[-1]['content']):
                    router = users[-2:]
                started = time.monotonic()
                raw = ''
                try:
                    raw = await ask(session, args.url, llm['model'], token, prompt, router,
                                    llm['max_tokens'])
                    name, arguments = parse_plan(raw, {**tools, **{t['name']: True for t in available}},
                                                 available)
                    actual = {'status': 'chat' if name is None else 'ready',
                              'tool': name, 'arguments': arguments}
                    error = None
                except Exception as exc:          # noqa: BLE001 - recorded as a failure
                    actual, error = {}, f'{type(exc).__name__}: {exc}'
                routing, params = verdict(row['expected'], actual)
                results.append({'id': row['id'], 'category': row['category'], 'text': row['text'],
                                'expected': row['expected'], 'actual': actual, 'raw': raw,
                                'routing_ok': routing, 'params_ok': params,
                                'error': error, 'ms': round((time.monotonic() - started) * 1000)})
        await asyncio.gather(*(one(row) for row in rows))

    by_status = defaultdict(Counter)
    for row in results:
        expected = row['expected']['status']
        by_status[expected]['total'] += 1
        by_status[expected]['routing'] += int(row['routing_ok'])
        by_status[expected]['params'] += int(row['params_ok'])
        if row['error']:
            by_status[expected]['error'] += 1

    (output / 'results.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False)
                                                    for row in results) + '\n')
    failures = [row for row in results if not row['routing_ok']]
    (output / 'failures.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False)
                                                     for row in failures) + '\n')

    print(f'cases={len(results)} mode={args.mode} url={args.url}')
    for status, counter in sorted(by_status.items()):
        total = counter['total'] or 1
        print(f'  {status:8} {counter["routing"]:4}/{total:<4} '
              f'({counter["routing"] / total:.1%})  params {counter["params"]}/{total}'
              f'  errors {counter["error"]}')
    routing = sum(1 for row in results if row['routing_ok'])
    print(f'  overall  {routing}/{len(results)} ({routing / max(len(results), 1):.1%})')
    print(f'  failures -> {output / "failures.jsonl"}')
    for row in failures[:8]:
        print(f'   ✗ [{row["category"]}] {row["text"][:36]!r} expected={row["expected"]["tool"]} '
              f'actual={row["actual"].get("tool")} raw={row["raw"][:60]!r}')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/tmp/router-eval')
    parser.add_argument('--settings', default=str(Path.home() / 'ai/aihub/data/settings.json'))
    parser.add_argument('--token-file',
                        default=str(Path.home() / 'ai/aihub/aihub-server/deploy/docker/env/models.env'))
    parser.add_argument('--url', default='http://127.0.0.1:8782/v1')
    parser.add_argument('--mode', choices=('single', 'chatty'), default='single')
    parser.add_argument('--category', default='')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
