# -*- coding: utf-8 -*-
"""程序位置与手写引擎相关的小工具。

原来是外壳里的 app_dir / handwriting_* 一组函数。搬到包内后 __file__ 变成
hpp/paths.py，所以开发态要往上退一层才是项目根——不然手写模型会去找
hpp/models/handwriting.onnx。
"""

from __future__ import annotations

import os
import subprocess
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    # 本文件在 hpp/ 里，开发态的项目根是它上一层（原先是外壳脚本所在目录）
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def handwriting_model_path() -> str:
    return os.path.join(app_dir(), "models", "handwriting.onnx")


def handwriting_status(engine: str) -> str:
    if engine == "offline":
        path = handwriting_model_path()
        if not os.path.exists(path):
            return "离线模型未找到：models/handwriting.onnx（本期未随包提供）"
        return "离线模型已就绪：models/handwriting.onnx"
    return "系统手写：Windows Ink 微软同款识别器"


def open_system_handwriting(app) -> bool:
    """唤起 Windows 手写面板，并把焦点交给本程序输入框。

    识别由微软自带的手写识别器完成（与系统输入法同一套引擎），出字后直接落进
    输入框，主窗口会自动注音——这就是 US12 说的「系统引擎优先」。
    """
    try:
        app.show()
        app._focus_entry()
    except Exception:
        pass

    for path in (
        r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe",
        r"C:\Program Files (x86)\Common Files\microsoft shared\ink\TabTip.exe",
    ):
        if os.path.exists(path):
            try:
                subprocess.Popen([path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return True
            except Exception:
                break
    # 兜底：Win + Ctrl + O（系统触摸键盘快捷键）
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.cmd):
            with kb.pressed(Key.ctrl):
                kb.press("o")
                kb.release("o")
        return True
    except Exception as exc:
        print(f"[warn] 唤起系统手写面板失败：{exc}", file=sys.stderr)
        return False
