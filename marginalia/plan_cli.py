"""Sending plans to the running app from the command line, and the Claude Code hook that does it after every reply.
No Qt here: the hook runs after each agent turn and must be quick and silent."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import ipc
from .core.plans import extract

ROOT = Path(__file__).resolve().parent.parent
HOOK_MARK = '--plan-hook'
CLAUDE_SETTINGS = Path.home() / '.claude' / 'settings.json'
TAIL_BYTES = 4 << 20            # the end of a transcript that is searched for the last reply


def ancestors(pid: int | None = None) -> list[int]:
    """This process and its parents, up to init: the app looks for windows owned by one of them."""
    out, pid = [], pid or os.getpid()
    while pid > 1 and len(out) < 64:
        out.append(pid)
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
            pid = int(stat[stat.rindex(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def project_name(cwd: str | None) -> str:
    """The git repository's folder name, else the folder's own name."""
    cwd = cwd or os.getcwd()
    try:
        top = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                             timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        top = ''
    return Path(top or cwd).name or 'default'


def send(project: str, text: str, category: str | None = None, cwd: str | None = None, agent: str = '') -> bool:
    payload = {'project': project, 'text': text, 'category': category, 'pids': ancestors(), 'cwd': cwd or os.getcwd(),
               'agent': agent}
    return ipc.request('plan ' + json.dumps(payload, ensure_ascii=False), timeout=3.0) is not None


def cmd_plan(project: str | None, path: str | None, category: str | None) -> int:
    text = sys.stdin.read() if not path or path == '-' else Path(path).read_text(encoding='utf-8')
    if not text.strip():
        print('计划内容为空', file=sys.stderr)
        return 1
    project = project or project_name(None)
    plan = extract(text) or text                      # a whole reply works too: its plan section is used
    if not send(project, plan, category):
        print('Marginalia 没有运行（./run.sh 启动）', file=sys.stderr)
        return 1
    print(f'已发送到 Marginalia：{project}')
    return 0


# ---- Claude Code hook ---------------------------------------------------------------------------------------------
def _texts(entry: dict) -> list[str]:
    msg = entry.get('message') or {}
    content = msg.get('content')
    if isinstance(content, str):
        return [content]
    return [c.get('text', '') for c in content or [] if isinstance(c, dict) and c.get('type') == 'text']


def last_reply(transcript: Path) -> str | None:
    """The text of the last assistant message in a Claude Code transcript (JSONL), read from its end."""
    try:
        size = transcript.stat().st_size
        with transcript.open('rb') as f:
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().split(b'\n')
    except OSError:
        return None
    for raw in reversed(lines):
        if b'"assistant"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get('type') != 'assistant':
            continue
        texts = [t for t in _texts(entry) if t.strip()]
        if texts:
            return texts[-1]
    return None


def cmd_hook() -> int:
    """Claude Code `Stop` hook: send the plan at the end of the reply just finished. Never fails the agent."""
    try:
        data = json.loads(sys.stdin.read() or '{}')
        reply = data.get('last_assistant_message') if isinstance(data.get('last_assistant_message'), str) else None
        plan = extract(reply) if reply else None
        path = data.get('transcript_path')
        for _ in range(4):                            # the transcript may get the last line a moment later
            if plan or not path:
                break
            plan = extract(last_reply(Path(path)) or '')
            if not plan:
                time.sleep(0.25)
        if plan:
            cwd = data.get('cwd') or os.getcwd()
            send(project_name(cwd), plan, cwd=cwd, agent='claude-code')
    except Exception:                                 # noqa: BLE001 - a hook must never get in the agent's way
        pass
    return 0


def hook_command() -> str:
    return f'{ROOT / "run.sh"} {HOOK_MARK}'


def install_claude_hook(on: bool, settings: Path = CLAUDE_SETTINGS) -> int:
    try:
        data = json.loads(settings.read_text(encoding='utf-8')) if settings.exists() else {}
    except ValueError as e:
        print(f'{settings} 不是有效的 JSON，未修改：{e}', file=sys.stderr)
        return 1
    hooks = data.setdefault('hooks', {})
    stop = [g for g in hooks.get('Stop', []) if not any(HOOK_MARK in (h.get('command') or '')
                                                        for h in g.get('hooks', []))]
    if on:
        stop.append({'hooks': [{'type': 'command', 'command': hook_command(), 'timeout': 10}]})
    if stop:
        hooks['Stop'] = stop
    else:
        hooks.pop('Stop', None)
    if not hooks:
        data.pop('hooks', None)
    if settings.exists():
        backup = settings.with_name(settings.name + '.marginalia.bak')
        shutil.copy2(settings, backup)
        print(f'已备份原文件：{backup}')
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if on:
        print(f'已在 {settings} 加入 Stop 钩子：Claude Code 每次回复结束后，把回复末尾的「计划」发给 Marginalia。')
    else:
        print(f'已从 {settings} 移除 Marginalia 的钩子。')
    return 0
