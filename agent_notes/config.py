"""User config (JSON, hand-editable) and app state (window geometry etc.)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from .core.models import AnnoType

APP = 'agent-notes'


def config_dir() -> Path:
    base = os.environ.get('AGENT_NOTES_CONFIG_DIR') or \
        Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / APP
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    base = os.environ.get('AGENT_NOTES_DATA_DIR') or \
        Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / APP
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / 'config.json'


DEFAULT_TYPES = [
    {'id': 'expand', 'name': '展开', 'color': '#4C8BF5', 'hotkey': 'Shift+Alt+E', 'input': 'optional',
     'template': '【展开】{{#quote}}「{{quote}}」{{/quote}}→ 请更详细地解释这部分{{#comment}}，重点：{{comment}}{{/comment}}'},
    {'id': 'condense', 'name': '精简', 'color': '#22A06B', 'hotkey': 'Shift+Alt+W', 'input': 'optional',
     'template': '【精简】{{#quote}}「{{quote}}」{{/quote}}→ 这部分请压缩精简{{#comment}}，{{comment}}{{/comment}}'},
    {'id': 'ask', 'name': '追问', 'color': '#F5A623', 'hotkey': 'Shift+Alt+Q', 'input': 'required',
     'template': '【追问】{{#quote}}「{{quote}}」{{/quote}}→ {{comment}}'},
    {'id': 'fix', 'name': '纠错', 'color': '#E5484D', 'hotkey': '', 'input': 'optional',
     'template': '【纠错】{{#quote}}「{{quote}}」{{/quote}}→ 这里可能有误{{#comment}}：{{comment}}{{/comment}}，请核实并修正'},
    {'id': 'example', 'name': '换个例子', 'color': '#8E4EC6', 'hotkey': '', 'input': 'optional',
     'template': '【换个例子】{{#quote}}「{{quote}}」{{/quote}}→ 请换一个更贴切的例子{{#comment}}（{{comment}}）{{/comment}}'},
    {'id': 'code', 'name': '给出代码', 'color': '#0EA5A4', 'hotkey': '', 'input': 'optional',
     'template': '【给出代码】{{#quote}}「{{quote}}」{{/quote}}→ 请给出对应的代码示例{{#comment}}，要求：{{comment}}{{/comment}}'},
    {'id': 'keep', 'name': '保留', 'color': '#7C8594', 'hotkey': '', 'input': 'optional',
     'template': '【保留】{{#quote}}「{{quote}}」{{/quote}}→ 这部分很好，修改时请保留{{#comment}}（{{comment}}）{{/comment}}'},
]

DEFAULTS = {
    '_说明': {
        'hotkeys': '全局快捷键：menu=批注菜单, fill=填入（带提示语和类型说明）, fill_plain=仅填入引用和批注, '
                   'toggle_panel=显示/隐藏面板；格式如 Shift+Alt+S，留空表示不绑定',
        'types': '批注类型（最多前 9 个会出现在菜单里，按数字键选择）。input: none=直接保存 / optional=可选说明 / required=必须输入；'
                 'template 变量：{{quote}} {{comment}} {{name}}，{{#comment}}…{{/comment}} 表示有说明时才输出',
        'prompt': '拼装 prompt 的开头/结尾；quote_max_chars 为引用原文的最大长度（超出时省略中间）；'
                  'plain_template 为 fill_plain 时每条批注的格式',
        'panel': 'auto_collapse=鼠标离开后自动收起成小条（面板上 📌 可固定展开）；expand_distance=鼠标离小条多近（像素）就展开；'
                 'idle_opacity=收起时小条的不透明度，'
                 'opacity=展开时的不透明度，取值 0.15~1',
        'popup': 'opacity=批注弹窗的不透明度，取值 0.3~1',
        'fill': 'mode: fill=自动填入输入框 / copy=只复制到剪贴板；target: source=批注来源窗口 / active=按快捷键时的当前窗口；'
                'auto_send: 填入后自动按回车发送；mark_sent: 填入后把批注标记为已发送',
    },
    'hotkeys': {'menu': 'Shift+Alt+S', 'fill': 'Shift+Alt+Return', 'fill_plain': 'Alt+Return',
                'toggle_panel': 'Shift+Alt+D'},
    'types': DEFAULT_TYPES,
    'prompt': {'header': '请根据以下批注，修改或补充你上一条回复：', 'footer': '', 'quote_max_chars': 160,
               'plain_template': '{{#quote}}「{{quote}}」{{/quote}}{{#comment}} {{comment}}{{/comment}}'},
    'fill': {'mode': 'fill', 'target': 'source', 'auto_send': False, 'mark_sent': True},
    'panel': {'auto_collapse': True, 'expand_distance': 40, 'idle_opacity': 0.5, 'opacity': 0.96},
    'popup': {'opacity': 0.9},
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
