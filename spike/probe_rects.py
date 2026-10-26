"""Spike: compare range / per-line / per-char extents for a quote."""
import sys, subprocess, time
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
T = Atspi.Text
SCREEN = Atspi.CoordType.SCREEN
pattern, quote = sys.argv[1], sys.argv[2]
want = {int(p) for p in subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True).stdout.split()}

def find(node, depth=0):
    if 'Text' in (node.get_interfaces() or []):
        n = T.get_character_count(node)
        s = T.get_text(node, 0, n)
        i = s.find(quote)
        if i >= 0 and node.get_role_name() != 'static':
            return node, i
    for k in range(node.get_child_count()):
        c = node.get_child_at_index(k)
        if c:
            r = find(c, depth + 1)
            if r: return r

desk = Atspi.get_desktop(0)
for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
    if a and a.get_process_id() in want:
        r = find(a)
        if r: break
node, i = r
j = i + len(quote)
e = T.get_range_extents(node, i, j, SCREEN); print('range', (e.x, e.y, e.width, e.height))
t0 = time.time()
chars = [T.get_character_extents(node, k, SCREEN) for k in range(i, j)]
dt = time.time() - t0
lines = {}
for c in chars:
    if c.width <= 0: continue
    l = lines.setdefault(c.y, [c.x, c.y, c.x + c.width, c.y + c.height])
    l[0] = min(l[0], c.x); l[2] = max(l[2], c.x + c.width); l[3] = max(l[3], c.y + c.height)
print('per-char lines', [(l[0], l[1], l[2]-l[0], l[3]-l[1]) for l in lines.values()], '%d chars %.1fms' % (len(chars), dt*1000))
print('first chars', [(c.x, c.y, c.width, c.height) for c in chars[:3]])
