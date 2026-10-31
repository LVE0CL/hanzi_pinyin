# -*- coding: utf-8 -*-
"""US12 手写模块的「声明 + 自检」。

手写板本身是个独立窗口（`hpp/ui/handwriting.py`），没有内嵌面板，所以这里
`panel()` 保持默认的 None——它作为 Feature 存在的意义是：开关状态、自检项、
以及后续把手写识别结果回填到输入框的挂点。
"""
from __future__ import annotations

import os

from ..paths import handwriting_status
from .base import Feature

# 系统手写面板（Windows Ink）常见路径
TABTIP_PATHS = (
    r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe",
    r"C:\Program Files (x86)\Common Files\microsoft shared\ink\TabTip.exe",
)


class HandwritingFeature(Feature):
    key = "handwriting"
    label = "手写功能"

    def self_check(self) -> list:
        engine = self.app.cfg.get("handwriting_engine", "system") if self.app else "system"
        status = handwriting_status(engine)
        found = next((p for p in TABTIP_PATHS if os.path.exists(p)), "")
        return [
            ("引擎状态文案", bool(status), status),
            # 找不到 TabTip 不算失败：程序会回退到 Win+Ctrl+O 唤起系统触摸键盘
            ("系统手写面板", True,
             found or "未找到 TabTip.exe，将回退到 Win+Ctrl+O"),
        ]


FEATURE = HandwritingFeature
