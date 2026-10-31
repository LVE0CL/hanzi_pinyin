# -*- coding: utf-8 -*-
"""功能模块包（S4）。

每个模块一个文件 `hpp/features/<key>.py`，文件里声明 `FEATURE = 类`。
注册表按 `hpp/modules.py` 的顺序加载，没写文件的模块静默跳过。

依赖方向：`features/**` 只允许 import `hpp` 的下三层（constants / pinyin /
theme / config / icons / paths），**不许 import `hpp.ui` 与外壳**——需要界面就
用 `panel(parent)` 拿父容器自己搭，需要主窗口状态就走 `self.app`。
"""

from .base import Feature
from .registry import (
    annotate_all,
    attach_all,
    build_panels,
    collect_self_checks,
    load_features,
    merge_settings,
    notify_text,
)

__all__ = [
    "Feature",
    "annotate_all",
    "attach_all",
    "build_panels",
    "collect_self_checks",
    "load_features",
    "merge_settings",
    "notify_text",
]
