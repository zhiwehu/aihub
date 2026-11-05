"""Score the Rex planner (production path) against the daily-conversation corpus.

Unlike ``evaluate_router_stress.py`` this needs no training snapshots: it drives
``RexPlanner`` - the same client the server uses at runtime, subprocess protocol
included - and applies the same production rule that answers calendar questions
before the planner ever runs.

    AIHUB_DATA_ROOT=~/ai/aihub/data python scripts/evaluate_rex_daily.py
    ... --limit 100 --mode followup
"""
import argparse
import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'src'))

from router_stress_cases import cases                        # noqa: E402
from evaluate_router_stress import error_kind                # noqa: E402
from aihub_tools.local_calendar import calendar_answer       # noqa: E402
from aihub_tools.rex_planner import RexPlanner               # noqa: E402


def load_defaults(path):
    tools = json.loads(Path(path).read_text())['tools']
    return {'default_city': tools['default_city'], 'news_source': tools['news_source'],
            'news_limit': tools['news_limit']}


async def run(args):
    defaults = load_defaults(args.settings)
    rows = cases()
    if args.category:
        rows = [row for row in rows if row.get('category') == args.category]
    if args.limit:
        rows = rows[:args.limit]
    planner = RexPlanner(args.data_root)
    results = []
    started = time.monotonic()
    try:
        for index, row in enumerate(rows, 1):
            history = []
            if args.mode == 'followup' and row.get('previous_user'):
                history.append({'role': 'user', 'content': row['previous_user']})
            history.append({'role': 'user', 'content': row['text']})
            calendar = calendar_answer(row['text'])
            if calendar is not None:
                plan = {'status': 'calendar', 'tool': None, 'arguments': {}}
            else:
                try:
                    plan = await planner.plan(history, defaults, row.get('previous'))
                except Exception as exc:                     # noqa: BLE001
                    plan = {'status': 'error', 'tool': None, 'arguments': {},
                            'error': f'{type(exc).__name__}: {exc}'}
            error = error_kind(row['expected'], plan)
            results.append({'id': row['id'], 'category': row['category'], 'family': row['family'],
                            'text': row['text'], 'expected': row['expected'], 'actual': plan,
                            'calendar_answer': calendar, 'error': error})
            if index % 100 == 0:
                print(f'  {index}/{len(rows)} …', flush=True)
    finally:
        await planner._stop()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'results.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False)
                                                    for row in results) + '\n')
    failures = [row for row in results if row['error']]
    (output / 'failures.json') .write_text(json.dumps(failures, ensure_ascii=False, indent=2))

    by_status = defaultdict(Counter)
    by_category = defaultdict(Counter)
    for row in results:
        ok = row['error'] is None
        by_status[row['expected']['status']]['total'] += 1
        by_status[row['expected']['status']]['ok'] += int(ok)
        by_category[row['category']]['total'] += 1
        by_category[row['category']]['ok'] += int(ok)
    print(f'cases={len(results)} mode={args.mode} elapsed={time.monotonic() - started:.0f}s')
    for status, counter in sorted(by_status.items()):
        print(f'  {status:8} {counter["ok"]:4}/{counter["total"]:<4} '
              f'({counter["ok"] / max(counter["total"], 1):.1%})')
    for category, counter in sorted(by_category.items()):
        print(f'    {category:10} {counter["ok"]:4}/{counter["total"]:<4} '
              f'({counter["ok"] / max(counter["total"], 1):.1%})')
    kinds = Counter(row['error'] for row in failures)
    print(f'  failures {len(failures)}/{len(results)} {dict(kinds)}')
    for row in failures[:10]:
        print(f'   ✗ [{row["category"]}] {row["text"][:30]!r} expected='
              f'{row["expected"]["tool"]}/{row["expected"]["status"]} actual='
              f'{row["actual"].get("tool")}/{row["actual"].get("status")}')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/tmp/rex-daily')
    parser.add_argument('--settings', default=str(Path.home() / 'ai/aihub/data/settings.json'))
    parser.add_argument('--data-root', default=str(Path.home() / 'ai/aihub/data'))
    parser.add_argument('--mode', choices=('single', 'followup'), default='single')
    parser.add_argument('--category', default='')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
