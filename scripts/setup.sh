#!/usr/bin/env bash
# One-time setup: venv (with system site-packages for the AT-SPI GObject bindings) + Python deps
# + libxcb-cursor0 for Qt's xcb plugin when the system lacks it (no sudo needed).
set -euo pipefail
cd "$(dirname "$0")/.."

if ! /usr/bin/python3 -c "import gi; gi.require_version('Atspi', '2.0')" 2>/dev/null; then
    echo "缺少 AT-SPI Python 绑定，请先执行：sudo apt install python3-gi gir1.2-atspi-2.0" >&2
    exit 1
fi
[ -d .venv ] || /usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/pip install -q -r requirements.txt

if ! ldconfig -p | grep -q 'libxcb-cursor.so.0'; then
    mkdir -p .venv/syslibs
    (cd .venv/syslibs && apt download libxcb-cursor0 >/dev/null && dpkg -x libxcb-cursor0_*.deb root)
    echo "已在本地解压 libxcb-cursor0（.venv/syslibs）"
fi

if [ "$(gsettings get org.gnome.desktop.interface toolkit-accessibility 2>/dev/null)" != "true" ]; then
    echo "提示：系统无障碍未开启，选区定位/输入框定位需要它：" >&2
    echo "  gsettings set org.gnome.desktop.interface toolkit-accessibility true" >&2
    echo "  （开启后需重启浏览器 / VS Code）" >&2
fi
echo "完成。启动：./run.sh"
