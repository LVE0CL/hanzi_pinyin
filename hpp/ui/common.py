# -*- coding: utf-8 -*-
"""几个 UI 模块共用的小东西。"""

from __future__ import annotations


def _release_grab(widget) -> None:
    """释放 pointer grab。

    注意：`widget.grab_release()` 只在 widget 就是 grab 窗口时才有效，
    所以必须问一次 grab_current()，否则旧 grab 会一直挂在那儿劫持后续鼠标事件。
    """
    try:
        current = widget.grab_current()
        if current is not None:
            current.grab_release()
    except Exception:
        pass

# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------
PLACEHOLDER = "在这里写字，或者选中一段文字后双击"
