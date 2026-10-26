# Agent Notes

给任意 Agent 输出（网页、VS Code、桌面应用、终端 CLI）加批注的独立桌面程序（Linux X11）。
选中文字 → 快捷键 → 选类型/写说明 → 批注进入桌面悬浮面板 → 一键拼成 prompt 填回 Agent 输入框。

## 安装

```bash
./scripts/setup.sh      # 建 .venv（需系统 python3-gi / gir1.2-atspi-2.0），装 PySide6 + python-xlib
./run.sh                # 启动（重复启动只会唤出已运行实例的面板）
```

前提：开启系统无障碍（用于精确读取选区、定位输入框），开启后**重启浏览器 / VS Code**：

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
```

snap 版 Firefox 不跟随该开关，需在 `about:config` 把 `accessibility.force_disabled` 设为 `-1`。

## 使用

| 快捷键 | 作用 |
|---|---|
| `Shift+Alt+S` | 批注菜单（select；数字键 1-9 选类型） |
| `Shift+Alt+E` / `W` / `Q` | 直接添加 展开 / 精简 / 追问（query） |
| `Shift+Alt+Return` | 把面板中勾选的批注拼成完整 prompt（提示语 + 类型说明），填入来源窗口的输入框 |
| `Alt+Return` | 仅填入引用和批注（`1. 「引用」 批注`），不加提示语和类型说明 |
| `Shift+Alt+D` | 显示 / 隐藏悬浮面板 |

弹窗内：`Enter` 保存，`Shift+Enter` 换行，`Tab` 换类型，`Esc` 取消。
面板在鼠标离开后自动收起成一条半透明小标题栏（只显示条数），鼠标靠近（`panel.expand_distance`，默认 40px）即展开；点 📌 或双击标题栏可固定展开。
删除：卡片右上角 ✕（悬停显示）；标题栏 🗑：删除已勾选 / 清空已发送（历史）/ 清空全部（需确认），只作用于当前筛选的来源。
批注按时间倒序排列（最新在上，可拖动调整）；填入的 prompt 按添加先后编号，预览中可见实际内容。
已发送的批注可以重新勾选，再次填入。
面板内：拖动卡片排序，双击编辑，右键菜单（切换到来源窗口 / 标记状态 / 删除），“预览”查看将要填入的内容。

填入方式：普通应用用剪贴板 + `Ctrl+V`（先用无障碍接口找到并聚焦聊天输入框），终端用 PRIMARY + `Shift+Insert`；
完成后恢复原剪贴板。默认**不自动发送**。若无法切换到目标窗口，内容留在剪贴板并提示手动粘贴。

## 配置

`~/.config/agent-notes/config.json`（首次启动生成，保存后自动重新加载；面板 ⋯ 菜单可直接打开）。

自定义批注类型示例（`types` 列表整体替换默认值，前 9 个出现在菜单中）：

```json
{
  "types": [
    {"id": "expand", "name": "展开", "color": "#4C8BF5", "hotkey": "Shift+Alt+E", "input": "optional",
     "template": "【展开】{{#quote}}「{{quote}}」{{/quote}}→ 请更详细地解释这部分{{#comment}}，重点：{{comment}}{{/comment}}"},
    {"id": "source", "name": "给出处", "color": "#0EA5A4", "hotkey": "Shift+Alt+S", "input": "none",
     "template": "【给出处】「{{quote}}」→ 请给出这一说法的来源或依据"}
  ],
  "fill": {"mode": "fill", "target": "source", "auto_send": false}
}
```

- `input`：`none` 直接保存 / `optional` 可选说明 / `required` 必须填写
- `template` 变量：`{{quote}}` `{{comment}}` `{{name}}`；`{{#comment}}…{{/comment}}` 仅在有说明时输出
- `fill.mode`：`fill` 自动填入 / `copy` 只复制到剪贴板；`fill.target`：`source` 批注来源窗口 / `active` 当前窗口

数据：`~/.local/share/agent-notes/`（`notes.db` 批注、`state.json` 面板位置、`agent-notes.log` 日志）。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests                 # 单元测试
.venv/bin/python -m tests.e2e.run_e2e [firefox] [terminal] [vscode]   # 真实桌面端到端测试
```

端到端测试会自行启动临时的 Firefox / gnome-terminal / VS Code（禁用 GPU、nice 19），用模拟输入走完
“选中 → 快捷键 → 弹窗 → 保存 → 填入 → 读回校验”，每次发送按键前都会确认活动窗口是自己打开的测试窗口。

## 结构

```
agent_notes/
  core/        数据模型、SQLite 存储、模板、prompt 拼装（无 Qt / 平台依赖）
  platform/    平台抽象 base.py；x11/（窗口、XTest、全局快捷键）；atspi/（选区采集、输入框定位、坐标）
  ui/          悬浮面板、批注弹窗、提示、托盘、主题
  app.py       控制器：快捷键 → 采集 → 弹窗 → 存储 → 面板；拼装 → 填入
spike/         M0 可行性验证脚本与结论（FINDINGS.md）
```

## 路线图

- [x] M0 可行性验证
- [x] M1 快捷键、选区采集（含锚点）、批注弹窗、悬浮面板、存储、拼装、自动填入、自定义类型
- [ ] M2 原文高亮层（透明置顶覆盖层）、滚动跟随、遮挡裁剪、点击批注跳回原文
- [ ] M3 OCR 兜底、类型/模板图形化设置、划词气泡、状态流转（已解决）
- [ ] M4 AppImage 打包、开机自启；Windows（UIA）/ macOS（AX）移植
