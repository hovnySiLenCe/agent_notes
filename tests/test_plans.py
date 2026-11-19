import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from marginalia.__main__ import _preload_xcb_cursor  # noqa: E402

_preload_xcb_cursor()

from marginalia.core import plans  # noqa: E402
from marginalia.core.plans import DONE, PlanStore, extract, parse  # noqa: E402

PASTED = """计划
进行中

v2 训练：semantics 预计 11-21 凌晨完成，三段全部完成约 11-23 上午。
内存记录：确认训练服务的内存会稳定下来，而不是持续上涨。
等你决定

两个训练脚本新加的 --start-stage / --resume 选项还没提交，要不要提交。
测试数据集：由你另外制作。
以后

训练跑完后停掉内存记录服务 atom-v2-memlog。
"""

REPLY = """改好了，测试都通过。

## 计划
**进行中**
- M3 OCR 兜底（应用没有无障碍接口时用）

**等你**
- 试试设置窗口：改个类型、录一个快捷键、保存。
- 在 VS Code 里再试一下：
  - 选一段带列表的回复加批注；
  - 面板展开后能否看到卡片列表。

**以后**
- M4：AppImage 打包，Windows / macOS 移植。
"""


class ParseTest(unittest.TestCase):
    def test_plain_text_plan(self):
        got = parse(PASTED)
        self.assertEqual([c for c, _ in got], ['进行中', '等你决定', '以后'])
        self.assertEqual(len(got[0][1]), 2)
        self.assertTrue(got[1][1][1].startswith('测试数据集'))       # 'x：y' is an item, not a category

    def test_markdown_reply(self):
        plan = extract(REPLY)
        self.assertIsNotNone(plan)
        got = dict(parse(plan))
        self.assertEqual(list(got), ['进行中', '等你', '以后'])
        self.assertEqual(len(got['等你']), 2)
        self.assertEqual(got['等你'][1], '在 VS Code 里再试一下：\n· 选一段带列表的回复加批注；\n· 面板展开后能否看到卡片列表。')

    def test_no_plan_heading(self):
        self.assertIsNone(extract('只是一段普通回复。\n没有计划。'))

    def test_items_without_category(self):
        self.assertEqual(parse('- a\n- b'), [('', ['a', 'b'])])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = PlanStore(Path(self.tmp.name) / 'n.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_keeps_ids_of_same_and_edited_items(self):
        self.st.update('p', parse(PASTED), {'xid': 5})
        before = {it['text']: it['id'] for it in self.st.items('p')}
        edited = PASTED.replace('三段全部完成约 11-23 上午', '三段全部完成约 11-23 中午').replace(
            '测试数据集：由你另外制作。\n', '').replace('以后\n', '以后\n新的一条\n')
        res = self.st.update('p', parse(edited))
        self.assertEqual(res, {'added': 1, 'removed': 1, 'kept': 4})
        after = self.st.items('p')
        v2 = next(it for it in after if it['text'].startswith('v2 训练'))
        self.assertEqual(v2['id'], before['v2 训练：semantics 预计 11-21 凌晨完成，三段全部完成约 11-23 上午。'])
        self.assertIn('中午', v2['text'])
        self.assertEqual([it['text'] for it in self.st.items('p', DONE)], ['测试数据集：由你另外制作。'])
        self.assertEqual(self.st.project('p')['source'], {'xid': 5})        # kept when not given

    def test_category_update_leaves_the_rest(self):
        self.st.update('p', parse(PASTED))
        self.st.update('p', [('', ['只换这一类'])], category='等你决定')
        secs = self.st.sections('p')
        self.assertEqual([c for c, _ in secs], ['进行中', '等你决定', '以后'])
        self.assertEqual([it['text'] for it in secs[1][1]], ['只换这一类'])

    def test_projects_most_recent_first(self):
        self.st.update('a', [('x', ['1'])])
        time.sleep(0.01)
        self.st.update('b', [('x', ['1'])])
        self.assertEqual([p['name'] for p in self.st.projects()], ['b', 'a'])
        self.st.delete_project('b')
        self.assertEqual([p['name'] for p in self.st.projects()], ['a'])


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _transcript(self) -> Path:
        p = self.dir / 't.jsonl'
        lines = [{'type': 'user', 'message': {'role': 'user', 'content': '做吧'}},
                 {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '旧回复'}]}},
                 {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                     {'type': 'tool_use', 'name': 'Bash', 'input': {}}]}},
                 {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': REPLY}]}},
                 {'type': 'system', 'subtype': 'stop_hook_summary'}]
        p.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in lines) + '\n', encoding='utf-8')
        return p

    def test_hook_sends_the_last_replys_plan(self):
        from marginalia import plan_cli
        sent = []
        stdin = io.StringIO(json.dumps({'transcript_path': str(self._transcript()), 'cwd': str(self.dir)}))
        with mock.patch.object(plan_cli, 'send', lambda *a, **k: sent.append((a, k)) or True), \
                mock.patch('sys.stdin', stdin):
            self.assertEqual(plan_cli.cmd_hook(), 0)
        (project, text), kw = sent[0]
        self.assertEqual(project, self.dir.name)
        self.assertTrue(text.startswith('**进行中**'))
        self.assertEqual(kw['agent'], 'claude-code')

    def test_hook_never_fails(self):
        from marginalia import plan_cli
        with mock.patch('sys.stdin', io.StringIO('not json')):
            self.assertEqual(plan_cli.cmd_hook(), 0)

    def test_install_and_uninstall_keep_other_hooks(self):
        from marginalia import plan_cli
        s = self.dir / 'settings.json'
        other = {'hooks': [{'type': 'command', 'command': 'echo hi'}]}
        s.write_text(json.dumps({'model': 'x', 'hooks': {'Stop': [other]}}), encoding='utf-8')
        with mock.patch('sys.stdout', io.StringIO()):
            plan_cli.install_claude_hook(True, s)
            plan_cli.install_claude_hook(True, s)                    # twice: still one entry
            data = json.loads(s.read_text())
            self.assertEqual(len(data['hooks']['Stop']), 2)
            self.assertIn('--plan-hook', data['hooks']['Stop'][1]['hooks'][0]['command'])
            self.assertTrue((self.dir / 'settings.json.marginalia.bak').exists())
            plan_cli.install_claude_hook(False, s)
        self.assertEqual(json.loads(s.read_text()), {'model': 'x', 'hooks': {'Stop': [other]}})

    def test_ancestors_include_self_and_parent(self):
        from marginalia.plan_cli import ancestors
        a = ancestors()
        self.assertEqual(a[:2], [os.getpid(), os.getppid()])


class ControllerPlanTest(unittest.TestCase):
    """Controller.receive_plan / annotate_plan_item on a stand-in controller."""

    def setUp(self):
        from marginalia import config as cfgmod
        from marginalia.core.store import Store
        from marginalia.platform.base import WindowInfo
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / 'n.db'
        term = WindowInfo(xid=11, pid=100, wm_class='Gnome-terminal', wm_instance='gnome-terminal-server',
                          title='✳ note_plugin')
        other = WindowInfo(xid=12, pid=100, wm_class='Gnome-terminal', wm_instance='gnome-terminal-server', title='bash')
        self.updated = []
        self.opened = []
        self.ctl = SimpleNamespace(
            plans=PlanStore(db), store=Store(db), cfg=cfgmod.Config(json.loads(json.dumps(cfgmod.DEFAULTS))),
            platform=SimpleNamespace(windows_of=lambda pids: [other, term] if 100 in pids else [],
                                     active_window=lambda: None, window_exists=lambda xid: xid in (11, 12),
                                     is_terminal=lambda w: True, window_with_text=lambda wins, text: 11),
            worker=SimpleNamespace(submit=lambda fn, *a, cb=None, urgent=False: cb(fn(*a))),
            panel=SimpleNamespace(plan_updated=lambda p, r: self.updated.append((p, r))),
            popup=SimpleNamespace(isVisible=lambda: False), _capture_ctx=None)
        from marginalia.app import Controller
        for name in ('receive_plan', '_plan_source', 'annotate_plan_item', '_confirm_plan_window'):
            setattr(self.ctl, name, getattr(Controller, name).__get__(self.ctl))
        self.ctl._open_capture = lambda ctx, type_id, t: self.opened.append((ctx, type_id))

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_lands_with_the_window_named_after_the_project(self):
        res = self.ctl.receive_plan({'project': 'note_plugin', 'text': PASTED, 'pids': [999, 100]})
        self.assertTrue(res['ok'])
        self.assertEqual(self.ctl.plans.project('note_plugin')['source']['xid'], 11)
        self.assertEqual(self.updated[0][0], 'note_plugin')
        self.assertFalse(self.ctl.receive_plan({'project': 'x', 'text': '   '})['ok'])

    def test_terminal_window_is_told_apart_by_its_screen(self):
        """All terminal windows share one process and no title names the project: the screen text decides."""
        self.ctl.receive_plan({'project': 'other_project', 'text': PASTED, 'pids': [100]})
        self.assertEqual(self.ctl.plans.project('other_project')['source']['xid'], 11)

    def test_annotating_an_item(self):
        self.ctl.receive_plan({'project': 'note_plugin', 'text': PASTED, 'pids': [100]})
        item = self.ctl.plans.items('note_plugin')[2]
        self.ctl.annotate_plan_item(item['id'], 'ask')
        ctx, type_id = self.opened[0]
        self.assertEqual((ctx['quote'], type_id, ctx['win'].xid), (item['text'], 'ask', 11))
        self.assertEqual(ctx['anchor'], {'method': 'plan', 'project': 'note_plugin', 'item': item['id'],
                                         'category': '等你决定'})
        self.assertFalse(ctx['return_focus'])


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _http(self, port: int, raw: bytes) -> bytes:
        import socket
        import threading
        out = {}

        def run():
            s = socket.create_connection(('127.0.0.1', port), timeout=3)
            s.sendall(raw)
            data = b''
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            out['r'] = data
            s.close()
        t = threading.Thread(target=run)
        t.start()
        end = time.monotonic() + 3
        while t.is_alive() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        t.join(1)
        return out.get('r', b'')

    def test_post_get_and_origin_refused(self):
        from marginalia.plan_server import PlanServer
        got = []
        srv = PlanServer(lambda p: got.append(p) or {'ok': True}, lambda name: {'project': name} if got else None)
        self.assertTrue(srv.listen(0) is False)                     # 0 = off
        port = 47999
        if not srv.listen(port):
            self.skipTest('port busy')
        body = '进行中\n- 一\n'.encode()
        r = self._http(port, b'POST /plan/%E9%A1%B9%E7%9B%AE/%E8%BF%9B%E8%A1%8C%E4%B8%AD HTTP/1.1\r\nHost: x\r\n'
                             + f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
        self.assertIn(b'200 OK', r)
        self.assertEqual((got[0]['project'], got[0]['category'], got[0]['text']), ('项目', '进行中', '进行中\n- 一\n'))
        r = self._http(port, b'GET /plan/abc HTTP/1.1\r\nHost: x\r\n\r\n')
        self.assertIn(b'"project": "abc"', r)
        r = self._http(port, b'POST /plan/x HTTP/1.1\r\nOrigin: https://evil.example\r\nContent-Length: 1\r\n\r\nx')
        self.assertIn(b'403', r)
        self.assertEqual(len(got), 1)
        srv.close()


class TerminalTrackingTest(unittest.TestCase):
    def test_on_screen(self):
        from marginalia.platform.atspi.tracker import on_screen
        screen = '● 这是第一段回复的结尾\n  - 选一段带列表的回复加批注；\n  - 面板展开后能否看到卡片列表。\n❯ '
        s, e, clipped = on_screen(screen, '选一段带列表的回复加批注；')
        self.assertEqual((screen[s:e], clipped), ('选一段带列表的回复加批注；', False))
        top = '上面已经滚出屏幕的半句话，' + screen[:7]        # its start scrolled off the top
        s, e, clipped = on_screen(screen, '更早的一行已经看不到\n' + '● 这是第一段回复的结尾')
        self.assertTrue(clipped)
        self.assertEqual(screen[s:e], '● 这是第一段回复的结尾')
        s, e, clipped = on_screen(screen, '面板展开后能否看到卡片列表。\n❯ 后面还没显示出来')
        self.assertTrue(clipped)
        self.assertTrue(screen[s:e].startswith('面板展开后'))
        self.assertIsNone(on_screen(screen, '完全不在屏幕上的一段话'))
        del top

    def test_quote_is_followed_every_tick(self):
        from marginalia.platform.atspi import tracker as tr
        screens = ['行一\n要找的那句话\n行三\n', '新输出\n新输出\n行一\n要找的那句话\n行三\n', '全是别的内容\n']
        cur = {'i': 0}
        measured = []

        def refresh(seg, xid, *a):
            measured.append(seg.seg.start)
            seg.raw = [(0, seg.seg.start, 10, 1)]
            return True
        with mock.patch.object(tr.windows, 'active_window', lambda: None), \
                mock.patch.object(tr.windows, 'is_shown', lambda x: True), \
                mock.patch.object(tr.windows, 'client_rect', lambda x: (0, 0, 100, 100)), \
                mock.patch.object(tr.windows, 'occluders', lambda x: []), \
                mock.patch.object(tr, '_find_terminal', lambda f, p: 'TERM'), \
                mock.patch.object(tr.Tracker, '_frame', lambda self, req: 'FRAME'), \
                mock.patch.object(tr.Tracker, '_pixels_usable', lambda self: False), \
                mock.patch.object(tr, '_refresh', refresh), \
                mock.patch.object(tr.T, 'get_character_count', lambda n: 0), \
                mock.patch.object(tr.T, 'get_text', lambda n, a, b: screens[cur['i']]):
            t = tr.Tracker(1)
            req = {'id': 'a', 'xid': 7, 'pid': 1, 'quote': '要找的那句话',
                   'anchor': {'method': 'atspi', 'role': 'terminal', 'path': [0], 'start': 3}}
            r = t.update([req], {'a'})
            self.assertEqual(r['items']['a']['state'], 'ok')
            cur['i'] = 1                                         # output pushed it down: found again at once
            r = t.update([req], {'a'})
            self.assertEqual(r['items']['a']['rects'][0][1], screens[1].index('要找的'))
            cur['i'] = 2                                         # scrolled away: offscreen, not missing
            r = t.update([req], {'a'})
            self.assertEqual(r['items']['a']['state'], 'offscreen')


class FollowerTest(unittest.TestCase):
    def test_follows_shifted_content(self):
        import numpy as np
        from marginalia.platform.x11 import motion
        rng = np.random.default_rng(1)
        page = rng.random((2000, 3 * motion.BINS)).astype(np.float32) * 200
        state = {'top': 500}

        def grab(xid, xs, y, w, h):
            return page[state['top'] + y: state['top'] + y + h]
        with mock.patch('marginalia.platform.x11.windows.client_rect', lambda xid: (0, 0, 800, 900)), \
                mock.patch.object(motion, 'grab_strip', grab):
            f = motion.Follower(1, 400, 450)
            self.assertEqual(f.step(), 0)
            state['top'] += 40                                  # content scrolled up by 40 px
            self.assertEqual(f.step(), -40)
            state['top'] += 25
            self.assertEqual(f.step(), -65)
            self.assertTrue(f.inside())
            for _ in range(5):                                  # a fling, frame by frame
                state['top'] += 120
                f.step()
            self.assertFalse(f.inside())                        # the point scrolled out of the window


if __name__ == '__main__':
    unittest.main()
