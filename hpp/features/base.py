# -*- coding: utf-8 -*-
"""功能模块的接口契约（S4）。

15 个可选模块以前只有开关没有实现。从 S4 起，一个模块 = `hpp/features/<key>.py`
里的一个 `Feature` 子类，模块级变量名固定为 `FEATURE`：

    # hpp/features/tone_contour.py
    from .base import Feature

    class ToneContour(Feature):
        key = "tone_contour"

        def panel(self, parent):
            ...

    FEATURE = ToneContour

为什么是「模块里放一个类」而不是「在注册表里登记」：三个人并行开发时，注册表
由一个人维护、其他人只加自己的文件，就不会出现两个人在同一个列表里插条目的冲突。
没写文件的模块 `find_spec` 直接找不到，静默跳过——开关勾着也不算错。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    # 功能模块通过 attach() 拿到的就是主窗口，运行时不去 import 外壳（会成环）
    from hanzi_pinyin import HanziPopup


class Feature:
    """所有功能模块的基类。

    生命周期：
        1. 注册表按 MODULES 顺序 import 模块 → 实例化 → `attach(app)`
        2. 主窗口构建界面时调 `panel(parent)`，返回的控件会被 pack 到正文下方；
           返回 None 表示这个模块没有内嵌面板（比如手写是独立窗口）
        3. 每次输入变化：先 `annotate(items)` 给每个字补充展示信息，
           渲染完再 `on_text(text, items)` 通知面板刷新
        4. `settings_spec()` 返回的设置项会被合并进「功能模块」页
        5. `self_check()` 返回的自检项会被 `--selftest` 收走

    红线：这里的方法都会被主窗口直接调用，**任何一个模块抛异常都不能影响其他模块
    和主界面**，所以注册表在所有调用点都套了 try/except。自己写模块时也别在这里
    做耗时操作（会卡 UI 线程）。
    """

    key: str = ""
    label: str = ""

    def __init__(self) -> None:
        self.app: "HanziPopup | None" = None

    # ---------------- 生命周期 ----------------
    def attach(self, app: "HanziPopup") -> None:
        """拿到主窗口引用。此时 `app.cfg` / `app.colors` / `app.font_*` 已就绪。"""
        self.app = app

    # ---------------- 界面 ----------------
    def panel(self, parent):
        """返回一个塞进主窗口正文下方的控件；没有内嵌面板就返回 None。"""
        return None

    # ---------------- 数据 ----------------
    def annotate(self, items: list) -> list:
        """给每个字补充展示信息（如声调数字），返回 items 本身即可。

        items 是 `pinyin.analyze()` 的结果，每项形如
        `{"char": "汉", "readings": ["hàn"], ...}`。
        """
        return items

    def on_text(self, text: str, items: list) -> None:
        """输入变化后的回调，用来刷新自己的面板。"""

    # ---------------- 设置与自检 ----------------
    def settings_spec(self) -> list:
        """返回设置项列表，元素格式同 `hpp/settings_spec.py` 里的 items。

        支持额外字段 `default`（该键不在 DEFAULT_CONFIG 里时用它兜底）。
        """
        return []

    def self_check(self) -> list:
        """返回 `(名称, 是否通过, 细节)` 三元组列表，会被 `--selftest` 收集。"""
        return []
