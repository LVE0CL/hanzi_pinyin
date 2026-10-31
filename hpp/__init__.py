"""汉字拼音浮窗 · 内部包。

分层（依赖单向，下层不认识上层）：
    constants / modules / settings_spec   纯数据
    paths / pinyin / icons / theme        无 UI 的小工具
    config / speech / selection / clipboard / hotkeys
    ui/                                   界面组件（只认 app 传进来的对象）
外壳 hanzi_pinyin.py 负责装配：主窗口、单实例、selftest、main。
"""
from .constants import VERSION as __version__

__all__ = ["__version__"]
