"""可选功能模块注册表（US11 框架）。

加一个模块 = 在这里加一条；未启用的模块不加载依赖、不显示入口。
本文件由项目经理统一维护，功能开发者不要直接改。
"""
from __future__ import annotations

# 第 2 批可选功能模块（US11）：开关框架本期就位，内部功能后续迭代逐个落地
# --------------------------------------------------------------------------
MODULES = [
    {"key": "stroke_animation", "label": "笔画顺序动画",
     "hint": "按笔顺逐笔回放单字写法"},
    {"key": "stroke_practice_sheet", "label": "字帖生成",
     "hint": "导出米字格字帖 PDF / 图片"},
    {"key": "srs_review", "label": "生词本 + SRS 复习",
     "hint": "按间隔重复算法安排复习"},
    {"key": "spelling_quiz", "label": "拼写自测 / 听写",
     "hint": "听读音写拼音或写汉字"},
    {"key": "tone_contour", "label": "声调五度图",
     "hint": "画出调值曲线，直观看出高低升降"},
    {"key": "custom_pronunciation", "label": "自定义读音词库",
     "hint": "给多音字 / 人名地名词条指定读法"},
    {"key": "translate_on_select", "label": "划词翻译",
     "hint": "选中文字时附带常见义项"},
    {"key": "hsk_frequency", "label": "HSK 等级 + 字频",
     "hint": "标注 HSK 级别与使用频率"},
    {"key": "ruby_export", "label": "Ruby 注音导出",
     "hint": "导出带注音的 HTML / Word"},
    {"key": "pinyin_reverse_lookup", "label": "拼音反向查字",
     "hint": "输入 han4 反查候选汉字"},
    {"key": "bopomofo", "label": "注音符号（ㄅㄆㄇ）",
     "hint": "台湾惯用的注音显示方式"},
    {"key": "variant_chars", "label": "繁简 / 异体对照",
     "hint": "同时给出繁体与异体写法"},
    {"key": "learning_stats", "label": "学习统计面板",
     "hint": "查询次数、生词增长、复习完成度"},
    {"key": "cloud_sync", "label": "云同步生词本",
     "hint": "多设备同步（需自备存储）"},
    {"key": "handwriting", "label": "手写功能（US12）",
     "hint": "内置手写板 + 系统手写识别", "default": True},
]

MODULE_KEYS = [m["key"] for m in MODULES]


def default_modules() -> dict:
    return {m["key"]: bool(m.get("default", False)) for m in MODULES}
