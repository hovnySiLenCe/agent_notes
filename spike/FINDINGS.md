# M0 可行性验证结论（2026-10-22，Ubuntu 22.04 / GNOME / X11，2x 缩放）

运行环境：`/usr/bin/python3 -m venv --system-site-packages .venv`（需要系统 gi/Atspi）+ PySide6 + python-xlib；
PySide6 xcb 插件需要 `libxcb-cursor0`，已解压到 `.venv/syslibs`，运行时设 `LD_LIBRARY_PATH`。
前提：`gsettings set org.gnome.desktop.interface toolkit-accessibility true`；Chromium/Electron 应用需重启或加 `--force-renderer-accessibility`。

| 能力 | Firefox | VS Code webview / Chat | gnome-terminal (CLI) |
|---|---|---|---|
| 读文本 | ✅ | ✅ | ✅ |
| 字符屏幕坐标 → 高亮 | ✅ 逐字 `get_character_extents` | ✅ | ⚠️ VTE 坐标需修正（见下）→ ✅ |
| 应用内遮挡判断（命中测试） | ✅ 从 frame 开始 | ✅ 必须从最外层 `document web` 开始 | — |
| 选区偏移量（AT-SPI） | ✅ | ✅ | 未测 |
| PRIMARY 选区 | 仅鼠标真实划选才写入 | ✅ | ✅ |
| 找输入框并聚焦 | ✅ `entry`（需在 `document web` 内，排除地址栏；不可见先 `scroll_to`） | ✅ `entry "Chat Input"` | 不需要 |
| 填入 | ✅ 剪贴板 + XTest Ctrl+V | ✅ 同左 | ✅ 写 PRIMARY + Shift+Insert（XTest 的 Ctrl+Shift+V 不生效） |

## 坑与解法
- **窗口激活**：`_NET_ACTIVE_WINDOW` 用 `CurrentTime` 会被 mutter 防抢焦点拒绝 → 用 PropertyNotify 取真实服务器时间戳（`x11util.server_time`）。
- **VTE 坐标**：返回逻辑坐标（未乘缩放）、屏幕原点错误、且宽字符按 1 格计 → 行 y 用 VTE 值，x = 行首 x + Σ显示宽度（东亚宽字符 2 格），再 ×scale + X 窗口原点（`term_rects.py`）。
- **系统级遮挡**：高亮层会画在挡住目标的其它窗口上 → 需按 `_NET_CLIENT_LIST_STACKING` 裁剪。
- **Chromium 被遮挡时停止重绘**：XComposite 抓到的是旧画面 → OCR 兜底只对可见窗口有效。
- **按 AT-SPI 名称点按钮要限定在 dialog 内**：VS Code 自绘标题栏里也有"关闭"按钮。
- **进程匹配**：`pkill -f <串>` 会匹配到执行命令的 shell 自身；终端定位要按窗口标题（frame name）而非内容。

## 快捷键
X11 层面 `Shift+Alt+{A,E,R,Q,Space,Return,1,2,3,H}` 均未被占用；但全局抢占会覆盖应用内快捷键，
VS Code 默认 `Shift+Alt+A`(块注释)、`Shift+Alt+R`(在文件管理器中显示)、`Shift+Alt+F`(格式化)、`Shift+Alt+I`、`Shift+Alt+↑↓` 会被吃掉。
