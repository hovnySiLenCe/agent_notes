"""Spike: locate a quote via AT-SPI in apps owned by given pids, print screen extents."""
import sys, time, subprocess, json
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

QUOTES = sys.argv[2:] or ["防止梯度爆炸的技术", "learning rate warmup"]
pattern = sys.argv[1]

def pids():
    out = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()
    return {int(p) for p in out}

def walk(node, found, depth=0, budget=[0]):
    budget[0] += 1
    if budget[0] > 20000 or depth > 60:
        return
    t = node if 'Text' in (node.get_interfaces() or []) else None
    if t is not None:
        try:
            n = Atspi.Text.get_character_count(t)
            s = Atspi.Text.get_text(t, 0, n) if n else ''
        except Exception:
            s = ''
        for q in QUOTES:
            i = s.find(q)
            if i >= 0:
                ext = Atspi.Text.get_range_extents(t, i, i + len(q), Atspi.CoordType.SCREEN)
                found.append(dict(quote=q, role=node.get_role_name(), off=i, len=n,
                                  rect=(ext.x, ext.y, ext.width, ext.height), node=node))
    for k in range(node.get_child_count()):
        try:
            c = node.get_child_at_index(k)
            if c: walk(c, found, depth + 1, budget)
        except Exception:
            pass

deadline = time.time() + 60
while True:
    want = pids()
    desk = Atspi.get_desktop(0)
    apps = [desk.get_child_at_index(i) for i in range(desk.get_child_count())]
    apps = [a for a in apps if a and a.get_process_id() in want]
    found = []
    t0 = time.time()
    for a in apps:
        walk(a, found, 0, [0])
    if found or time.time() > deadline:
        break
    time.sleep(3)
print('apps:', [(a.get_name(), a.get_process_id()) for a in apps], 'walk %.2fs' % (time.time() - t0))
for f in found:
    f.pop('node')
    print(json.dumps(f, ensure_ascii=False))
