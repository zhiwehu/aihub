import asyncio
import unittest

from aihub_models.minutes.extractor import chunk_lines, extract_chunk


class TruncatedButRecoverable(unittest.TestCase):
    """A long chunk used to fail every retry because the JSON was cut at 1400 tokens."""

    def test_second_attempt_gets_more_room(self):
        chunk = chunk_lines([{'stamp': '00:01', 'speaker': None, 'text': '大家讨论一下下周的安排。'}])[0]
        template = {'name': '通用', 'instructions': '保留脉络。'}
        calls = []

        class Engine:
            async def generate(self, messages, *, max_tokens=1400, timeout=240):
                calls.append(max_tokens)
                if len(calls) == 1:
                    return '{"topics": [{"title": "安排", "summary": "讨论", "evidence": [{"line": 1, "quote": "下周'  # cut off
                return ('{"topics": [], "key_points": [], "decisions": [], '
                        '"actions": [], "risks": [], "questions": []}')

        data = asyncio.run(extract_chunk(Engine(), chunk, template))
        self.assertEqual(calls[0], 2000)
        self.assertGreater(calls[1], calls[0])
        self.assertEqual(data['actions'], [])

    def test_hopeless_output_still_reports_invalid_json(self):
        chunk = chunk_lines([{'stamp': '00:01', 'speaker': None, 'text': '随便说说。'}])[0]

        class Engine:
            async def generate(self, messages, *, max_tokens=1400, timeout=240):
                return '这不是 JSON'

        with self.assertRaises(Exception) as raised:
            asyncio.run(extract_chunk(Engine(), chunk, {'name': '通用', 'instructions': '保留脉络。'}))
        self.assertEqual(getattr(raised.exception, 'code', ''), 'minutes_json_invalid')
