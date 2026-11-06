import unittest

from aihub_models.minutes.render import render_markdown

TEMPLATE = {'name': '通用详细纪要', 'template_id': 'general', 'version': 3,
            'sections': ['overview', 'topics', 'decisions', 'action_items']}
RECORDING = {'started_at': 1793970700, 'duration_ms': 38000}


def minutes():
    return {
        'stats': {'transcript_lines': 3, 'speakers': 0},
        'model_id': 'mlx-community/Qwen3.5-4B-MLX-4bit',
        'transcript_sha256': 'a' * 64,
        'generated_at': 1793971000,
        'coverage': {},
        'sections': [
            {'key': 'overview', 'title': '会议概览', 'kind': 'text', 'text': '本场录音 38 秒。'},
            {'key': 'topics', 'title': '议题与讨论', 'kind': 'topics',
             'items': [{'title': '测试状态', 'summary': '确认设备',
                        'evidence': [{'stamp': '00:04', 'quote': '能听见我说话吗？'}]}],
             'key_points': [{'text': '设备可用',
                             'evidence': [{'stamp': '00:11', 'quote': '我在测试。'}]}]},
            {'key': 'decisions', 'title': '已确认决策', 'kind': 'decisions',
             'items': [{'text': '继续测试',
                        'evidence': [{'stamp': '00:20', 'quote': '继续吧。'}]}]},
            {'key': 'action_items', 'title': '行动项', 'kind': 'actions',
             'items': [{'task': '发通知', 'owner': '未明确', 'due_date': '未明确',
                        'status': 'agreed',
                        'evidence': [{'stamp': '00:30', 'quote': '我来发。'}]}]},
        ],
    }


class MinutesMarkdown(unittest.TestCase):
    def test_evidence_and_internal_metadata_are_not_rendered(self):
        markdown = render_markdown(minutes(), TEMPLATE, RECORDING)
        for needle in ('证据', 'SHA-256', '生成模型', '00:04', '能听见我说话吗'):
            self.assertNotIn(needle, markdown)
        # the structured result keeps the quotes for tooling; the document does not
        self.assertEqual(minutes()['sections'][1]['items'][0]['evidence'][0]['stamp'], '00:04')

    def test_document_keeps_sections_and_a_compact_action_table(self):
        markdown = render_markdown(minutes(), TEMPLATE, RECORDING)
        self.assertIn('## 会议概览', markdown)
        self.assertIn('## 行动项', markdown)
        self.assertIn('| 任务 | 负责人 | 截止 | 状态 |', markdown)
        self.assertIn('| 发通知 | 未明确 | 未明确 | 已确认 |', markdown)
        self.assertIn('> 本纪要由本机模型根据录音转写生成', markdown)


if __name__ == '__main__':
    unittest.main()
