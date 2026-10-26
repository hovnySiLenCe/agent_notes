"""Spike: inside test VS Code, press buttons located only inside role=dialog (never the window frame)."""
import subprocess, time, gi
gi.require_version('Atspi','2.0')
from gi.repository import Atspi
def app():
    pids={int(p) for p in subprocess.run(['pgrep','-f','vscode-ud'],capture_output=True,text=True).stdout.split()}
    desk=Atspi.get_desktop(0)
    for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count())):
        if a and a.get_process_id() in pids: return a
def dialogs(n, out):
    if n.get_role_name() in ('dialog','alert'): out.append(n); return
    for k in range(n.get_child_count()):
        c=n.get_child_at_index(k)
        if c: dialogs(c,out)
def buttons(n,out):
    if n.get_role_name()=='push button': out.append(n)
    for k in range(n.get_child_count()):
        c=n.get_child_at_index(k)
        if c: buttons(c,out)
deadline=time.time()+40; a=None
while time.time()<deadline:
    a=app()
    if a and a.get_child_count(): 
        ds=[]; dialogs(a,ds)
        if ds: break
    time.sleep(2)
for round_ in range(6):
    ds=[]; dialogs(a,ds)
    if not ds: print('no dialog'); break
    bs=[]; [buttons(d,bs) for d in ds]
    names=[b.get_name() or '' for b in bs]; print('dialog buttons', names)
    pick=next((b for b in bs if (b.get_name() or '') in ('Continue without Signing In','Skip','Close','Done')), None) \
         or next((b for b in bs if 'Skip' in (b.get_name() or '') or 'Close' in (b.get_name() or '')), None)
    if not pick: break
    print('press', pick.get_name(), Atspi.Action.do_action(pick,0)); time.sleep(1.5)
