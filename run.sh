#!/usr/bin/env sh
# Linux / macOS 启动脚本
set -e
cd "$(dirname "$0")"

if ! python3 -c "import pypinyin, pynput, pystray, PIL" >/dev/null 2>&1; then
    echo "正在安装依赖..."
    python3 -m pip install -r requirements.txt
fi

# Linux 下 pystray 需要 GTK/AppIndicator 支持
if [ "$(uname -s)" = "Linux" ] && ! python3 -c "import pystray" >/dev/null 2>&1; then
    echo "[提示] 托盘图标依赖缺失，Debian/Ubuntu 可执行："
    echo "       sudo apt install python3-gi gir1.2-appindicator3-0.1"
fi

exec python3 hanzi_pinyin.py "$@"
