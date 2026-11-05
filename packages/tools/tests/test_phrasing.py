import unittest
from aihub_tools import phrasing


class PhrasingTests(unittest.TestCase):
    def test_acknowledgement_is_varied_and_never_the_old_template(self):
        seen=[phrasing.acknowledge('weather') for _ in range(3)]
        self.assertEqual(len(set(seen)),3,seen)
        for line in seen:
            self.assertNotIn('收到，我来处理',line)
            self.assertTrue(line.endswith('。'),line)

    def test_unknown_tool_gets_a_natural_fallback(self):
        for _ in range(4):
            self.assertIn(phrasing.acknowledge('ext_demo__read_file'),phrasing._DEFAULT)

    def test_progress_names_the_subject_it_can_recognise(self):
        self.assertIn(phrasing.progress('上海今天天气怎么样'),phrasing._ACKS['weather'])
        self.assertIn(phrasing.progress('看看最新新闻'),phrasing._ACKS['news'])

    def test_verified_results_are_spoken_without_invented_leads(self):
        text='上海今天多云，22 到 28 度。'
        self.assertEqual(phrasing.announcement(text),text)

    def test_repeated_results_do_not_get_random_conversational_filler(self):
        text='确认的查询结果。'
        self.assertEqual([phrasing.announcement(text) for _ in range(6)],[text]*6)

    def test_long_results_are_complete_without_web_redirects(self):
        text='第一条新闻：相关报道的内容。'*15+'最后一条新闻：完整的核实结果。'
        self.assertEqual(phrasing.announcement(text),text)
        for status in ('completed','failed','waiting'):
            with self.subTest(status=status):
                spoken=phrasing.announcement(text,status=status)
                self.assertEqual(spoken,text)
                self.assertNotIn('网页',spoken)
                self.assertNotIn('不念了',spoken)

    def test_truncation_never_leaves_a_half_clause(self):
        # 真实案例：按字符硬切会切出「还有一。」这种半句。
        text='新闻摘要是这样的，内容比较长。'*10+'还有一条很重要的消息没有说完，后面还有内容'
        body,truncated=phrasing.shorten(text,120)
        self.assertTrue(truncated)
        self.assertTrue(body.endswith('。'),body)
        self.assertNotIn('还有一条很重要的消息没有说完。',body)
        self.assertLessEqual(len(body),121)

    def test_cut_prefers_a_sentence_boundary(self):
        body,_=phrasing.shorten('第一句。第二句。'+'第三句'*80,20)
        self.assertEqual(body,'第一句。第二句。')

    def test_without_sentence_marks_the_body_still_ends_with_a_full_stop(self):
        body,truncated=phrasing.shorten('没有任何标点的长文本'*40,50)
        self.assertTrue(truncated)
        self.assertTrue(body.endswith('。'),body)

    def test_failures_are_spoken_as_written(self):
        text='后台任务未能完成，请在网页上查看原因。'
        self.assertEqual(phrasing.announcement(text,status='failed'),text)


if __name__=='__main__':
    unittest.main()
