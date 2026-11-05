# Agent Notes

给任意 Agent 输出（网页、VS Code、桌面应用、终端 CLI）加批注的独立桌面程序（Linux X11）。
选中文字 → 快捷键 → 选类型/写说明 → 批注进入桌面悬浮面板，原文上出现高亮 → 一键拼成 prompt 填回 Agent 输入框。

## 安装

```bash
./scripts/setup.sh      # 建 .venv（需系统 python3-gi / gir1.2-atspi-2.0），装 PySide6-Essentials + python-xlib
./run.sh                # 在后台启动后立即返回；关掉终端也不影响。已在运行时只唤出面板
```

| 命令 | 作用 |
|---|---|
| `./run.sh` | 后台启动（已在运行则显示面板；旧实例卡死/被挂起时自动结束它再启动） |
| `./run.sh --status` | 是否在运行（PID） |
| `./run.sh --stop` / `--restart` | 停止 / 重启（更新代码后用 `--restart`） |
| `./run.sh -f` | 在当前终端前台运行，日志直接输出，`Ctrl+C` 退出 |
| `./run.sh --autostart on\|off` | 登录桌面时自动启动（写入 `~/.config/autostart/agent-notes.desktop`） |
| `./run.sh --setup-firefox` | 为 Firefox 打开无障碍接口（重启 Firefox 后生效），用于精确定位与高亮 |

后台运行的输出在 `~/.local/share/agent-notes/agent-notes.out`，日志在同目录 `agent-notes.log`。

**PySide6 6.12.0 有缺陷**：每次发出 Qt 信号都会少计一次 `True` 的引用，累计几千次后进程以 `free(): invalid pointer` 崩溃
（划词按钮每次点鼠标都会发信号，几分钟就会闪退）。`requirements.txt` 已排除该版本，旧环境重新运行一次 `./scripts/setup.sh` 即可换成 6.11.x；
即使装的是 6.12.0，程序启动时也会检测并绕过（日志里有一条 WARNING）。

前提：开启系统无障碍（用于精确读取选区、定位输入框），开启后**重启浏览器 / VS Code**：

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
```

snap 版 Firefox 不跟随该开关：运行 `./run.sh --setup-firefox`（在各 Firefox 配置目录的 `user.js` 写入
`accessibility.force_disabled = -1`），然后**完全退出并重开 Firefox**；也可在 `about:config` 手动改。
Chrome / Chromium / VS Code 等 Electron 应用若没有开启，可在启动参数加 `--force-renderer-accessibility`。
某个应用没开无障碍接口时，第一次在其中添加批注会弹出提示告诉你怎么开。

## 使用

| 快捷键 | 作用 |
|---|---|
| `Shift+Alt+S` | 批注菜单（select；数字键 1-9 选类型） |
| `Shift+Alt+E` / `W` / `Q` | 直接添加 展开 / 精简 / 追问（query） |
| `Shift+Alt+Return` | 把面板中勾选的批注拼成完整 prompt（提示语 + 类型说明），填入来源窗口的输入框 |
| `Alt+Return` | 仅填入引用和批注（`1. 「引用」 批注`），不加提示语和类型说明 |
| `Shift+Alt+D` | 显示 / 隐藏悬浮面板 |

默认类型：展开、精简、追问、纠错、换个例子、给出代码、保留、忽略（告诉 Agent 这部分不用管，后续回复中不必再处理或提及）。

弹窗内：`Enter` 保存，`Shift+Enter` 换行，`Tab` 换类型，`Esc` 取消。

**划词按钮**：用鼠标选中文字（拖选、双击）后，指针旁会出现一排类型按钮（前 4 个类型 + `⋯` 打开完整菜单），
点一下等同于按对应快捷键。它不抢焦点、不影响选区；不理会约 3.5 秒后消失，点别处立即消失。
键盘选择不会弹出。面板 ⋯ 菜单可关闭（`bubble.enabled`）。
面板在鼠标离开后自动收起成一条半透明小标题栏（只显示条数），鼠标靠近（`panel.expand_distance`，默认 40px）即展开；点 📌 或双击标题栏可固定展开。
状态：**待发送** → 填入后自动变为 **已发送**（仍可重新勾选再次填入）→ Agent 的回答解决了问题后点卡片上的 ✓ 标记为 **已解决**
（不再勾选、不再高亮；↺ 可重新打开）。右键菜单可以在三种状态之间任意切换。
删除：卡片右上角 ✕（悬停显示）；标题栏 🗑：删除已勾选 / 清空已发送 / 清空已解决 / 清空全部（需确认），只作用于当前筛选的来源。
批注按时间倒序排列（最新在上，可拖动调整）；填入的 prompt 按添加先后编号，预览中可见实际内容。
已发送的批注可以重新勾选，再次填入。
面板内：拖动卡片排序，右键菜单（跳到原文 / 编辑 / 复制引用 / 标记状态 / 删除），“预览”查看将要填入的内容。

### 原文高亮

- 在某个窗口里工作时，该窗口里**待发送**批注对应的原文会被标上类型颜色的半透明高亮（`highlight.show` 可改为 `all` 包括已发送的，或 `hover` 只在悬停时显示）。
- 高亮跟随滚动；滚出视野、被浏览器工具栏或其它窗口挡住的部分不画；高亮层不接收鼠标，不影响点击和选字。
- 鼠标**悬停在卡片上**：对应原文加深显示（即使不在当前窗口）。
- **双击卡片**或点卡片上的 ⌖：切到来源窗口，把原文滚动到可见处并闪烁高亮。
- 卡片上的小标记：◉ 原文可见 / ○ 已滚出视野 / ⚠ 原文找不到（页面关了或内容变了）。
- 面板 ⋯ 菜单可临时关闭高亮。没有窗口合成器（compositor）时只画下划线，不遮挡文字。
- VS Code 等 Electron 应用（含 Claude Code 等扩展的聊天面板）同样支持：它们的原生界面按逻辑像素、网页内容按物理像素报告坐标，
  裁剪只在网页内容内部进行，所以高缩放比例下也能画出来。
- 引用的原文以系统 PRIMARY 选区为准（即复制时得到的文字）：Chromium 只在选区首尾节点报告选区，中间的列表项、段落会漏掉，
  这时用 PRIMARY 的完整文字，并按文字找回原文位置。
- 定位依赖无障碍接口。应用没有报告选区位置、只拿到了选中的文字时，会在该窗口的无障碍树里按文字查找原文来补上锚点
  （忽略换行/空白差异；从表格复制的多列文字按单元格分段匹配）；应用完全没有无障碍接口时没有高亮，双击只切换窗口。

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
    {"id": "source", "name": "给出处", "color": "#0EA5A4", "hotkey": "Shift+Alt+G", "input": "none",
     "template": "【给出处】「{{quote}}」→ 请给出这一说法的来源或依据"}
  ],
  "fill": {"mode": "fill", "target": "source", "auto_send": false}
}
```

- `input`：`none` 直接保存 / `optional` 可选说明 / `required` 必须填写
- `template` 变量：`{{quote}}` `{{comment}}` `{{name}}`；`{{#comment}}…{{/comment}}` 仅在有说明时输出
- `fill.mode`：`fill` 自动填入 / `copy` 只复制到剪贴板；`fill.target`：`source` 批注来源窗口 / `active` 当前窗口
- `highlight.enabled`：是否在原文上画高亮；`highlight.show`：`pending` / `all`（不含已解决）/ `hover`
- `bubble.enabled`：选中文字后显示划词按钮；`bubble.types`：显示前几个类型；`bubble.timeout_ms`：自动消失时间
- `panel`：`auto_collapse`、`expand_distance`、`idle_opacity`、`opacity`；`popup.opacity`

配置文件的修改会自动生效（系统 inotify 监视数用尽时改为每 2 秒检查一次修改时间）。

数据：`~/.local/share/agent-notes/`（`notes.db` 批注、`state.json` 面板位置、`agent-notes.log` 日志）。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -t .                       # 单元测试（无窗口）
./scripts/setup.sh --test                                                 # 一次性：本地解压 Xvfb（无需 sudo）
.venv/bin/python -m tests.e2e.sandbox -- .venv/bin/python -m tests.e2e.run_e2e firefox highlight bubble
                                                                          # 端到端测试，在不可见的虚拟桌面里跑
.venv/bin/python -m tests.e2e.run_e2e [firefox] [terminal] [vscode] [highlight] [bubble]   # 在真实桌面上跑
```

端到端测试会自行启动临时的 Firefox / gnome-terminal / VS Code（禁用 GPU、nice 19），用模拟输入走完
“选中 → 快捷键 → 弹窗 → 保存 → 填入 → 读回校验”，高亮的“绘制 → 滚动跟随 → 遮挡裁剪 → 双击跳回原文”，
以及划词按钮的“鼠标拖选 → 按钮出现且不抢焦点 → 点别处消失 → 点类型 → 弹窗 → 保存”。
每个场景用独立的程序实例和数据目录；每次发送按键前都会确认活动窗口是自己打开的测试窗口。

`tests.e2e.sandbox` 启动 Xvfb + 私有 D-Bus/无障碍总线 + 一个极简窗口管理器（`tests/e2e/miniwm.py`），
屏幕上什么都不出现、不抢焦点、不碰真实剪贴板，可以边工作边跑。snap 版 Firefox 会被放进 snap 要求的 systemd scope 里启动。
（沙箱里还跑不了 gnome-terminal 和 VS Code 场景，这两个仍需真实桌面。）

## 结构

```
agent_notes/
  core/        数据模型、SQLite 存储、模板、prompt 拼装、原文重定位（anchor.py）（无 Qt / 平台依赖）
  platform/    平台抽象 base.py；x11/（窗口、层叠与遮挡、XTest、全局快捷键、鼠标划词监听 selwatch.py）；
               atspi/（选区采集、输入框定位、坐标、原文定位 locate.py、滚动跟踪 tracker.py）
  ui/          悬浮面板、批注弹窗、高亮层 overlay.py、划词按钮 bubble.py、提示、托盘、主题
  highlight.py 高亮控制：选哪些批注、轮询位置、遮挡裁剪、跳回原文
  ipc.py       命令行与运行中实例的通信（--status / --stop / 单实例）
  app.py       控制器：快捷键 → 采集 → 弹窗 → 存储 → 面板；拼装 → 填入
tests/e2e/     端到端测试、不可见沙箱（sandbox.py、miniwm.py）
spike/         M0 可行性验证脚本与结论（FINDINGS.md）
```

## 路线图

- [x] M0 可行性验证
- [x] M1 快捷键、选区采集（含锚点）、批注弹窗、悬浮面板、存储、拼装、自动填入、自定义类型
- [x] M2 原文高亮层（透明置顶覆盖层）、滚动跟随、遮挡裁剪、点击批注跳回原文；后台运行与 `--status/--stop/--restart/--autostart`
- [ ] M3 采集增强（✅ 纯文字采集按文字补锚点、✅ 无障碍未开启提示与 `--setup-firefox`、OCR 兜底）、✅ 划词按钮、✅ 状态流转（已解决）、类型/模板图形化设置
- [ ] M4 AppImage 打包；Windows（UIA）/ macOS（AX）移植
