"""剪贴板与选区抓取。

CLIP_WIDGET 由主窗口通过 set_clip_widget() 注入，用于走 Tk 的剪贴板通道
（pyperclip 缺失时的兜底）。
"""
from __future__ import annotations

import time

try:
    import pyperclip  # 跨平台剪贴板
except ImportError:  # pragma: no cover
    pyperclip = None

from .selection import read_selection_uia

# --------------------------------------------------------------------------
# 剪贴板
# --------------------------------------------------------------------------
CLIP_WIDGET = None


def read_clipboard() -> str:
    if pyperclip is not None:
        try:
            return pyperclip.paste() or ""
        except Exception:
            pass
    if CLIP_WIDGET is not None:
        try:
            return CLIP_WIDGET.clipboard_get() or ""
        except Exception:
            return ""
    return ""


def write_clipboard(text: str) -> None:
    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            return
        except Exception:
            pass
    if CLIP_WIDGET is not None:
        try:
            CLIP_WIDGET.clipboard_clear()
            CLIP_WIDGET.clipboard_append(text)
        except Exception:
            pass


def set_clip_widget(widget) -> None:
    """注入主窗口控件，供 Tk 剪贴板通道兜底使用。"""
    global CLIP_WIDGET
    CLIP_WIDGET = widget


def grab_selection(preserve: bool = True) -> str:
    """抓取当前选中的文字。

    先走 UIA（不动剪贴板）；拿不到再退回「备份剪贴板 → 模拟 Ctrl+C → 读 → 还原」。
    preserve=True 时会把用户原来的剪贴板内容放回去。
    """
    text = read_selection_uia()
    if text:
        return text

    old = read_clipboard()
    try:
        from pynput.keyboard import Controller, Key

        kbd = Controller()
        with kbd.pressed(Key.ctrl):
            kbd.press("c")
            kbd.release("c")
        time.sleep(0.18)
    except Exception:
        pass
    new = read_clipboard() or old
    if preserve and new != old:
        time.sleep(0.03)
        write_clipboard(old)
    return new
