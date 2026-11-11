"""User config (JSON, hand-editable) and app state (window geometry etc.)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from .core.models import AnnoType

APP = 'marginalia'
OLD_APP = 'agent-notes'      # the name before Marginalia: its config and data are moved over once


def _config_home() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def _data_home() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')


def config_dir() -> Path:
    p = Path(os.environ.get('MARGINALIA_CONFIG_DIR') or _config_home() / APP)
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = Path(os.environ.get('MARGINALIA_DATA_DIR') or _data_home() / APP)
    p.mkdir(parents=True, exist_ok=True)
    return p


def migrate_old_dirs() -> list[str]:
    """Move ~/.config/agent-notes and ~/.local/share/agent-notes to the new names (unless overridden by the
    environment or already there). Returns what was moved."""
    moved = []
    for env, home in (('MARGINALIA_CONFIG_DIR', _config_home()), ('MARGINALIA_DATA_DIR', _data_home())):
        old, new = home / OLD_APP, home / APP
        if not os.environ.get(env) and old.is_dir() and not new.exists():
            old.rename(new)
            moved.append(f'{old} → {new}')
    return moved


def config_path() -> Path:
    return config_dir() / 'config.json'


DEFAULT_TYPES = [   # the menu shows 4 per row; order = keys 1-9, 0
    # row 1 in the menu (and the selection bubble): one-click verdicts. Simple tags (YES / NO / 已解决 / 忽略 /
    # 保留) use input 'none': picked = saved, no comment box.
    {'id': 'agree', 'name': 'YES', 'color': '#16A34A', 'hotkey': 'Shift+Alt+Y', 'input': 'none',
     'template': '【YES】{{#quote}}「{{quote}}」{{/quote}}→ 同意这一点，按这个思路继续{{#comment}}（{{comment}}）{{/comment}}'},
    {'id': 'disagree', 'name': 'NO', 'color': '#C2185B', 'hotkey': 'Shift+Alt+N', 'input': 'none',
     'template': '【NO】{{#quote}}「{{quote}}」{{/quote}}→ 我不同意这一点{{#comment}}：{{comment}}{{/comment}}，请重新考虑'},
    {'id': 'solved', 'name': '已解决', 'color': '#64748B', 'hotkey': '', 'input': 'none',
     'template': '【已解决】{{#quote}}「{{quote}}」{{/quote}}→ 这个问题已经解决了，不用再处理{{#comment}}（{{comment}}）{{/comment}}'},
    {'id': 'ignore', 'name': '忽略', 'color': '#A0785A', 'hotkey': '', 'input': 'none',
     'template': '【忽略】{{#quote}}「{{quote}}」{{/quote}}→ 这部分不用管，后续回复中不必再处理或提及{{#comment}}（{{comment}}）{{/comment}}'},
    # row 2: remarks and corrections, ask for more
    {'id': 'ask', 'name': 'REMARK', 'color': '#F5A623', 'hotkey': 'Shift+Alt+Q', 'input': 'required',
     'template': '【REMARK】{{#quote}}「{{quote}}」{{/quote}}→ {{comment}}'},
    {'id': 'fix', 'name': '纠错', 'color': '#E5484D', 'hotkey': '', 'input': 'optional',
     'template': '【纠错】{{#quote}}「{{quote}}」{{/quote}}→ 这里可能有误{{#comment}}：{{comment}}{{/comment}}，请核实并修正'},
    {'id': 'expand', 'name': '展开', 'color': '#4C8BF5', 'hotkey': 'Shift+Alt+E', 'input': 'optional',
     'template': '【展开】{{#quote}}「{{quote}}」{{/quote}}→ 请更详细地解释这部分{{#comment}}，重点：{{comment}}{{/comment}}'},
    {'id': 'condense', 'name': '精简', 'color': '#6366F1', 'hotkey': 'Shift+Alt+W', 'input': 'optional',
     'template': '【精简】{{#quote}}「{{quote}}」{{/quote}}→ 这部分请压缩精简{{#comment}}，{{comment}}{{/comment}}'},
    # row 3: other rewrites, keep
    {'id': 'example', 'name': '换个例子', 'color': '#8E4EC6', 'hotkey': '', 'input': 'optional',
     'template': '【换个例子】{{#quote}}「{{quote}}」{{/quote}}→ 请换一个更贴切的例子{{#comment}}（{{comment}}）{{/comment}}'},
    {'id': 'code', 'name': '给出代码', 'color': '#0EA5A4', 'hotkey': '', 'input': 'optional',
     'template': '【给出代码】{{#quote}}「{{quote}}」{{/quote}}→ 请给出对应的代码示例{{#comment}}，要求：{{comment}}{{/comment}}'},
    {'id': 'keep', 'name': '保留', 'color': '#84A63A', 'hotkey': '', 'input': 'none',
     'template': '【保留】{{#quote}}「{{quote}}」{{/quote}}→ 这部分很好，修改时请保留{{#comment}}（{{comment}}）{{/comment}}'},
]

DEFAULTS = {
    '_说明': {
        'hotkeys': '全局快捷键：menu=批注菜单, fill=填入（带提示语和类型说明）, fill_plain=仅填入引用和批注, '
                   'toggle_panel=显示/隐藏面板；格式如 Shift+Alt+S，留空表示不绑定',
        'types': '批注类型（菜单每行 4 个，按 1-9、0 选前 10 个，其余用方向键）。input: none=直接保存 / optional=可选说明 / required=必须输入；'
                 'template 变量：{{quote}} {{comment}} {{name}}，{{#comment}}…{{/comment}} 表示有说明时才输出',
        'prompt': '拼装 prompt 的开头/结尾；quote_max_chars 为引用原文的最大长度（超出时省略中间）；'
                  'plain_template 为 fill_plain 时每条批注的格式；trailing_newline 为 true 时填入的内容末尾多一个换行'
                  '（光标落在新的一行，方便接着写；填入终端时不加，以免直接执行）',
        'panel': 'auto_collapse=鼠标离开后自动收起成小条（面板上 📌 可固定展开）；expand_distance=鼠标离小条多近（像素）就展开；'
                 'idle_opacity=收起时小条的不透明度，'
                 'opacity=展开时的不透明度，取值 0.15~1',
        'popup': 'opacity=批注弹窗的不透明度，取值 0.3~1',
        'highlight': 'enabled=在原文上画高亮（面板 ⋯ 菜单里也可临时关闭）；show: pending=高亮当前窗口里待发送的批注 / '
                     'all=包括已发送的 / hover=只在鼠标悬停卡片或跳转时高亮',
        'bubble': 'enabled=用鼠标选中文字后，在指针旁弹出一排批注类型按钮（面板 ⋯ 菜单里也可关闭）；'
                  'types=显示前几个类型；timeout_ms=不理会时多久后自动消失',
        'fill': 'mode: fill=自动填入输入框 / copy=只复制到剪贴板；target: source=批注来源窗口 / active=按快捷键时的当前窗口；'
                'auto_send: 填入后自动按回车发送；mark_sent: 填入后把批注标记为已发送',
    },
    'hotkeys': {'menu': 'Shift+Alt+S', 'fill': 'Shift+Alt+Return', 'fill_plain': 'Alt+Return',
                'toggle_panel': 'Shift+Alt+D'},
    'types': DEFAULT_TYPES,
    'prompt': {'header': '请根据以下批注，修改或补充你上一条回复：', 'footer': '', 'quote_max_chars': 160,
               'trailing_newline': False,
               'plain_template': '{{#quote}}「{{quote}}」{{/quote}}{{#comment}} {{comment}}{{/comment}}'},
    'fill': {'mode': 'fill', 'target': 'source', 'auto_send': False, 'mark_sent': True},
    'panel': {'auto_collapse': True, 'expand_distance': 40, 'idle_opacity': 0.5, 'opacity': 0.96},
    'popup': {'opacity': 0.9},
    'highlight': {'enabled': True, 'show': 'pending'},
    'bubble': {'enabled': True, 'types': 4, 'timeout_ms': 3500},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)   # lists (e.g. types) are replaced wholesale
    return out


class Config:
    def __init__(self, data: dict):
        self.data = data
        self.types = [AnnoType.from_dict(t) for t in data['types']]
        ids = [t.id for t in self.types]
        if len(set(ids)) != len(ids):
            raise ValueError('批注类型 id 有重复')
        self.type_map = {t.id: t for t in self.types}

    @property
    def prompt(self) -> dict:
        return self.data['prompt']

    @property
    def fill(self) -> dict:
        return self.data['fill']

    @property
    def panel(self) -> dict:
        return self.data['panel']

    def hotkey_bindings(self) -> dict[str, str]:
        """action -> key spec; per-type hotkeys become `type:<id>` actions."""
        b = {k: v for k, v in self.data['hotkeys'].items() if v}
        b.update({f'type:{t.id}': t.hotkey for t in self.types if t.hotkey})
        return b

    @classmethod
    def load(cls, path: Path | None = None) -> tuple['Config', str | None]:
        """Returns (config, error). On a broken file the defaults are used and the error is reported."""
        path = path or config_path()
        if not path.exists():
            path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            user = json.loads(path.read_text(encoding='utf-8'))
            return cls(_merge(DEFAULTS, user)), None
        except (ValueError, TypeError, KeyError) as e:
            return cls(copy.deepcopy(DEFAULTS)), f'配置文件有误，已使用默认配置：{e}'


def load_state() -> dict:
    try:
        return json.loads((data_dir() / 'state.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    (data_dir() / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
