import unittest

from agent_notes.core.anchor import OBJ, find_all, find_quote, normalize, parts


class AnchorTest(unittest.TestCase):
    def test_normalize_maps_back_to_original_offsets(self):
        t = f'ab{OBJ}  c\n\nd'
        n, idx = normalize(t)
        self.assertEqual(n, 'ab c d')
        self.assertEqual(t[idx[3]], 'c')

    def test_finds_across_placeholders_and_reflowed_whitespace(self):
        text = f'梯度裁剪{OBJ}是一种\n  防止梯度爆炸的技术。'
        (s, e), = find_all(text, '是一种 防止梯度爆炸')
        self.assertEqual(text[s:e], '是一种\n  防止梯度爆炸')

    def test_line_breaks_inside_cjk_text(self):
        text = '把梯度的范数限制在某个阈值以内。'
        (s, e), = find_all(text, '把梯度的范数限制在\n某个阈值')
        self.assertEqual(text[s:e], '把梯度的范数限制在某个阈值')

    def test_context_picks_the_right_occurrence(self):
        text = 'A: learning rate warmup is good. B: learning rate warmup is bad.'
        s, e, _ = find_quote(text, 'learning rate warmup', prefix='B: ', suffix=' is bad')
        self.assertEqual(s, text.rindex('learning'))
        s, _, _ = find_quote(text, 'learning rate warmup', prefix='A: ')
        self.assertEqual(s, text.index('learning'))

    def test_old_offset_breaks_ties(self):
        text = 'x foo y foo z foo'
        s, _, _ = find_quote(text, 'foo', near=9)
        self.assertEqual(s, 8)

    def test_missing_quote(self):
        self.assertIsNone(find_quote('abc', 'xyz'))
        self.assertIsNone(find_quote('abc', '   '))

    def test_parts(self):
        self.assertEqual(parts('first para\n\n second \nthird'), ['first para', 'second', 'third'])
        self.assertEqual(parts('交接时前倾\t01: 0.000\t02: 0.096'), ['交接时前倾', '01: 0.000', '02: 0.096'])


class CapturePrimaryTest(unittest.TestCase):
    def test_primary_extends_the_reported_selection(self):
        from agent_notes.platform.atspi.capture import _covers_more
        reported = '先说明进度：配置查看器已经跑起来了。'
        primary = '先说明进度：配置查看器已经跑起来了。\n\n- 接口检查正常\n- 对比功能可用'
        self.assertTrue(_covers_more(primary, reported))
        self.assertTrue(_covers_more('abc\nmiddle\nxyz end', 'abc\nxyz'))         # start + end nodes only
        self.assertFalse(_covers_more(reported, reported))
        self.assertFalse(_covers_more('something else entirely, longer', reported))   # stale PRIMARY
        self.assertFalse(_covers_more('', reported))


if __name__ == '__main__':
    unittest.main()
