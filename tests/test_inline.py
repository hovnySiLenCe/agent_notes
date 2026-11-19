"""Quotes that run through inline elements (inline code, links): Chromium / VS Code put an embedded-object
character in the paragraph's text where each one sits, and the element's text in a child."""
import unittest
from unittest import mock

from marginalia.platform.atspi import locate
from marginalia.platform.atspi.tree import OBJ


class Node:
    def __init__(self, text, role='paragraph'):
        self.text, self.role = text, role

    def get_role_name(self):
        return self.role


PARA = Node(f'主控是 {OBJ}。IMU 使用直连 I²C，按 {OBJ} 先完成接线。')
CODE = Node('ZERO 3W，不是 3E', 'static')
LINK = Node('IMU 首次只读测试', 'link')
LEAF = Node('主控是 ', 'static')                 # Chromium also exposes the paragraph's own runs as children
EMBEDDED = {(id(PARA), 4): CODE, (id(PARA), PARA.text.index(OBJ, 5)): LINK}
NODES = [(PARA, (0, 3), PARA.text), (LEAF, (0, 3, 0), LEAF.text), (CODE, (0, 3, 1), CODE.text),
         (LINK, (0, 3, 3), LINK.text)]


class InlineTest(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(locate, '_text', lambda n: n.text),
                  mock.patch.object(locate, '_embedded', lambda n, i: EMBEDDED.get((id(n), i)))):
            p.start()
            self.addCleanup(p.stop)

    def test_expand(self):
        text, owners = locate.expand(PARA)
        self.assertEqual(text, '主控是 ZERO 3W，不是 3E。IMU 使用直连 I²C，按 IMU 首次只读测试 先完成接线。')
        self.assertEqual(len(owners), len(text))
        self.assertIs(owners[4][0], CODE)

    def test_quote_through_inline_code_is_found(self):
        segs = locate._search(NODES, {}, '主控是 ZERO 3W，不是 3E。IMU 使用', ())
        self.assertEqual([(s.node, s.start, s.end) for s in segs],
                         [(PARA, 0, 4), (CODE, 0, len(CODE.text)), (PARA, 5, 12)])
        self.assertEqual(''.join(s.text for s in segs), '主控是 ZERO 3W，不是 3E。IMU 使用')

    def test_quote_inside_one_element_needs_no_expanding(self):
        with mock.patch.object(locate, 'expand', side_effect=AssertionError('expanded')):
            segs = locate._search(NODES, {}, '不是 3E', ())
        self.assertEqual([(s.node, s.start) for s in segs], [(CODE, CODE.text.index('不是'))])

    def test_anchor_round_trip(self):
        quote = '按 IMU 首次只读测试 先完成'
        with mock.patch.object(locate, 'frames_for', lambda pid, xid: ['frame']), \
                mock.patch.object(locate, 'walk', lambda root, deadline: [(n, p, 0) for n, p, _ in NODES]):
            anchor = locate.anchor_from_text(1, 2, quote)
        self.assertTrue(anchor['expanded'])
        self.assertEqual(anchor['path'], [0, 3])
        with mock.patch.object(locate, 'node_at', lambda frame, path: (PARA, None, ())):
            segs = locate.fast_locate('frame', anchor, quote)
        self.assertTrue(locate.single_node(anchor))
        self.assertEqual([s.node for s in segs], [PARA, LINK, PARA])
        self.assertEqual(''.join(s.text for s in segs).replace(' ', ''), quote.replace(' ', ''))
        with mock.patch.object(locate, 'node_at', lambda frame, path: (PARA, None, ())):
            self.assertIsNone(locate.fast_locate('frame', anchor, '别的文字'))

    def test_unrelated_paragraphs_are_not_expanded(self):
        other = Node(f'完全无关的段落 {OBJ}。')
        with mock.patch.object(locate, 'expand', side_effect=AssertionError('expanded')):
            self.assertIsNone(locate._search([(other, (1,), other.text)], {}, '主控是 ZERO 3W', ()))


if __name__ == '__main__':
    unittest.main()
