import json
import tempfile
import unittest
from pathlib import Path

from marginalia import config as cfgmod
from marginalia.core.composer import clean_quote, compose
from marginalia.core.models import PENDING, SENT, AnnoType, Annotation
from marginalia.core.store import Store
from marginalia.core.template import render


class TemplateTest(unittest.TestCase):
    def test_vars_and_sections(self):
        tpl = '【{{name}}】{{#quote}}「{{quote}}」{{/quote}}{{#comment}}→ {{comment}}{{/comment}}{{^comment}}→ 无{{/comment}}'
        self.assertEqual(render(tpl, {'name': '展开', 'quote': 'abc', 'comment': 'why'}), '【展开】「abc」→ why')
        self.assertEqual(render(tpl, {'name': '展开', 'quote': '', 'comment': ''}), '【展开】→ 无')

    def test_user_text_is_not_template_syntax(self):
        self.assertEqual(render('{{comment}}', {'comment': '{{#x}}hi{{/x}} {{name}}'}), '{{#x}}hi{{/x}} {{name}}')


class ComposerTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfgmod.Config(json.loads(json.dumps(cfgmod.DEFAULTS)))

    def test_clean_quote_elides_middle(self):
        self.assertEqual(clean_quote('a  b\n c'), 'a b c')
        q = clean_quote('x' * 50 + 'y' * 50, 21)
        self.assertEqual(len(q), 21)
        self.assertTrue(q.startswith('x' * 10) and q.endswith('y' * 10) and '…' in q)

    def test_compose_default_templates(self):
        items = [Annotation('expand', '防止梯度爆炸的技术'),
                 Annotation('ask', 'clip_grad_norm_', comment='为什么不用权重衰减？'),
                 Annotation('condense', '一大段\n废话', comment='')]
        out = compose(items, self.cfg.type_map, self.cfg.prompt)
        self.assertEqual(out.splitlines(), [
            '请根据以下批注，修改或补充你上一条回复：',
            '1. 【展开】「防止梯度爆炸的技术」→ 请更详细地解释这部分',
            '2. 【REMARK】「clip_grad_norm_」→ 为什么不用权重衰减？',
            '3. 【精简】「一大段 废话」→ 这部分请压缩精简',
        ])

    def test_compose_plain(self):
        items = [Annotation('expand', '防止梯度爆炸的技术'),
                 Annotation('ask', 'clip_grad_norm_', comment='为什么不用权重衰减？'),
                 Annotation('ask', '', comment='独立备注')]
        out = compose(items, self.cfg.type_map, self.cfg.prompt, plain=True)
        self.assertEqual(out.splitlines(), [
            '1. 「防止梯度爆炸的技术」',
            '2. 「clip_grad_norm_」 为什么不用权重衰减？',
            '3. 独立备注',
        ])
        one = compose(items[1:2], self.cfg.type_map, self.cfg.prompt, plain=True)
        self.assertEqual(one, '「clip_grad_norm_」 为什么不用权重衰减？')   # single item: no numbering

    def test_unknown_type_falls_back(self):
        out = compose([Annotation('gone', 'q', comment='c')], {}, {'header': ''})
        self.assertEqual(out, '1. 【gone】「q」→ c')


class ConfigTest(unittest.TestCase):
    def test_merge_and_bindings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'config.json'
            p.write_text(json.dumps({'fill': {'auto_send': True},
                                     'types': [{'id': 'mine', 'name': '我的', 'hotkey': 'Shift+Alt+M'}]}))
            cfg, err = cfgmod.Config.load(p)
            self.assertIsNone(err)
            self.assertTrue(cfg.fill['auto_send'])
            self.assertEqual(cfg.fill['mode'], 'fill')                 # untouched defaults survive
            self.assertEqual([t.id for t in cfg.types], ['mine'])      # lists replace
            b = cfg.hotkey_bindings()
            self.assertEqual(b['type:mine'], 'Shift+Alt+M')
            self.assertEqual(b['menu'], 'Shift+Alt+S')
            self.assertEqual(b['fill_plain'], 'Alt+Return')
            self.assertEqual(b['toggle_panel'], 'Shift+Alt+D')

    def test_broken_file_reports_error_and_uses_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'config.json'
            p.write_text('{ not json')
            cfg, err = cfgmod.Config.load(p)
            self.assertIsNotNone(err)
            self.assertEqual(len(cfg.types), len(cfgmod.DEFAULT_TYPES))

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            AnnoType.from_dict({'id': 'x', 'name': 'X', 'input': 'sometimes'})


class StoreTest(unittest.TestCase):
    def test_crud_order_status(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / 'n.db')
            calls = []
            s.subscribe(lambda: calls.append(1))
            a = s.add(Annotation('expand', 'A', source={'xid': 1, 'wm_class': 'firefox'}, created_at=1.0))
            b = s.add(Annotation('ask', 'B', comment='q', anchor={'path': [0, 1], 'start': 3}, created_at=2.0))
            c = s.add(Annotation('keep', 'C', created_at=3.0))
            self.assertEqual([x.id for x in s.all()], [c.id, b.id, a.id])      # newest first
            self.assertEqual(s.get(b.id).anchor, {'path': [0, 1], 'start': 3})
            s.reorder([a.id, c.id])
            self.assertEqual([x.id for x in s.all()], [a.id, c.id, b.id])
            s.sort_newest_first()
            self.assertEqual([x.id for x in s.all()], [c.id, b.id, a.id])
            s.update(a.id, comment='new', checked=False)
            self.assertEqual((s.get(a.id).comment, s.get(a.id).checked), ('new', False))
            s.set_status([a.id, b.id], SENT, checked=False)
            self.assertEqual(s.get(b.id).status, SENT)
            s.delete_status(SENT)
            self.assertEqual([x.id for x in s.all()], [c.id])
            self.assertEqual(s.get(c.id).status, PENDING)
            self.assertGreaterEqual(len(calls), 6)

    def test_group_key(self):
        self.assertEqual(Annotation('x', 'q', source={'url': 'https://a/c/1'}).group_key, 'https://a/c/1')
        self.assertEqual(Annotation('x', 'q', source={'wm_class': 'code', 'xid': 7}).group_key, 'code:7')


class HotkeyParseTest(unittest.TestCase):
    def test_parse(self):
        from Xlib import X, XK
        from marginalia.platform.x11.hotkeys import parse
        self.assertEqual(parse('Shift+Alt+Space'), (X.ShiftMask | X.Mod1Mask, XK.XK_space))
        self.assertEqual(parse('shift+alt+enter'), (X.ShiftMask | X.Mod1Mask, XK.XK_Return))
        self.assertEqual(parse('Shift+Alt+E'), (X.ShiftMask | X.Mod1Mask, XK.XK_e))
        for bad in ('', 'Hyper+E', 'Shift+NoSuchKey'):
            with self.assertRaises(ValueError):
                parse(bad)


if __name__ == '__main__':
    unittest.main()
