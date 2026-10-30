@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   汉字拼音浮窗 / Hanzi Pinyin Popup
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 Python。
    echo 请先安装 Python 3.8 及以上版本，安装时勾选 "Add python.exe to PATH"。
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [错误] 当前 Python 缺少 tkinter，请安装官方版本 Python（不要用精简版）。
    pause
    exit /b 1
)

set "PYDEPS=pypinyin,pyperclip,pynput,pystray,PIL"
python -c "import pypinyin, pyperclip, pynput, pystray, PIL" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装依赖...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行: python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

rem 优先用 pythonw 启动，避免残留黑色控制台窗口
where pythonw >nul 2>nul
if errorlevel 1 (
    start "" python hanzi_pinyin.py
) else (
    start "" pythonw hanzi_pinyin.py
)
exit /b 0
