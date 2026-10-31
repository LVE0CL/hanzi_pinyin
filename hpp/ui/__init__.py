# -*- coding: utf-8 -*-
"""界面组件：主窗口之外的各个独立窗口 / 视图。

S2 把原来堆在 hanzi_pinyin.py 里的 UI 类逐个搬到这里，外壳只剩装配与编排。

约定：所有组件的构造函数第一个参数都是 app（HanziPopup 实例），组件只通过
app 拿配置、配色、字体，**不反向 import 外壳**——外壳反过来 import 它们，
真去 import 会成环（类型标注用 TYPE_CHECKING 挡在运行时之外）。
"""

from .common import PLACEHOLDER, _release_grab
from .first_run import FirstRunWindow
from .handwriting import HandwritingPad
from .mini_popup import MiniPopup
from .ruby_view import RubyView
from .settings import SettingsWindow
from .widgets import BottomBar, ResizeZones, TitleBar

__all__ = [
    "PLACEHOLDER",
    "_release_grab",
    "BottomBar",
    "FirstRunWindow",
    "HandwritingPad",
    "MiniPopup",
    "ResizeZones",
    "RubyView",
    "SettingsWindow",
    "TitleBar",
]
