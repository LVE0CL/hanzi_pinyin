#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
汉字拼音浮窗 · Hanzi Pinyin Popup  v1.2.0
=========================================

一个常驻托盘的小浮窗：在任何地方写/打出汉字，立刻看到拼音（多音字全列）、
能朗读、能复制。

v1.0.x 迭代：
    · 系统托盘常驻（首页 / 设置 / 退出）
    · 双击 Ctrl 唤起首页（触发键与间隔可配置）
    · 自定义标题栏：× 退出、□ 最大化、− 隐藏到托盘，标题栏可拖动
    · 统一设置界面（通用 / 快捷键 / 功能模块 / 关于），配置带 schemaVersion

v1.1.0 迭代：
    · US5 无边框窗口 8 向拖动改大小（修复缺陷），尺寸记忆
    · US6 选中文字后双击弹出迷你浮窗（不打开主窗口）
    · US7 迷你浮窗贴光标定位、可拖动 / 固定 / 超时淡出
    · US8 朗读嗓音可选、点单字朗读、抓取选区不破坏剪贴板
    · US9 标调方式切换（符号 / 数字 / 无声调）、多音字点击切换

v1.2.0 迭代：
    · US10 设置图标统一为齿轮（首页自绘位图 + 托盘菜单齿轮字符）
    · US11 首次启动引导页 + 15 个可选模块的开关框架
    · US12 内置手写板（米字格画布）+ 系统手写识别接入
    · US13 5 套 VS Code 风主题（默认 Dark+）+ 可选背景色覆盖，切换即重绘
    · US14 置顶改为可选：标题栏「📌 | − | □ | ×」中的图钉切换
    · US15 快捷键重构：允许留空禁用、移除抓取热键、选中双击支持键盘功能键、
           与唤起键冲突时弹「是否互换」确认框
    · US17 迷你浮窗点击外部自动关闭（可配置，pin 后不生效）
    · FR1  过滤非中文/非标点字符（"Hello 你好 123！" → 只注音「你好！」）

许可证：MIT
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import platform
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser

# --------------------------------------------------------------------------
# 依赖检查
# --------------------------------------------------------------------------
try:
    from pypinyin import Style, pinyin as pinyin_of
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 pypinyin，请先执行：pip install -r requirements.txt")

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox
except ImportError:  # pragma: no cover
    sys.exit(
        "当前 Python 没有 tkinter，请安装带 tkinter 的官方 Python：\n"
        "  https://www.python.org/downloads/"
    )

try:
    import pyperclip  # 跨平台剪贴板
except ImportError:  # pragma: no cover
    pyperclip = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 Pillow，请先执行：pip install -r requirements.txt")

HANZI_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
APP_NAME = "HanziPinyinPopup"
APP_TITLE = "汉字拼音浮窗"
VERSION = "1.2.0"
CONFIG_SCHEMA = 4
SINGLE_INSTANCE_PORT = 47653
PROJECT_URL = "https://github.com/LVE0CL/hanzi_pinyin"

# --------------------------------------------------------------------------
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

# --------------------------------------------------------------------------
# 配置模型
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "schemaVersion": CONFIG_SCHEMA,
    # 通用
    "start_hidden": False,        # 启动时只驻留托盘
    "always_on_top": True,        # 窗口置顶（US14：可由标题栏图钉切换）
    "language": "zh-CN",          # 预留：界面语言
    "resize_enabled": True,       # 允许从边缘拖动改大小
    "resize_pad": 6,              # 边缘热区厚度(px)
    "min_width": 320,
    "min_height": 200,
    "theme": "dark_plus",         # US13：dark_plus/light_plus/dark_blue/light_blue/monokai
    "theme_background": None,     # US13：自定义背景色，null = 跟随配色
    # 快捷键（US15：空字符串 = 禁用）
    "trigger_key": "ctrl",        # 双击唤起的按键
    "double_click_ms": 400,       # 双击判定间隔
    "quit_hotkey": "<ctrl>+<alt>+q",
    "select_double_popup": True,  # 选中文字后双击弹迷你浮窗
    "select_double_mode": "mouse",     # mouse / key
    "select_double_button": "left",    # left / right / middle
    "select_double_modifier": "none",  # none / ctrl / alt / shift
    "select_double_key": "shift",      # 键盘模式下双击的按键，须 ≠ trigger_key
    "trigger_prefers_selection": False,  # 双击触发键时有选区则弹迷你窗而非首页
    # 功能模块
    "auto_clipboard": False,      # 剪贴板出现汉字时自动显示
    "font_size": 32,              # 汉字字号（点）
    "speech_rate": 0,             # 语速 -10 ~ 10
    "tts_voice": "auto",          # auto / female / male / 具体 VoiceId
    "read_char_on_click": True,   # 点单字朗读
    "preserve_clipboard": True,   # 抓取选区不破坏剪贴板
    "tone_style": "symbol",       # symbol / num / none
    "filter_non_han": True,       # FR1：过滤非中文/非标点字符
    "popup_dismiss_on_outside_click": True,   # US17：点浮窗外自动关闭
    "mini_popup_auto_hide_ms": 4000,   # 0 = 不自动消失
    "mini_popup_pinned": False,
    "handwriting_engine": "system",    # US12：system / offline
    "modules": default_modules(),      # US11：15 个可选模块开关
    "first_run": True,                 # US11：首次启动引导
    # 运行时状态（不算「设置」，但一起持久化）
    "window_width": 420,
    "window_height": 200,
    "position": None,
}

# 设置界面的声明式定义：加一个设置项 = 这里加一条 + DEFAULT_CONFIG 加默认值
# type: bool / int / choice
SETTING_GROUPS = [
    {
        "key": "general",
        "title": "通用",
        "items": [
            {
                "key": "start_hidden",
                "label": "启动时直接驻留托盘",
                "type": "bool",
                "hint": "勾选后，启动程序不会自动弹出首页",
            },
            {
                "key": "always_on_top",
                "label": "窗口置顶",
                "type": "bool",
                "hint": "浮窗始终显示在其他窗口之上（也可点标题栏左侧图钉快速切换）",
            },
            {
                "key": "theme",
                "label": "主题",
                "type": "choice",
                "choices": [
                    ("Dark+", "dark_plus"),
                    ("Light+", "light_plus"),
                    ("Dark Blue", "dark_blue"),
                    ("Light Blue", "light_blue"),
                    ("Monokai", "monokai"),
                ],
                "hint": "VS Code 风配色，保存后立即重绘，不需要重启",
            },
            {
                "key": "theme_background",
                "label": "背景色",
                "type": "color",
                "hint": "可选，留空则跟随主题；只改主背景，其余颜色按明暗自适应",
            },
            {
                "key": "language",
                "label": "界面语言",
                "type": "choice",
                "choices": [("简体中文", "zh-CN")],
                "readonly": True,
                "hint": "多语言为后续版本预留",
            },
            {
                "key": "resize_enabled",
                "label": "拖动改变窗口大小",
                "type": "bool",
                "hint": "关闭后只能通过下方的最小尺寸与字号间接控制窗口大小",
            },
            {
                "key": "min_width",
                "label": "窗口最小宽度",
                "type": "int",
                "min": 320,
                "max": 1200,
                "step": 20,
                "suffix": "px",
                "hint": "拖动缩放时可缩到的最小宽度",
            },
            {
                "key": "min_height",
                "label": "窗口最小高度",
                "type": "int",
                "min": 160,
                "max": 900,
                "step": 20,
                "suffix": "px",
                "hint": "拖动缩放时可缩到的最小高度",
            },
        ],
    },
    {
        "key": "shortcut",
        "title": "快捷键",
        "items": [
            {
                "key": "trigger_key",
                "label": "双击唤起的按键",
                "type": "choice",
                "choices": [
                    ("Ctrl", "ctrl"),
                    ("Alt", "alt"),
                    ("Shift", "shift"),
                    ("空格", "space"),
                    ("Tab", "tab"),
                    ("F1", "f1"),
                    ("F2", "f2"),
                    ("F3", "f3"),
                    ("不使用（禁用）", ""),
                ],
                "hint": "连续按两下该键即可唤起首页；选「不使用」则不注册全局监听",
            },
            {
                "key": "double_click_ms",
                "label": "双击判定间隔",
                "type": "int",
                "min": 150,
                "max": 1000,
                "step": 50,
                "suffix": "ms",
                "hint": "两次按键间隔小于该值才算双击，400 ms 为跨平台折中值",
            },
            {
                "key": "select_double_popup",
                "label": "选中双击弹浮窗",
                "type": "bool",
                "hint": "选中文字后双击，在光标旁弹出迷你浮窗（需 uiautomation 才能读到选区）",
            },
            {
                "key": "select_double_mode",
                "label": "选中双击模式",
                "type": "choice",
                "choices": [("鼠标", "mouse"), ("键盘", "key")],
                "hint": "键盘模式适合触控板 / 只想敲键的场景：连续按两下下方功能键",
            },
            {
                "key": "select_double_key",
                "label": "选中双击的键盘功能键",
                "type": "choice",
                "choices": [
                    ("Shift", "shift"),
                    ("Ctrl", "ctrl"),
                    ("Alt", "alt"),
                    ("空格", "space"),
                    ("Tab", "tab"),
                    ("F4", "f4"),
                    ("F5", "f5"),
                    ("不使用（禁用）", ""),
                ],
                "hint": "必须与「双击唤起键」不同；若相同，保存时会询问是否互换",
            },
            {
                "key": "select_double_button",
                "label": "选中双击的按钮",
                "type": "choice",
                "choices": [("鼠标左键", "left"), ("鼠标右键", "right"), ("鼠标中键", "middle")],
                "hint": "只在检测到文本选区时触发，空白处双击不受影响",
            },
            {
                "key": "select_double_modifier",
                "label": "选中双击的修饰键",
                "type": "choice",
                "choices": [("不需要", "none"), ("按住 Ctrl", "ctrl"), ("按住 Alt", "alt"), ("按住 Shift", "shift")],
                "hint": "若与其它软件的双击手势冲突，可加一个修饰键区分",
            },
            {
                "key": "quit_hotkey",
                "label": "退出热键",
                "type": "choice",
                "choices": [
                    ("Ctrl + Alt + Q", "<ctrl>+<alt>+q"),
                    ("Ctrl + Shift + Q", "<ctrl>+<shift>+q"),
                    ("Alt + Shift + Q", "<alt>+<shift>+q"),
                    ("不使用（禁用）", ""),
                ],
                "hint": "任何时候按下都能退出程序；选「不使用」则只能用托盘的退出",
            },
            {
                "key": "trigger_prefers_selection",
                "label": "优先查询选区",
                "type": "bool",
                "hint": "开启后，双击触发键时若当前有选中的文字，直接弹迷你浮窗而不是首页",
            },
        ],
    },
    {
        "key": "module",
        "title": "功能模块",
        "items": [
            {
                "key": "auto_clipboard",
                "label": "剪贴板自动识别",
                "type": "bool",
                "hint": "复制到剪贴板的中文会自动弹出拼音",
            },
            {
                "key": "font_size",
                "label": "汉字字号",
                "type": "int",
                "min": 18,
                "max": 72,
                "step": 2,
                "suffix": "pt",
                "hint": "调整后窗口会自动适配大小",
            },
            {
                "key": "speech_rate",
                "label": "朗读语速",
                "type": "int",
                "min": -10,
                "max": 10,
                "step": 1,
                "hint": "0 为系统默认语速，负数更慢",
            },
            {
                "key": "tts_voice",
                "label": "朗读嗓音",
                "type": "choice",
                "choices": [("跟随系统", "auto"), ("女声优先", "female"), ("男声优先", "male")],
                "choices_from": "voices",
                "hint": "列表来自系统已安装的 SAPI 嗓音；没有男声时可在「设置 → 语音」里添加语音包",
            },
            {
                "key": "read_char_on_click",
                "label": "点单字朗读",
                "type": "bool",
                "hint": "点击拼音行里的某一个字，只朗读这个字（多音字会顺便切到下一个读音）",
            },
            {
                "key": "preserve_clipboard",
                "label": "抓取选区不破坏剪贴板",
                "type": "bool",
                "hint": "抓取前备份剪贴板，读完后还原，你原来复制的内容不会丢",
            },
            {
                "key": "tone_style",
                "label": "标调方式",
                "type": "choice",
                "choices": [("符号调 hàn", "symbol"), ("数字调 han4", "num"), ("无声调 han", "none")],
                "hint": "切换后立即按新方式重新显示",
            },
            {
                "key": "mini_popup_auto_hide_ms",
                "label": "浮窗自动淡出",
                "type": "int",
                "min": 0,
                "max": 30000,
                "step": 500,
                "suffix": "ms",
                "hint": "迷你浮窗停留多久后淡出，0 表示一直留着（也可以在浮窗上点「固定」）",
            },
            {
                "key": "mini_popup_pinned",
                "label": "浮窗默认固定",
                "type": "bool",
                "hint": "勾选后迷你浮窗默认固定，不会自动淡出",
            },
            {
                "key": "filter_non_han",
                "label": "过滤非中文/非标点",
                "type": "bool",
                "hint": "只把中文与标点送进注音，英文、数字、符号、emoji 一律过滤（推荐开启）",
            },
            {
                "key": "popup_dismiss_on_outside_click",
                "label": "点浮窗外自动关闭",
                "type": "bool",
                "hint": "在迷你浮窗以外的地方点一下鼠标就收起（已固定的浮窗不受影响）",
            },
            {
                "key": "handwriting_engine",
                "label": "手写识别引擎",
                "type": "choice",
                "choices": [("系统手写（微软同款）", "system"), ("离线模型（ONNX）", "offline")],
                "hint": "系统引擎调用 Windows 自带手写识别；离线模型需自行放置 models/handwriting.onnx",
            },
        ],
    },
]

TRIGGER_LABELS = {
    value: label
    for group in SETTING_GROUPS
    for item in group["items"]
    if item["key"] == "trigger_key"
    for label, value in item["choices"]
}

# 标调方式 → pypinyin style。内部一律用 TONE 计算（词典过滤依赖带调字符串），
# 显示前再转成用户选的方式。
TONE_STYLES = [
    ("符号调 hàn", "symbol"),
    ("数字调 han4", "num"),
    ("无声调 han", "none"),
]


def convert_reading(reading: str, style: str) -> str:
    """把带调拼音（hàn）转成数字调（han4）或无声调（han）。"""
    if not reading or style == "symbol":
        return reading
    try:
        from pypinyin.contrib.tone_convert import to_normal, to_tone3
    except Exception:
        return reading
    try:
        return to_tone3(reading) if style == "num" else to_normal(reading)
    except Exception:
        return reading

# --------------------------------------------------------------------------
# US13：主题配色表（集中在这一处，切换即重绘，界面里不硬编码颜色）
# 每套都给齐同样的 key，改配色只改这里。accent_fg = 强调色上的文字色。
# --------------------------------------------------------------------------
THEME_COLOR_KEYS = ("panel", "panel_alt", "border", "fg", "fg_dim", "accent",
                    "accent_fg", "hover", "entry_bg", "danger", "scroll")

THEMES = {
    "dark_plus": {          # VS Code Dark+
        "panel": "#1e1e1e", "panel_alt": "#252526", "border": "#3c3c3c",
        "fg": "#d4d4d4", "fg_dim": "#8f8f8f", "accent": "#4ec9b0",
        "accent_fg": "#0f1f1b", "hover": "#2a2d2e", "entry_bg": "#181818",
        "danger": "#f48771", "scroll": "#4a4a4a", "dark": True,
    },
    "light_plus": {         # VS Code Light+
        "panel": "#ffffff", "panel_alt": "#f3f3f3", "border": "#e0e0e0",
        "fg": "#1f1f1f", "fg_dim": "#6f6f6f", "accent": "#007acc",
        "accent_fg": "#ffffff", "hover": "#e8e8e8", "entry_bg": "#fbfbfb",
        "danger": "#cd3131", "scroll": "#c8c8c8", "dark": False,
    },
    "dark_blue": {          # Visual Studio Dark Blue
        "panel": "#12212f", "panel_alt": "#1a2c3d", "border": "#2a4256",
        "fg": "#dbe7f3", "fg_dim": "#7f97ad", "accent": "#4fa3d1",
        "accent_fg": "#07131d", "hover": "#1e3548", "entry_bg": "#0d1926",
        "danger": "#e26d6d", "scroll": "#3a5568", "dark": True,
    },
    "light_blue": {         # Visual Studio Light Blue
        "panel": "#f5f9ff", "panel_alt": "#e8f1fb", "border": "#cfe0f0",
        "fg": "#1b2b3a", "fg_dim": "#6b8299", "accent": "#1f7ac0",
        "accent_fg": "#ffffff", "hover": "#dceaf8", "entry_bg": "#ffffff",
        "danger": "#c0392b", "scroll": "#c3d6e8", "dark": False,
    },
    "monokai": {            # Monokai
        "panel": "#272822", "panel_alt": "#2f3029", "border": "#49483e",
        "fg": "#f8f8f2", "fg_dim": "#a6a68a", "accent": "#a6e22e",
        "accent_fg": "#1a1f12", "hover": "#3a3b32", "entry_bg": "#1f201b",
        "danger": "#f92672", "scroll": "#575744", "dark": True,
    },
}

# 老配置里的 dark / light 直接映射到对应的新预设
THEME_ALIASES = {"dark": "dark_plus", "light": "light_plus"}


def _hex_to_rgb(value: str):
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    """按 ratio 把 a 混向 b（0 = 全 a，1 = 全 b）。"""
    ra, rb = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    if ra is None or rb is None:
        return color_a
    ratio = max(0.0, min(1.0, ratio))
    return _rgb_to_hex(tuple(a + (b - a) * ratio for a, b in zip(ra, rb)))


def normalize_theme(name: str) -> str:
    name = THEME_ALIASES.get(name or "", name or "")
    return name if name in THEMES else "dark_plus"


def theme_colors(name: str, background=None) -> dict:
    """取一套配色；给了 background 就只覆盖主背景，其余颜色按明暗自适应。"""
    base = dict(THEMES[normalize_theme(name)])
    rgb = _hex_to_rgb(background) if isinstance(background, str) else None
    if rgb is not None:
        lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
        dark = lum < 0.5
        base["panel"] = _rgb_to_hex(rgb)
        base["panel_alt"] = _mix(base["panel"], "#ffffff" if dark else "#000000",
                                 0.08 if dark else 0.05)
        base["hover"] = _mix(base["panel"], "#ffffff" if dark else "#000000",
                             0.16 if dark else 0.09)
        base["entry_bg"] = _mix(base["panel"], "#000000" if dark else "#ffffff",
                                0.22 if dark else 0.45)
        base["border"] = _mix(base["panel"], "#ffffff" if dark else "#000000",
                              0.26 if dark else 0.14)
        base["dark"] = dark
        if dark:
            base["fg"] = "#e8e8e8"
            base["fg_dim"] = "#9a9a9a"
        else:
            base["fg"] = "#1f2328"
            base["fg_dim"] = "#6f6f6f"
    return base



# --------------------------------------------------------------------------
# 配置文件：读取 / 迁移 / 原子写入
# --------------------------------------------------------------------------
def config_path() -> str:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif platform.system() == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, APP_NAME, "config.json")


def migrate(cfg: dict) -> dict:
    """把旧版本配置升级到当前 schema。新增字段一律走这里补齐。"""
    version = int(cfg.get("schemaVersion", 1) or 1)
    # US15：「抓取选中文字」热键已被「选中双击弹浮窗」取代，旧字段一律清掉
    cfg.pop("hotkey", None)
    if version < 2:
        # v1 → v2：新增托盘 / 双击唤起相关字段，旧字段名保持不变
        cfg.setdefault("start_hidden", DEFAULT_CONFIG["start_hidden"])
        cfg.setdefault("trigger_key", DEFAULT_CONFIG["trigger_key"])
        cfg.setdefault("double_click_ms", DEFAULT_CONFIG["double_click_ms"])
        version = 2
    if version < 3:
        # v2 → v3：窗口缩放、选中双击、迷你浮窗、朗读嗓音、标调方式
        for key in (
            "resize_enabled", "resize_pad", "min_width", "min_height",
            "select_double_popup", "select_double_button", "select_double_modifier",
            "tts_voice", "read_char_on_click", "preserve_clipboard", "tone_style",
            "mini_popup_auto_hide_ms", "mini_popup_pinned", "window_height",
        ):
            cfg.setdefault(key, DEFAULT_CONFIG[key])
        # 老配置只记了宽度，高度给个和内容相称的初值
        if not isinstance(cfg.get("window_height"), int):
            cfg["window_height"] = DEFAULT_CONFIG["window_height"]
        version = 3
    if version < 4:
        # v3 → v4：主题 5 套 + 背景覆盖、快捷键空值/键盘模式、模块开关、首启引导、
        #           手写引擎、非汉字过滤、点浮窗外关闭
        for key in (
            "theme_background", "select_double_mode", "select_double_key",
            "filter_non_han", "popup_dismiss_on_outside_click",
            "handwriting_engine", "first_run",
        ):
            cfg.setdefault(key, DEFAULT_CONFIG[key])
        version = 4
    # 主题名（dark/light → dark_plus/light_plus）与模块表每轮都对齐一次，幂等
    cfg["theme"] = normalize_theme(cfg.get("theme"))
    modules = default_modules()
    stored = cfg.get("modules")
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in modules:
                modules[key] = bool(value)
    cfg["modules"] = modules
    cfg["schemaVersion"] = version
    return cfg


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as exc:
            print(f"[warn] 读取配置失败，使用默认配置：{exc}", file=sys.stderr)
    cfg = migrate(cfg)
    for key, value in DEFAULT_CONFIG.items():
        cfg.setdefault(key, value)
    return cfg


def save_config(cfg: dict) -> None:
    """原子写入，避免写一半断电导致配置损坏。"""
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[warn] 保存配置失败：{exc}", file=sys.stderr)


# --------------------------------------------------------------------------
# 图标（运行时绘制，不依赖外部资源文件）
# --------------------------------------------------------------------------
def _cjk_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def make_app_image(size: int = 64):
    """应用图标：圆角方块 + 「拼」字。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.24), fill=(42, 122, 90, 255))
    font = _cjk_font(int(s * 0.62))
    if font is not None:
        try:
            box = d.textbbox((0, 0), "拼", font=font)
            w, h = box[2] - box[0], box[3] - box[1]
            d.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]), "拼",
                   font=font, fill=(255, 255, 255, 255))
        except Exception:
            pass
    return img.resize((size, size), Image.LANCZOS)


def make_gear_image(size: int = 18, color: str = "#8b939e"):
    """齿轮图标：圆环 + 8 个齿，运行时绘制。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = s / 2
    ring_r = s * 0.27
    inner_r = s * 0.31
    outer_r = s * 0.45
    width = max(2, int(s * 0.11))
    for i in range(8):
        ang = i * math.pi / 4 + math.pi / 8
        d.line(
            [cx + inner_r * math.cos(ang), cy + inner_r * math.sin(ang),
             cx + outer_r * math.cos(ang), cy + outer_r * math.sin(ang)],
            fill=color, width=width,
        )
    d.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
              outline=color, width=width)
    return img.resize((size, size), Image.LANCZOS)


def make_pin_image(size: int = 16, color: str = "#8f8f8f", filled: bool = False):
    """US14：图钉图标。filled=True 表示「已钉住」（实心高亮），否则描边。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    width = max(2, int(s * 0.10))
    head = [s * 0.28, s * 0.12, s * 0.72, s * 0.44]        # 钉帽（椭圆）
    body = [(s * 0.32, s * 0.40), (s * 0.68, s * 0.40), (s * 0.60, s * 0.60),
            (s * 0.40, s * 0.60)]
    if filled:
        d.ellipse(head, fill=color)
        d.polygon(body, fill=color)
        d.line([s * 0.5, s * 0.58, s * 0.5, s * 0.90], fill=color, width=width)
    else:
        d.ellipse(head, outline=color, width=width)
        d.line(body + [body[0]], fill=color, width=width, joint="curve")
        d.line([s * 0.5, s * 0.58, s * 0.5, s * 0.90], fill=color, width=width)
    return img.resize((size, size), Image.LANCZOS)


def make_caret_image(size: int = 9, color: str = "#8b939e"):
    """下拉箭头：向下的小三角。Tk 自带箭头在深色主题下会变成空白方块，故自绘。"""
    scale = 4
    w, h = size * scale, int(size * scale * 0.62)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 0), (w - 1, 0), (w / 2, h - 1)], fill=color)
    return img.resize((size, max(4, int(size * 0.62))), Image.LANCZOS)


# --------------------------------------------------------------------------
# 拼音分析
# --------------------------------------------------------------------------
_COMMON_PAIRS = None


def common_pairs() -> set:
    """pypinyin 的 heteronym 会列出很多生僻又音（"之" → zhī/zhū/zhì）。

    用它的词组词典反查一遍，只保留现代汉语里真实用到的读音。
    """
    global _COMMON_PAIRS
    if _COMMON_PAIRS is None:
        pairs = set()
        try:
            from pypinyin.phrases_dict import phrases_dict

            for word, readings in phrases_dict.items():
                if len(word) != len(readings):
                    continue
                for ch, rs in zip(word, readings):
                    for r in rs:
                        pairs.add((ch, r))
        except Exception:
            pass
        _COMMON_PAIRS = pairs
    return _COMMON_PAIRS


# FR1：只放行「中文 + 标点」，其余字符（英文、数字、符号、emoji、空白）过滤掉
ALLOWED_PUNCT = set(
    "，。！？；：、（）《》〈〉「」『』【】〔〕—－…～·"
    ",.!?;:()[]{}<>'\"-+*/=%&@#|^`$"
)


def filter_text(text: str, enabled: bool = True) -> str:
    """FR1 缺陷修复：把非中文/非标点的字符滤掉。

    "Hello 你好 123！" → "你好！"：标点原样保留、不参与注音，英文数字不报错不串行。
    enabled=False 时原样返回（此时英文数字仍只是展示，不注音）。
    """
    if not enabled or not text:
        return text
    return "".join(
        ch for ch in text if HANZI_RE.match(ch) or ch in ALLOWED_PUNCT
    ).strip()


def analyze(text: str, tone_style: str = "symbol", filter_non_han: bool = True) -> list:
    """把一段文字拆成 [{char, readings}]，非汉字（连续的一段）合并为一项。

    readings[0] 是**结合上下文**得到的主读音（"重庆"的"重"读 chóng），
    后面跟的是该字的其他常见读音（多音字）。
    tone_style 只影响输出的写法（hàn / han4 / han），消歧与过滤始终按带调进行。
    filter_non_han=True 时先做 FR1 过滤，英文/数字/emoji 不参与注音也不显示。
    """
    text = filter_text(text, filter_non_han)
    chars = [ch for ch in text if ch not in "\r\n\t"]
    if not chars:
        return []

    # 整句一起送进去，pypinyin 才会用词组词典消歧
    try:
        contextual = pinyin_of("".join(chars), style=Style.TONE, heteronym=False)
    except Exception:
        contextual = []

    items = []
    buffer = ""  # 连续的非汉字
    for idx, ch in enumerate(chars):
        if not HANZI_RE.match(ch):
            buffer += ch
            continue
        if buffer:
            items.append({"char": buffer, "readings": []})
            buffer = ""

        try:
            readings = pinyin_of(ch, style=Style.TONE, heteronym=True)[0]
        except Exception:
            readings = []
        uniq = []
        for r in readings:
            if r and r != ch and r not in uniq:
                uniq.append(r)

        # 只留下词组词典里出现过的读音，过滤掉生僻又音
        pairs = common_pairs()
        if pairs and uniq:
            kept = [r for r in uniq if (ch, r) in pairs]
            uniq = kept or uniq[:1]

        primary = ""
        if idx < len(contextual) and contextual[idx]:
            cand = contextual[idx][0]
            if cand and cand != ch:
                primary = cand
        if not primary and uniq:
            primary = uniq[0]
        if primary:
            uniq = [primary] + [r for r in uniq if r != primary]
        if tone_style != "symbol" and uniq:
            uniq = [convert_reading(r, tone_style) for r in uniq]

        items.append({"char": ch, "readings": uniq[:3]})

    if buffer:
        items.append({"char": buffer, "readings": []})
    return items


def pinyin_plain(items: list) -> str:
    out = []
    for it in items:
        out.append(it["readings"][0] if it["readings"] else it["char"])
    return " ".join(x for x in out if x.strip())


def pinyin_pairs(items: list) -> str:
    lines = []
    for it in items:
        if it["readings"]:
            lines.append(f"{it['char']}\t{it['readings'][0]}")
        elif it["char"].strip():
            lines.append(it["char"].strip())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 朗读
# --------------------------------------------------------------------------
_VOICE_CACHE = None
_VOICE_LOCK = threading.Lock()


def list_sapi_voices() -> list:
    """列出系统已安装的 SAPI 嗓音：[(名称, 性别, 语言)]。

    只在 Windows 有效，首次调用约 0.5~1 s，之后走缓存。失败一律返回空列表。
    """
    global _VOICE_CACHE
    with _VOICE_LOCK:
        if _VOICE_CACHE is not None:
            return _VOICE_CACHE
        voices = []
        if platform.system() == "Windows":
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.GetInstalledVoices() | ForEach-Object { "
                "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Gender + '|' + $_.VoiceInfo.Culture.Name }"
            )
            for shell in ("powershell", "pwsh"):
                try:
                    out = subprocess.run(
                        [shell, "-NoProfile", "-NoLogo", "-Command", script],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=30,
                        creationflags=0x08000000,
                    )
                    if out.returncode == 0 and out.stdout.strip():
                        for line in out.stdout.strip().splitlines():
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 3 and parts[0]:
                                voices.append((parts[0], parts[1], parts[2]))
                        break
                except Exception:
                    continue
        _VOICE_CACHE = voices
        return voices


def resolve_voice(pref: str) -> str:
    """把设置里的嗓音偏好解析成具体 VoiceId；空字符串表示交给系统默认。"""
    pref = (pref or "auto").strip()
    if not pref or pref == "auto":
        return ""
    voices = list_sapi_voices()
    if not voices:
        return ""
    if pref in ("female", "male"):
        want = pref
        cands = [v for v in voices if (v[1] or "").lower() == want]
        # 中文嗓音优先，否则随便挑一个
        zh = [v for v in cands if "zh" in (v[2] or "").lower()]
        pick = zh or cands
        return pick[0][0] if pick else ""
    names = [v[0] for v in voices]
    return pref if pref in names else ""


class Speech:
    """优先用 Windows 自带的 System.Speech（常驻进程，延迟低）；其他平台走系统命令。"""

    def __init__(self, rate: int = 0, voice: str = "auto"):
        self.rate = max(-10, min(10, int(rate)))
        self.voice = voice or "auto"
        self.system = platform.system()
        self._proc = None
        self._lock = threading.Lock()
        self._shell = None

    def set_rate(self, rate: int) -> None:
        rate = max(-10, min(10, int(rate)))
        if rate != self.rate:
            self.rate = rate
            self.close()  # 下次说话时按新语速重建

    def set_voice(self, voice: str) -> None:
        voice = voice or "auto"
        if voice != self.voice:
            self.voice = voice
            self.close()  # 下次说话时按新嗓音重建

    def _shell_candidates(self):
        return [self._shell] if self._shell else ["powershell", "pwsh"]

    def _ensure_windows(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        picked = resolve_voice(self.voice)
        select = ""
        if picked:
            safe = picked.replace("'", "''")
            select = f"try {{ $s.SelectVoice('{safe}') }} catch {{}};"
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate = {self.rate};"
            + select +
            "while ($true) {"
            "  $l = [Console]::In.ReadLine();"
            "  if ($null -eq $l) { break }"
            "  if ($l -eq '##quit##') { break }"
            "  if ($l.Trim().Length -eq 0) { continue }"
            "  $t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($l));"
            "  if ($t.Trim().Length -gt 0) { $s.Speak($t) }"
            "}"
        )
        flags = 0x08000000 if self.system == "Windows" else 0
        for shell in self._shell_candidates():
            try:
                self._proc = subprocess.Popen(
                    [shell, "-NoProfile", "-NoLogo", "-Command", script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="ascii",
                    errors="ignore",
                    creationflags=flags,
                )
                self._shell = shell
                return True
            except Exception:
                self._proc = None
        print("[warn] 找不到可用的 PowerShell，朗读不可用", file=sys.stderr)
        return False

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text: str) -> None:
        with self._lock:
            if self.system == "Windows":
                if self._ensure_windows() and self._proc and self._proc.stdin:
                    try:
                        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
                        self._proc.stdin.write(payload + "\n")
                        self._proc.stdin.flush()
                        return
                    except Exception:
                        self._proc = None
                try:
                    picked = resolve_voice(self.voice)
                    select = ""
                    if picked:
                        select = f"try {{ $s.SelectVoice('{picked.replace(chr(39), chr(39) * 2)}') }} catch {{}};"
                    ps = (
                        "Add-Type -AssemblyName System.Speech;"
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                        f"$s.Rate = {self.rate};"
                        + select +
                        "$s.Speak([Text.Encoding]::UTF8.GetString("
                        f"[Convert]::FromBase64String('{base64.b64encode(text.encode()).decode()}')))"
                    )
                    subprocess.run(
                        [self._shell or "powershell", "-NoProfile", "-Command", ps],
                        creationflags=0x08000000,
                        timeout=30,
                    )
                    return
                except Exception:
                    pass
            elif self.system == "Darwin":
                try:
                    cmd = ["say"]
                    picked = resolve_voice(self.voice)
                    if picked:
                        cmd += ["-v", picked]
                    subprocess.run(cmd + [text], timeout=30)
                    return
                except Exception:
                    pass
            else:
                for cmd in ("spd-say", "espeak-ng", "espeak"):
                    try:
                        subprocess.run([cmd, text], timeout=30)
                        return
                    except Exception:
                        continue

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write("##quit##\n")
                    proc.stdin.flush()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


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


# --------------------------------------------------------------------------
# 选区读取（US6 / US8）
# --------------------------------------------------------------------------
_UIA_THREADS = set()

MODIFIER_KEYS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
_MODIFIER_STATE = set()   # 非 Windows 平台由键盘监听维护
_MODIFIER_LOCK = threading.Lock()


def _init_uia_in_thread():
    """uiautomation 要求每个使用它的线程各自初始化 COM，否则会静默失败。"""
    tid = threading.get_ident()
    if tid in _UIA_THREADS:
        return True
    if platform.system() != "Windows":
        return False
    try:
        import uiautomation as auto
    except Exception:
        return False
    for name in ("InitializeUIAutomationInCurrentThread", "UIAutomationInitializerInThread"):
        fn = getattr(auto, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            break
    _UIA_THREADS.add(tid)
    return True


def read_selection_uia() -> str:
    """用 UI Automation 直接读焦点控件的文本选区——**完全不碰剪贴板**。

    读不到（控件不支持 TextPattern、没焦点、非 Windows）就返回空串，
    调用方据此判断「没有选区」，从而不去打扰用户。
    """
    if not _init_uia_in_thread():
        return ""
    try:
        import uiautomation as auto

        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return ""
        try:
            pattern = ctrl.GetTextPattern()
        except Exception:
            return ""
        if pattern is None:
            return ""
        try:
            ranges = pattern.GetSelection()
        except Exception:
            return ""
        parts = []
        for r in ranges or []:
            try:
                txt = r.GetText(-1)
            except Exception:
                txt = ""
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip()
    except Exception:
        return ""


# 只有这些控件里的 Ctrl+C 才是「复制文字」，其它（列表、按钮、桌面）按下去可能是复制文件
TEXT_CONTROL_TYPES = {"EditControl", "DocumentControl", "TextControl"}


def control_type_at(x: int, y: int) -> str:
    """光标落点处的 UIA 控件类型名，用来判断「这里能不能安全地按 Ctrl+C」。"""
    if not _init_uia_in_thread():
        return ""
    try:
        import uiautomation as auto

        ctrl = auto.ControlFromPoint(int(x), int(y))
        return getattr(ctrl, "ControlTypeName", "") or ""
    except Exception:
        return ""


def pressed_modifiers() -> set:
    """当前按下的修饰键集合（用于区分双击手势）。"""
    if platform.system() == "Windows":
        try:
            import ctypes

            u = ctypes.windll.user32
            out = set()
            for name, vk in MODIFIER_KEYS.items():
                if u.GetAsyncKeyState(vk) & 0x8000:
                    out.add(name)
            return out
        except Exception:
            return set()
    with _MODIFIER_LOCK:
        return set(_MODIFIER_STATE)


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


def cursor_position():
    """当前鼠标位置（跨平台）；失败给个能看的默认值。"""
    try:
        from pynput.mouse import Controller

        x, y = Controller().position
        return int(x), int(y)
    except Exception:
        return 200, 200


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


# --------------------------------------------------------------------------
# 全局键监听：双击触发
# --------------------------------------------------------------------------
class TriggerKeyListener:
    """监听「双击某个键」触发回调。现阶段只支持单键。"""

    SUPPORTED = ["ctrl", "alt", "shift", "space", "tab", "caps_lock"] + [
        f"f{i}" for i in range(1, 13)
    ]

    def __init__(self, key: str, interval_ms: int, callback):
        # US15：空字符串 = 用户主动禁用，不做任何监听
        self.disabled = not key or key not in self.SUPPORTED
        self.key = key if key in self.SUPPORTED else ""
        self.interval = max(0.15, min(1.0, int(interval_ms) / 1000.0))
        self.callback = callback
        self._last = 0.0
        self._pressed = False
        self._listener = None

    @staticmethod
    def _normalize(key) -> str:
        try:
            from pynput import keyboard
        except Exception:
            return ""
        if isinstance(key, keyboard.Key):
            name = getattr(key, "name", "") or ""
            return {
                "ctrl_l": "ctrl", "ctrl_r": "ctrl",
                "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
                "shift_l": "shift", "shift_r": "shift",
            }.get(name, name)
        try:
            return (key.char or "").lower()
        except Exception:
            return ""

    def start(self) -> bool:
        if self.disabled:
            return False
        try:
            from pynput import keyboard
        except Exception:
            print("[warn] 未安装 pynput，双击唤起不可用", file=sys.stderr)
            return False

        def on_press(key):
            name = self._normalize(key)
            if name != self.key:
                self._last = 0.0
                return
            if self._pressed:  # 过滤系统自动重复
                return
            self._pressed = True
            now = time.monotonic()
            if self._last and (now - self._last) <= self.interval:
                self._last = 0.0
                try:
                    self.callback()
                except Exception as exc:
                    print(f"[warn] 触发回调失败：{exc}", file=sys.stderr)
            else:
                self._last = now

        def on_release(key):
            if self._normalize(key) == self.key:
                self._pressed = False

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            print(f"[warn] 监听 {self.key} 失败：{exc}", file=sys.stderr)
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


class MouseDoubleClickListener:
    """监听「双击鼠标某个键」，并把点击坐标透传给回调（US6）。

    只在两次点击间隔 <= interval 且修饰键匹配时触发；是否真的有选区由回调判断。
    """

    def __init__(self, button: str, modifier: str, interval_ms: int, callback):
        self.button = button if button in ("left", "right", "middle") else "left"
        self.modifier = modifier if modifier in ("none", "ctrl", "alt", "shift") else "none"
        self.interval = max(0.15, min(1.0, int(interval_ms) / 1000.0))
        self.callback = callback
        self._last = 0.0
        self._listener = None
        self._mod_listener = None

    def start(self) -> bool:
        try:
            from pynput import mouse
        except Exception:
            print("[warn] 未安装 pynput，选中双击不可用", file=sys.stderr)
            return False

        if platform.system() != "Windows":
            self._start_modifier_tracker()

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            name = getattr(button, "name", "")
            if name != self.button:
                self._last = 0.0
                return
            now = time.monotonic()
            if self._last and (now - self._last) <= self.interval:
                self._last = 0.0
                if self.modifier != "none" and self.modifier not in pressed_modifiers():
                    return
                try:
                    self.callback(int(x), int(y))
                except Exception as exc:
                    print(f"[warn] 选中双击回调失败：{exc}", file=sys.stderr)
            else:
                self._last = now

        try:
            self._listener = mouse.Listener(on_click=on_click)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            print(f"[warn] 启动鼠标监听失败：{exc}", file=sys.stderr)
            self._listener = None
            return False

    def _start_modifier_tracker(self) -> None:
        """非 Windows 没有 GetAsyncKeyState，用键盘监听自己维护修饰键状态。"""
        try:
            from pynput import keyboard
        except Exception:
            return

        mapping = {
            "ctrl_l": "ctrl", "ctrl_r": "ctrl",
            "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
            "shift_l": "shift", "shift_r": "shift",
        }

        def on_press(key):
            name = mapping.get(getattr(key, "name", ""))
            if name:
                with _MODIFIER_LOCK:
                    _MODIFIER_STATE.add(name)

        def on_release(key):
            name = mapping.get(getattr(key, "name", ""))
            if name:
                with _MODIFIER_LOCK:
                    _MODIFIER_STATE.discard(name)

        try:
            self._mod_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._mod_listener.daemon = True
            self._mod_listener.start()
        except Exception:
            self._mod_listener = None

    def stop(self) -> None:
        for listener in (self._listener, self._mod_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._listener = None
        self._mod_listener = None


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------
PLACEHOLDER = "在这里写字，或者选中一段文字后双击"


# --------------------------------------------------------------------------
# 拼音渲染（主窗口与迷你浮窗共用）
# --------------------------------------------------------------------------
class RubyView:
    """把 analyze() 的结果渲染成「拼音在上、汉字在下」的格子。

    主窗口和迷你浮窗都用它，避免两套渲染逻辑走偏。多音字的主读音可以逐个切换，
    切换状态存在 alt 里（汉字下标 → 读音下标）。
    """

    def __init__(self, parent, app, width_fn):
        self.app = app
        self.colors = app.colors
        self.width_fn = width_fn      # () -> 当前可用宽度
        self.items = []
        self.rows = []
        self.alt = {}
        self.frame = tk.Frame(parent, bg=self.colors["panel"])

    # ---- 尺寸 ----
    def cell_width(self) -> int:
        return self.app.font_char.measure("国") + 16

    def cell_height(self) -> int:
        return (self.app.font_char.metrics("linespace")
                + self.app.font_pinyin.metrics("linespace") + 10)

    def item_width(self, it: dict) -> int:
        if it["readings"]:
            return self.cell_width()
        ch = it["char"]
        if not ch.strip():
            return 10
        return max(24, self.app.font_latin.measure(ch) + 10)

    def content_height(self) -> int:
        self.frame.update_idletasks()
        return self.frame.winfo_reqheight()

    def shown_reading(self, idx: int) -> str:
        it = self.items[idx]
        if not it["readings"]:
            return ""
        return it["readings"][self.alt.get(idx, 0) % len(it["readings"])]

    # ---- 渲染 ----
    def set_items(self, items: list, reset_alt: bool = True) -> None:
        self.items = items
        if reset_alt:
            self.alt = {}
        self.render()

    def _layout(self, content_w: int) -> list:
        rows, cur, cur_w = [], [], 0
        for idx, it in enumerate(self.items):
            w = self.item_width(it)
            if cur and cur_w + w > content_w:
                rows.append(cur)
                cur, cur_w = [], 0
            cur.append((idx, it, w))
            cur_w += w
        if cur:
            rows.append(cur)
        return rows

    def render(self) -> None:
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        if not self.items:
            return

        c = self.colors
        content_w = max(120, self.width_fn() - 36)
        cell_h = self.cell_height()

        for row_items in self._layout(content_w):
            row = tk.Frame(self.frame, bg=c["panel"])
            row.pack(anchor="center")
            self.rows.append(row)
            for idx, it, w in row_items:
                cell = tk.Frame(row, bg=c["panel"], width=w, height=cell_h)
                cell.pack(side="left", padx=2)
                cell.pack_propagate(False)
                if not it["char"].strip():
                    continue
                if it["readings"]:
                    shown = self.shown_reading(idx)
                    py = tk.Label(cell, text=shown, bg=c["panel"], fg=c["accent"],
                                  font=self.app.font_pinyin, bd=0,
                                  highlightthickness=0, padx=0, pady=0)
                    py.place(relx=0.5, y=1, anchor="n")
                    ch = tk.Label(cell, text=it["char"], bg=c["panel"], fg=c["fg"],
                                  font=self.app.font_char, bd=0,
                                  highlightthickness=0, padx=0, pady=0)
                    ch.place(relx=0.5, rely=1.0, y=-1, anchor="s")
                    widgets = (cell, py, ch)
                else:
                    ch = tk.Label(cell, text=it["char"], bg=c["panel"], fg=c["fg_dim"],
                                  font=self.app.font_latin)
                    ch.place(relx=0.5, rely=0.58, anchor="center")
                    widgets = (cell, ch)

                for wdg in widgets:
                    wdg.configure(cursor="hand2")
                    wdg.bind(
                        "<Button-1>",
                        lambda _e, i=idx: self.app.on_char_click(self, i),
                    )


# --------------------------------------------------------------------------
# 迷你浮窗（US7）
# --------------------------------------------------------------------------
class MiniPopup:
    """贴着光标的小浮窗：可拖动、可固定、超时淡出。"""

    def __init__(self, app, text: str, x: int, y: int):
        self.app = app
        self.colors = app.colors
        self.pinned = bool(app.cfg.get("mini_popup_pinned", False))
        self.text = text
        self._drag = (0, 0)
        self._hide_job = None
        self._fade_job = None
        self._dead = False
        self._outside = None          # US17：点浮窗外关闭的鼠标监听
        self._born = time.monotonic()

        c = self.colors
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=c["border"])
        try:
            self.win.attributes("-alpha", 0.0)
        except Exception:
            pass

        self.outer = tk.Frame(self.win, bg=c["panel"])
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 顶部拖动条 + 按钮
        self.bar = tk.Frame(self.outer, bg=c["panel_alt"], height=28)
        self.bar.pack(fill="x")
        self.bar.pack_propagate(False)
        tk.Label(self.bar, text="选中文字 · 拼音", bg=c["panel_alt"], fg=c["fg_dim"],
                 font=app.font_hint).pack(side="left", padx=(10, 0))

        # 从右往左：× / 固定 / 朗读 / 复制
        self._bar_button(self.bar, "×", self.close, danger=True).pack(side="right", padx=(0, 10))
        self.btn_pin = self._bar_button(
            self.bar, "已固定" if self.pinned else "固定", self.toggle_pin)
        self.btn_pin.pack(side="right", padx=2)
        self._bar_button(self.bar, "朗读", self.speak_all).pack(side="right", padx=2)
        self._bar_button(self.bar, "复制", self.copy_plain).pack(side="right", padx=2)

        # 内容
        self.view = RubyView(self.outer, app, lambda: self._width)
        self.view.frame.pack(fill="both", expand=True, padx=8, pady=(6, 8))

        items = analyze(text, app.cfg.get("tone_style", "symbol"),
                        bool(app.cfg.get("filter_non_han", True)))
        need = sum(self.view.item_width(it) for it in items) + 40
        self._width = int(max(200, min(560, need)))
        self.view.set_items(items)

        self.win.update_idletasks()
        height = max(88, self.outer.winfo_reqheight())
        px, py = self._place(x, y, height)
        self.win.geometry(f"{self._width}x{height}+{px}+{py}")
        self.win.deiconify()

        for w in (self.bar, self.outer):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Button-3>", self._popup_menu)
        self.bar.bind("<ButtonPress-1>", self._start_drag)
        self.bar.bind("<B1-Motion>", self._do_drag)
        self.bar.bind("<ButtonRelease-1>", self._end_drag)

        # 鼠标进来就别急着消失
        self.win.bind("<Enter>", lambda _e: self._cancel_hide())
        self.win.bind("<Leave>", lambda _e: self._schedule_hide())

        self.menu = tk.Menu(self.win, tearoff=0)
        self.menu.add_command(label="复制拼音", command=self.copy_plain)
        self.menu.add_command(label="复制「字 + 拼音」", command=self.copy_pairs)
        self.menu.add_command(label="朗读", command=self.speak_all)
        self.menu.add_separator()
        self.menu.add_command(label=self._pin_label(), command=self.toggle_pin)
        self.menu.add_command(label="关闭", command=self.close)

        self._fade_in()
        self._schedule_hide()
        self._start_outside_watch()

    # ---- US17：点浮窗外自动关闭 ----
    def _start_outside_watch(self) -> None:
        if not self.app.cfg.get("popup_dismiss_on_outside_click", True):
            return
        try:
            from pynput import mouse
        except Exception:
            return

        def on_click(x, y, _button, pressed):
            if not pressed:
                return
            # 判定放到 Tk 线程里做（winfo_* 不能跨线程读）
            self.app.post(self._maybe_close_outside, int(x), int(y))

        try:
            self._outside = mouse.Listener(on_click=on_click)
            self._outside.daemon = True
            self._outside.start()
        except Exception as exc:
            print(f"[warn] 浮窗外部点击监听启动失败：{exc}", file=sys.stderr)
            self._outside = None

    def _maybe_close_outside(self, x: int, y: int) -> None:
        if self._dead or self.pinned:
            return
        # 打开浮窗的那一次双击还在路上，给它一点缓冲
        if time.monotonic() - self._born < 0.35:
            return
        if not self.app.cfg.get("popup_dismiss_on_outside_click", True):
            return
        try:
            wx, wy = self.win.winfo_rootx(), self.win.winfo_rooty()
            ww, wh = self.win.winfo_width(), self.win.winfo_height()
        except Exception:
            return
        if wx <= x < wx + ww and wy <= y < wy + wh:
            return
        self.close()

    def _stop_outside_watch(self) -> None:
        if self._outside is not None:
            try:
                self._outside.stop()
            except Exception:
                pass
            self._outside = None

    # ---- 小工具 ----
    def _pin_label(self) -> str:
        return "取消固定" if self.pinned else "固定浮窗"

    def fit_to_content(self) -> None:
        """多音字切换后行宽可能变，重新贴合一次高度。"""
        self.win.update_idletasks()
        height = max(88, self.outer.winfo_reqheight())
        self.win.geometry(f"{self._width}x{height}+{self.win.winfo_x()}+{self.win.winfo_y()}")

    def _bar_button(self, master, text, cmd, danger=False):
        c = self.colors
        lbl = tk.Label(master, text=text, bg=c["panel_alt"], fg=c["fg_dim"],
                       font=self.app.font_hint, padx=8, cursor="hand2")
        hover = c["danger"] if danger else c["fg"]
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", lambda _e: lbl.configure(bg=c["hover"], fg=hover))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=c["panel_alt"], fg=c["fg_dim"]))
        return lbl

    def _place(self, x: int, y: int, height: int):
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        px = min(max(8, x + 10), max(8, sw - self._width - 8))
        py = y + 20
        if py + height > sh - 8:
            py = max(8, y - height - 20)   # 下面放不下就翻到光标上方
        return px, py

    # ---- 交互 ----
    def _start_drag(self, event) -> None:
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())
        try:
            event.widget.grab_set()   # 抓住指针，鼠标跑出标题栏也能继续拖
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _end_drag(self, _event=None) -> None:
        _release_grab(self.win)

    def _popup_menu(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        self.btn_pin.configure(text="已固定" if self.pinned else "固定")
        try:
            self.menu.entryconfigure(4, label=self._pin_label())
        except Exception:
            pass
        if self.pinned:
            self._cancel_hide()
        else:
            self._schedule_hide()

    def speak_all(self) -> None:
        self.app.speech.speak(self.text)

    def copy_plain(self) -> None:
        write_clipboard(pinyin_plain(self.view.items))

    def copy_pairs(self) -> None:
        write_clipboard(pinyin_pairs(self.view.items))

    # ---- 淡入淡出 ----
    def _fade_in(self, step: float = 0.18) -> None:
        if self._dead:
            return
        try:
            alpha = float(self.win.attributes("-alpha"))
        except Exception:
            return
        alpha = min(1.0, alpha + step)
        try:
            self.win.attributes("-alpha", alpha)
        except Exception:
            return
        if alpha < 1.0:
            self.win.after(16, self._fade_in)

    def _cancel_hide(self) -> None:
        if self._hide_job is not None:
            try:
                self.win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _schedule_hide(self) -> None:
        if self.pinned or self._dead:
            return
        ms = int(self.app.cfg.get("mini_popup_auto_hide_ms", 4000) or 0)
        if ms <= 0:
            return
        self._cancel_hide()
        self._hide_job = self.win.after(ms, self._fade_out)

    def _fade_out(self, step: float = 0.12) -> None:
        if self._dead or self.pinned:
            return
        try:
            alpha = float(self.win.attributes("-alpha"))
        except Exception:
            self.close()
            return
        alpha -= step
        if alpha <= 0.02:
            self.close()
            return
        try:
            self.win.attributes("-alpha", alpha)
        except Exception:
            self.close()
            return
        self._fade_job = self.win.after(16, self._fade_out)

    def close(self) -> None:
        if self._dead:
            return
        self._dead = True
        self._stop_outside_watch()
        self._cancel_hide()
        if self._fade_job is not None:
            try:
                self.win.after_cancel(self._fade_job)
            except Exception:
                pass
            self._fade_job = None
        try:
            self.win.destroy()
        except Exception:
            pass
        if getattr(self.app, "_mini", None) is self:
            self.app._mini = None


class HanziPopup:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.theme = normalize_theme(cfg.get("theme"))
        self.colors = theme_colors(self.theme, cfg.get("theme_background"))
        self.font_size = int(cfg.get("font_size", 32))
        self.width = int(cfg.get("window_width", 420))
        self.height = int(cfg.get("window_height", 220))
        self._rows = []
        self._refresh_job = None
        self._maximized = False
        self._restore_geo = ""
        self._drag_origin = (0, 0)
        self._resize_mode = None       # US5：当前正在拖的方向
        self._resize_origin = None
        self._settings_win = None
        self._tray = None
        self._hidden = False
        self._clip_stop = None
        self._trigger = None
        self._hotkeys = None
        self._mouse = None
        self._mini = None
        self._pad = None              # US12：手写板窗口
        self._guide = None            # US11：首启引导页
        self._image_refs = []
        self._ui_queue = queue.Queue()
        self._poll_job = None
        self._hint_job = None
        self._closing = False

        self.root = tk.Tk()
        self.root.withdraw()

        global CLIP_WIDGET
        CLIP_WIDGET = self.root

        self.root.title(APP_TITLE)
        self.root.overrideredirect(True)
        self.root.configure(bg=self.colors["panel"])
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))

        self._set_window_icon()
        self._build_fonts()
        self._build_ui()
        self._bind_events()
        self._poll_ui()

        self.speech = Speech(cfg.get("speech_rate", 0), cfg.get("tts_voice", "auto"))
        # 嗓音列表要走一次 PowerShell（约 0.6 s），提前在后台预热，别卡设置界面
        threading.Thread(target=list_sapi_voices, daemon=True).start()
        self._place_window()

        # 托盘 → 双击触发键 → 热键 → 选中双击（失败都有兜底）
        self.tray_ok = self._start_tray()
        self._start_trigger()
        self._start_hotkeys()
        self._start_select_double()
        if cfg.get("auto_clipboard"):
            self._start_clipboard_watch()

        if cfg.get("start_hidden") and self.tray_ok:
            self._hidden = True
            self.root.withdraw()
        else:
            self.refresh()
            self.root.deiconify()

        # US11：首次启动弹一次引导页
        if cfg.get("first_run", True):
            self.root.after(120, self.open_first_run)

    # ---------------- 图标 / 字体 ----------------
    def _set_window_icon(self) -> None:
        try:
            photo = ImageTk.PhotoImage(make_app_image(64))
            self._image_refs.append(photo)
            self.root.iconphoto(True, photo)
        except Exception:
            pass

    def _pick(self, candidates) -> str:
        families = set(tkfont.families(self.root))
        for name in candidates:
            if name in families:
                return name
        return "Segoe UI" if "Segoe UI" in families else "TkDefaultFont"

    def _build_fonts(self) -> None:
        self.cn_font = self._pick([
            "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
            "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
        ])
        self.latin_font = self._pick(["Segoe UI", "Helvetica Neue", "DejaVu Sans"])

        # tkinter 的正数字号是「点」，会再乘一次系统缩放，导致度量与实际绘制不一致。
        # 统一换算成「像素」（负数），布局才算得准。
        try:
            self.scale = self.root.winfo_fpixels("1i") / 96.0
        except Exception:
            self.scale = 1.0

        def px(pt: float) -> int:
            return max(6, int(round(pt * 4 / 3 * self.scale)))

        self.font_char = tkfont.Font(family=self.cn_font, size=-px(self.font_size), weight="bold")
        self.font_pinyin = tkfont.Font(family=self.latin_font,
                                        size=-px(max(9, self.font_size * 0.34)))
        self.font_latin = tkfont.Font(family=self.latin_font,
                                      size=-px(max(11, self.font_size * 0.55)))
        self.font_ui = tkfont.Font(family=self.cn_font, size=-px(10))
        self.font_entry = tkfont.Font(family=self.cn_font, size=-px(12))
        self.font_ctrl = tkfont.Font(family=self.latin_font, size=-px(13))
        self.font_hint = tkfont.Font(family=self.cn_font, size=-px(8))

    # ---------------- 布局 ----------------
    def _build_ui(self) -> None:
        c = self.colors
        self.outer = tk.Frame(
            self.root, bg=c["panel"], highlightthickness=1,
            highlightbackground=c["border"], highlightcolor=c["border"],
        )
        self.outer.pack(fill="both", expand=True)

        # ---- 自定义标题栏（可拖动区域）----
        self.bar = tk.Frame(self.outer, bg=c["panel"], height=34)
        self.bar.pack(fill="x", side="top")
        self.bar.pack_propagate(False)

        self.title = tk.Label(self.bar, text=APP_TITLE, bg=c["panel"],
                              fg=c["fg_dim"], font=self.font_ui)
        self.title.pack(side="left", padx=(12, 0))

        self.btn_close = self._title_button(self.bar, "×", self.quit, danger=True, big=True)
        self.btn_close.pack(side="right", padx=(0, 8))
        self.btn_max = self._title_button(self.bar, "□", self.toggle_maximize, big=True)
        self.btn_max.pack(side="right", padx=2)
        self.btn_min = self._title_button(self.bar, "−", self.hide_to_tray, big=True)
        self.btn_min.pack(side="right", padx=2)
        # US14：图钉紧挨在「−」左侧，点击切换始终置顶
        self.btn_pin = self._pin_button(self.bar)
        self.btn_pin.pack(side="right", padx=(2, 4))

        self.btn_copy = self._title_button(self.bar, "复制", self.copy_pinyin)
        self.btn_copy.pack(side="right", padx=(2, 10))
        self.btn_speak = self._title_button(self.bar, "朗读", self.speak_current)
        self.btn_speak.pack(side="right", padx=2)

        for w in (self.bar, self.title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Button-3>", self._popup_menu)

        # ---- 输入框 ----
        self.entry_wrap = tk.Frame(self.outer, bg=c["entry_bg"])
        self.entry_wrap.pack(fill="x", padx=12, pady=(0, 10))
        self.entry = tk.Entry(
            self.entry_wrap, bg=c["entry_bg"], fg=c["fg"], insertbackground=c["fg"],
            relief="flat", font=self.font_entry, highlightthickness=0, bd=0,
        )
        self.entry.pack(fill="x", ipady=6, padx=9)

        # 占位提示用独立 Label 叠在输入框上，避免被输入/焦点清掉
        self.placeholder = tk.Label(
            self.entry_wrap, text=PLACEHOLDER, bg=c["entry_bg"], fg=c["fg_dim"],
            font=self.font_entry, anchor="w",
        )
        self.placeholder.place(x=10, rely=0.5, anchor="w")

        # ---- 正文（可滚动）----
        self.body = tk.Frame(self.outer, bg=c["panel"])
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        self.canvas = tk.Canvas(self.body, bg=c["panel"], highlightthickness=0,
                                bd=0, height=76)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.ruby = tk.Frame(self.canvas, bg=c["panel"])
        self._ruby_id = self.canvas.create_window((0, 0), window=self.ruby, anchor="nw")
        self.ruby_view = RubyView(self.ruby, self, lambda: self._current_width())
        self.ruby_view.frame.pack(fill="both", expand=True)
        self.scroll = tk.Scrollbar(
            self.body, orient="vertical", command=self.canvas.yview, width=9,
            troughcolor=c["panel"], bg=c["scroll"], relief="flat", bd=0,
            activebackground=c["border"],
        )
        self.canvas.configure(yscrollcommand=self._on_scroll_set)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.ruby.bind("<Configure>", self._on_ruby_configure)
        for w in (self.canvas, self.ruby):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-3>", self._popup_menu)

        # ---- 多音字提示 ----
        self.multi = tk.Label(
            self.outer, text="", bg=c["panel"], fg=c["fg_dim"],
            font=(self.cn_font, 9), anchor="w", justify="left",
        )
        self.multi.pack(fill="x", padx=14)

        # ---- 底部：提示 + 设置入口（圆圈1）----
        bottom = tk.Frame(self.outer, bg=c["panel"])
        bottom.pack(fill="x", padx=12, pady=(2, 8))

        self.hint = tk.Label(
            bottom, text=self._hint_text(), bg=c["panel"], fg=c["fg_dim"],
            font=self.font_hint, anchor="w",
        )
        self.hint.pack(side="left", padx=(2, 0))

        self.btn_settings = self._gear_button(bottom)
        self.btn_settings.pack(side="right", padx=(6, 2))

        # US12：手写入口只在模块开启时出现
        self.btn_hand = None
        if self.module_enabled("handwriting"):
            self.btn_hand = tk.Label(
                bottom, text="手写", bg=c["panel"], fg=c["fg_dim"],
                font=self.font_hint, padx=6, cursor="hand2",
            )
            self.btn_hand.pack(side="right", padx=(6, 2))
            self.btn_hand.bind("<Button-1>", lambda _e: self.open_handwriting())
            self.btn_hand.bind("<Enter>", lambda _e: self.btn_hand.configure(fg=c["accent"]))
            self.btn_hand.bind("<Leave>", lambda _e: self.btn_hand.configure(fg=c["fg_dim"]))

        # ---- 右键菜单 ----
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="⚙ 设置…", command=self.open_settings)
        self.menu.add_command(label="手写板…", command=self.open_handwriting)
        self.menu.add_command(label="复制「字 + 拼音」", command=self.copy_pairs)
        self.menu.add_command(label="朗读", command=self.speak_current)
        self.menu.add_separator()
        self.menu.add_command(label="切换置顶", command=self.toggle_topmost)
        self.menu.add_command(label="隐藏到托盘", command=self.hide_to_tray)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

        for w in (self.outer, self.hint, self.multi):
            w.bind("<Button-3>", self._popup_menu)

        self._build_resize_zones()

    # ---------------- US5：8 向缩放热区 ----------------
    RESIZE_CURSORS = {
        "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
        "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
        "nw": "size_nw_se", "se": "size_nw_se",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
    }

    def _build_resize_zones(self) -> None:
        """在窗口四周贴一圈透明感的热区，鼠标移上去变双向箭头，按住即可改大小。

        热区浮在所有控件之上（place 后创建即置顶），但只占几像素边缘，
        正中间留给标题栏拖动和正文点击，两者不冲突。
        """
        pad = max(3, int(self.cfg.get("resize_pad", 6)))
        self._zones = {}
        for name in ("n", "s", "w", "e", "nw", "ne", "sw", "se"):
            frame = tk.Frame(self.outer, bg=self.colors["panel"], cursor=self.RESIZE_CURSORS[name])
            frame.bind("<ButtonPress-1>", lambda e, n=name: self._resize_start(e, n))
            frame.bind("<B1-Motion>", self._resize_drag)
            frame.bind("<ButtonRelease-1>", self._resize_end)
            self._zones[name] = (frame, pad)
        self._layout_resize_zones()
        self._sync_resize_zones()

    def _layout_resize_zones(self) -> None:
        pad = max(3, int(self.cfg.get("resize_pad", 6)))
        # name: (relx, rely, anchor, width, height, x, y)；width/height 为 None 表示拉伸到边
        spec = {
            "n":  (0, 0, "nw", None, pad, 0, 0),
            "s":  (0, 1, "sw", None, pad, 0, -pad),
            "w":  (0, 0, "nw", pad, None, 0, 0),
            "e":  (1, 0, "ne", pad, None, 0, 0),
            "nw": (0, 0, "nw", pad * 2, pad * 2, 0, 0),
            "ne": (1, 0, "ne", pad * 2, pad * 2, 0, 0),
            "sw": (0, 1, "sw", pad * 2, pad * 2, 0, 0),
            "se": (1, 1, "se", pad * 2, pad * 2, 0, 0),
        }
        for name, (frame, _old) in self._zones.items():
            relx, rely, anchor, w, h, x, y = spec[name]
            frame.place(
                relx=relx, rely=rely, anchor=anchor, x=x, y=y,
                width=w, height=h,
                relwidth=1.0 if w is None else None,
                relheight=1.0 if h is None else None,
            )
            self._zones[name] = (frame, pad)

    def _sync_resize_zones(self) -> None:
        """最大化时或用户关掉缩放时，把热区藏起来。"""
        show = bool(self.cfg.get("resize_enabled", True)) and not self._maximized
        if show:
            # place_forget 之后必须重新 place 才能回来
            self._layout_resize_zones()
            for frame, _pad in self._zones.values():
                frame.lift()
        else:
            for frame, _pad in self._zones.values():
                frame.place_forget()

    def _resize_start(self, event, name: str) -> None:
        if self._maximized or not self.cfg.get("resize_enabled", True):
            return
        self._resize_mode = name
        self._resize_origin = (
            event.x_root, event.y_root,
            self.root.winfo_width(), self.root.winfo_height(),
            self.root.winfo_x(), self.root.winfo_y(),
        )
        # 热区只有几像素宽，抓住指针才能一路跟到松开
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _resize_drag(self, event) -> None:
        if not self._resize_mode or not self._resize_origin:
            return
        sx, sy, w0, h0, x0, y0 = self._resize_origin
        dx, dy = event.x_root - sx, event.y_root - sy
        min_w = max(160, int(self.cfg.get("min_width", 320)))
        min_h = max(120, int(self.cfg.get("min_height", 200)))

        w, h, x, y = w0, h0, x0, y0
        mode = self._resize_mode
        if "e" in mode:
            w = max(min_w, w0 + dx)
        if "s" in mode:
            h = max(min_h, h0 + dy)
        if "w" in mode:
            w = max(min_w, w0 - dx)
            x = x0 + (w0 - w)
        if "n" in mode:
            h = max(min_h, h0 - dy)
            y = y0 + (h0 - h)

        self.width, self.height = int(w), int(h)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _resize_end(self, _event=None) -> None:
        if not self._resize_mode:
            self._release_grab()
            return
        self._resize_mode = None
        self._resize_origin = None
        self._release_grab()
        self.cfg["window_width"] = int(self.width)
        self.cfg["window_height"] = int(self.height)
        save_config(self.cfg)
        self.refresh()

    def _hint_text(self) -> str:
        key = self.cfg.get("trigger_key", "ctrl")
        if not key:
            return "选中文字双击弹浮窗 · Esc 隐藏 · Ctrl+Enter 朗读"
        label = TRIGGER_LABELS.get(key, "Ctrl")
        return f"双击 {label} 唤起 · Esc 隐藏 · Ctrl+Enter 朗读"

    def _title_button(self, master, text, cmd, danger=False, big=False) -> tk.Label:
        c = self.colors
        lbl = tk.Label(master, text=text, bg=c["panel"], fg=c["fg_dim"],
                       font=self.font_ctrl if big else self.font_ui,
                       padx=8, cursor="hand2")
        hover_fg = c["danger"] if danger else c["fg"]
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", lambda _e: lbl.configure(bg=c["hover"], fg=hover_fg))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=c["panel"], fg=c["fg_dim"]))
        return lbl

    def _pin_button(self, master) -> tk.Label:
        """US14：置顶图钉。钉住 = 实心 + 强调色，松开 = 描边。"""
        c = self.colors
        lbl = tk.Label(master, bg=c["panel"], cursor="hand2", padx=7, pady=2)
        lbl._images = {}
        try:
            for state in ("on", "off", "hover"):
                if state == "on":
                    img = make_pin_image(16, c["accent"], filled=True)
                elif state == "off":
                    img = make_pin_image(16, c["fg_dim"], filled=False)
                else:
                    img = make_pin_image(16, c["fg"], filled=bool(
                        self.cfg.get("always_on_top", True)))
                photo = ImageTk.PhotoImage(img)
                lbl._images[state] = photo
                self._image_refs.append(photo)
            lbl.configure(image=lbl._images["on" if self.cfg.get("always_on_top", True) else "off"])
        except Exception:
            lbl.configure(text="钉", fg=c["fg_dim"], font=self.font_ui)
        lbl.bind("<Button-1>", lambda _e: self.toggle_topmost())
        lbl.bind("<Enter>", lambda _e: lbl.configure(
            image=lbl._images["hover"], bg=c["hover"]))
        lbl.bind("<Leave>", lambda _e: (lbl.configure(bg=c["panel"]), self._refresh_pin()))
        return lbl

    def _refresh_pin(self) -> None:
        lbl = getattr(self, "btn_pin", None)
        if lbl is None:
            return
        images = getattr(lbl, "_images", None) or {}
        key = "on" if self.cfg.get("always_on_top", True) else "off"
        if key in images:
            try:
                lbl.configure(image=images[key])
            except Exception:
                pass

    def module_enabled(self, key: str) -> bool:
        """US11：模块开关统一从这里读，未启用的模块不显示入口。"""
        mods = self.cfg.get("modules") or {}
        return bool(mods.get(key, False))

    def _gear_button(self, master) -> tk.Label:
        c = self.colors
        try:
            normal = ImageTk.PhotoImage(make_gear_image(18, c["fg_dim"]))
            hover = ImageTk.PhotoImage(make_gear_image(18, c["accent"]))
            self._image_refs.extend([normal, hover])
            lbl = tk.Label(master, image=normal, bg=c["panel"], cursor="hand2",
                           padx=4, pady=2)
            lbl.bind("<Enter>", lambda _e: lbl.configure(image=hover, bg=c["hover"]))
            lbl.bind("<Leave>", lambda _e: lbl.configure(image=normal, bg=c["panel"]))
        except Exception:
            lbl = tk.Label(master, text="设置", bg=c["panel"], fg=c["fg_dim"],
                           font=self.font_hint, cursor="hand2", padx=6)
            lbl.bind("<Enter>", lambda _e: lbl.configure(fg=c["accent"]))
            lbl.bind("<Leave>", lambda _e: lbl.configure(fg=c["fg_dim"]))
        lbl.bind("<Button-1>", lambda _e: self.open_settings())
        return lbl

    # ---------------- 事件 ----------------
    def _bind_events(self) -> None:
        self.root.bind("<Escape>", lambda _e: self.hide_to_tray())
        self.root.bind("<Control-Return>", lambda _e: self.speak_current())
        for seq in ("<KeyRelease>", "<ButtonRelease-1>"):
            self.entry.bind(seq, self._schedule_refresh)
        self.entry.bind("<Return>", self._schedule_refresh)
        self.entry.bind("<FocusIn>", lambda _e: self._sync_placeholder())
        self.entry.bind("<FocusOut>", lambda _e: self._sync_placeholder())
        self.entry.bind("<Button-1>", lambda _e: self._sync_placeholder())

    def _focus_entry(self) -> None:
        try:
            self.entry.focus_force()
            self.entry.icursor("end")
        except Exception:
            pass

    def _start_drag(self, event) -> None:
        if self._maximized:
            return
        self._drag_origin = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())
        # 拖动时鼠标很容易跑出标题栏，抓住指针才能持续收到 <B1-Motion>
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        if self._maximized:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event=None) -> None:
        _release_grab(self.root)

    def _release_grab(self) -> None:
        _release_grab(self.root)

    def _popup_menu(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------------- 跨线程调用 ----------------
    def post(self, fn, *args) -> None:
        """把回调丢回 Tk 主线程执行（托盘 / 键盘监听都在别的线程）。"""
        self._ui_queue.put((fn, args))

    def _poll_ui(self) -> None:
        self._poll_job = None
        if self._closing:
            return
        while True:
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception as exc:
                print(f"[warn] UI 回调异常：{exc}", file=sys.stderr)
        if not self._closing:
            self._poll_job = self.root.after(60, self._poll_ui)

    # ---------------- 滚动区 ----------------
    def _on_scroll_set(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scroll.pack_forget()
        elif not self.scroll.winfo_ismapped():
            self.scroll.pack(side="right", fill="y", padx=(2, 0))
        self.scroll.set(first, last)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._ruby_id, width=event.width)

    def _on_ruby_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_wheel(self, event) -> None:
        step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step * max(1, abs(int(event.delta / 120))), "units")

    # ---------------- 占位符 ----------------
    def _sync_placeholder(self) -> None:
        """输入框为空且没有焦点时显示提示文字，否则隐藏。"""
        empty = not self.entry.get().strip()
        focused = self.root.focus_get() is self.entry
        if empty and not focused:
            self.placeholder.place(x=10, rely=0.5, anchor="w")
        else:
            self.placeholder.place_forget()

    # ---------------- 渲染 ----------------
    def _schedule_refresh(self, _event=None) -> None:
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(120, self.refresh)

    def _current_width(self) -> int:
        w = self.root.winfo_width()
        return w if w > 80 else self.width

    def _cell_metrics(self):
        return self.ruby_view.cell_width(), self.ruby_view.cell_height()

    def _item_width(self, it: dict) -> int:
        return self.ruby_view.item_width(it)

    def render_text(self, text: str) -> None:
        self.canvas.yview_moveto(0)
        items = analyze(text, self.cfg.get("tone_style", "symbol"),
                        bool(self.cfg.get("filter_non_han", True)))
        self.ruby_view.set_items(items)

        multi_lines = [
            f"{it['char']}  " + " / ".join(it["readings"])
            for it in items if len(it["readings"]) > 1
        ]
        self.multi.configure(text="　".join(multi_lines[:3]) if multi_lines else "")
        self._update_geometry()

    def _update_geometry(self) -> None:
        if self._maximized:
            wx, wy, ww, wh = work_area(self.root)
            chrome = 34 + 46 + 26 + 34  # 标题栏 + 输入框 + 多音字 + 底部
            self.canvas.configure(height=max(80, wh - chrome))
            self.root.geometry(f"{ww}x{wh}+{wx}+{wy}")
            # 最大化时把内容垂直居中，避免一大片空白压在下方
            self.root.update_idletasks()
            ch = max(80, self.canvas.winfo_height())
            rh = self.ruby.winfo_reqheight()
            self.canvas.coords(self._ruby_id, 0, max(0, (ch - rh) // 2))
            return

        self.canvas.coords(self._ruby_id, 0, 0)
        self.root.update_idletasks()
        content_h = self.ruby.winfo_reqheight()
        max_body = max(70, int(self.root.winfo_screenheight() * 0.5))
        self.canvas.configure(height=max(38, min(content_h, max_body)))
        self.root.update_idletasks()

        # 窗口高度 = max(用户拖出来的高度, 内容需要的高度)，内容变多时自动长高，
        # 内容变少时不会缩回去——否则每次打字窗口都跳一下。
        min_h = max(160, int(self.cfg.get("min_height", 200)))
        height = max(min_h, self.height, self.outer.winfo_reqheight())
        self.height = int(height)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if x <= 0 or y <= 0:
            x, y = 120, 120
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def refresh(self) -> None:
        self._refresh_job = None
        self._sync_placeholder()
        self.render_text(self.entry.get())

    # ---------------- 内容操作 ----------------
    def current_text(self) -> str:
        return self.entry.get().strip()

    def set_text(self, text: str, focus: bool = True) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        if focus:
            self._focus_entry()
        self.refresh()

    def speak_current(self) -> None:
        text = self.current_text()
        if text:
            self.speech.speak(text)

    def copy_pinyin(self) -> None:
        text = self.current_text()
        if not text:
            return
        write_clipboard(pinyin_plain(analyze(text)))
        self._flash_hint("已复制拼音")

    def copy_pairs(self) -> None:
        text = self.current_text()
        if not text:
            return
        write_clipboard(pinyin_pairs(analyze(text)))
        self._flash_hint("已复制「字 + 拼音」")

    def _flash_hint(self, msg: str) -> None:
        old = self._hint_text()
        self.hint.configure(text=msg, fg=self.colors["accent"])
        if self._hint_job is not None:
            try:
                self.root.after_cancel(self._hint_job)
            except Exception:
                pass
        self._hint_job = self.root.after(
            1400, lambda: self.hint.configure(text=old, fg=self.colors["fg_dim"]))

    def toggle_topmost(self) -> None:
        new = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", new)
        self.cfg["always_on_top"] = new
        save_config(self.cfg)
        self._refresh_pin()
        self._flash_hint("已置顶" if new else "已取消置顶")

    # ---------------- 窗口状态 ----------------
    def _place_window(self) -> None:
        self.root.update_idletasks()
        pos = self.cfg.get("position")
        if isinstance(pos, list) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            x = self.root.winfo_screenwidth() - self.width - 80
            y = max(80, self.root.winfo_screenheight() - 480)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def show(self, text=None) -> None:
        self._hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self.root.lift()
        if text is not None:
            self.set_text(text)
        else:
            self._focus_entry()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def hide_to_tray(self) -> None:
        self._remember_geometry()
        self._hidden = True
        self.root.withdraw()

    def _remember_geometry(self) -> None:
        """记住位置与尺寸（最大化时不记，否则会把 0,0 和整屏尺寸存进配置）。"""
        if self._maximized:
            return
        try:
            self.cfg["position"] = [self.root.winfo_x(), self.root.winfo_y()]
            self.cfg["window_width"] = int(self.root.winfo_width())
            self.cfg["window_height"] = int(self.root.winfo_height())
            self.width = int(self.cfg["window_width"])
            self.height = int(self.cfg["window_height"])
            save_config(self.cfg)
        except Exception:
            pass

    def toggle_maximize(self) -> None:
        if self._maximized:
            self._maximized = False
            if self._restore_geo:
                self.root.geometry(self._restore_geo)
            self.refresh()
        else:
            self._restore_geo = (
                f"{self.root.winfo_width()}x{self.root.winfo_height()}"
                f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
            )
            self._maximized = True
            self.refresh()
        self._sync_resize_zones()   # US5：最大化时禁用拖动改大小

    def quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        for job in (self._poll_job, self._hint_job, self._refresh_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._poll_job = self._hint_job = self._refresh_job = None
        self._remember_geometry()
        self._stop_background()
        try:
            self.speech.close()
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _stop_background(self) -> None:
        if self._mini is not None:
            try:
                self._mini.close()
            except Exception:
                pass
            self._mini = None
        if self._mouse is not None:
            try:
                self._mouse.stop()
            except Exception:
                pass
            self._mouse = None
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        if self._trigger is not None:
            try:
                self._trigger.stop()
            except Exception:
                pass
            self._trigger = None
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None
        if self._clip_stop is not None:
            self._clip_stop.set()
            self._clip_stop = None

    # ---------------- 托盘 ----------------
    def _start_tray(self) -> bool:
        try:
            import pystray
        except Exception as exc:
            print(f"[warn] 托盘不可用（{exc}），将保持窗口显示", file=sys.stderr)
            return False

        def later(fn):
            return lambda *_a: self.post(fn)

        try:
            menu = pystray.Menu(
                pystray.MenuItem("首页", later(self.show), default=True),
                # US10：图标统一为齿轮（系统托盘菜单不支持自定义位图，用齿轮字符表达）
                pystray.MenuItem("⚙ 设置", later(self.open_settings)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", later(self.quit)),
            )
            self._tray = pystray.Icon(APP_NAME, make_app_image(64), APP_TITLE, menu=menu)
            self._tray.run_detached()
            return True
        except Exception as exc:
            print(f"[warn] 启动托盘失败：{exc}", file=sys.stderr)
            self._tray = None
            return False

    # ---------------- 双击触发 / 热键 ----------------
    def _start_trigger(self) -> None:
        if self._trigger is not None:
            self._trigger.stop()
        self._trigger = TriggerKeyListener(
            self.cfg.get("trigger_key", "ctrl"),
            int(self.cfg.get("double_click_ms", 400)),
            self._on_trigger_key,
        )
        self._trigger.start()

    def _on_trigger_key(self) -> None:
        """双击触发键。

        默认唤起首页；若打开了「有选区时优先弹迷你窗」，且当前确实有文本选区，
        就在光标旁弹迷你浮窗——这就是文档里说的上下文分流。
        """
        if self.cfg.get("trigger_prefers_selection") and not self._closing:
            text = read_selection_uia()
            if text:
                x, y = cursor_position()
                self.post(self.show_mini, text, x, y)
                return
        self.post(self.show)

    def _start_hotkeys(self) -> None:
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None
        try:
            from pynput import keyboard
        except Exception:
            print("[warn] 未安装 pynput，全局热键不可用", file=sys.stderr)
            return

        def on_quit():
            self.post(self.quit)

        # US15：「抓取选中文字」热键已移除（能力由选中双击覆盖），空值表示禁用
        bindings = {}
        quit_key = str(self.cfg.get("quit_hotkey", "") or "")
        if quit_key:
            bindings[quit_key] = on_quit
        if not bindings:
            return
        try:
            self._hotkeys = keyboard.GlobalHotKeys(bindings)
            self._hotkeys.daemon = True
            self._hotkeys.start()
        except Exception as exc:
            print(f"[warn] 注册热键失败：{exc}", file=sys.stderr)
            self._hotkeys = None

    def _grab_selection(self) -> str:
        return grab_selection(bool(self.cfg.get("preserve_clipboard", True)))

    def _start_clipboard_watch(self) -> None:
        if self._clip_stop is not None:
            return
        stop = threading.Event()
        self._clip_stop = stop

        def worker():
            last = read_clipboard()
            while not stop.is_set():
                stop.wait(0.5)
                try:
                    cur = read_clipboard()
                except Exception:
                    continue
                if cur and cur != last:
                    last = cur
                    stripped = cur.strip()
                    if 0 < len(stripped) <= 12 and HANZI_RE.search(stripped):
                        x, y = cursor_position()
                        self.post(self.show_mini, stripped, x, y)   # US7：贴近光标

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 选中双击 → 迷你浮窗（US6 / US7 / US15）----------------
    def _start_select_double(self) -> None:
        if self._mouse is not None:
            try:
                self._mouse.stop()
            except Exception:
                pass
            self._mouse = None
        if not self.cfg.get("select_double_popup", True):
            return

        # US15：键盘模式——连续按两下「选中双击功能键」，与唤起键互斥
        if self.cfg.get("select_double_mode", "mouse") == "key":
            key = str(self.cfg.get("select_double_key", "shift") or "")
            if not key or key == self.cfg.get("trigger_key"):
                return
            self._mouse = TriggerKeyListener(
                key, int(self.cfg.get("double_click_ms", 400)), self._on_select_double_key)
            self._mouse.start()
            return

        self._mouse = MouseDoubleClickListener(
            self.cfg.get("select_double_button", "left"),
            self.cfg.get("select_double_modifier", "none"),
            int(self.cfg.get("double_click_ms", 400)),
            self._on_select_double,
        )
        self._mouse.start()

    def _on_select_double(self, x: int, y: int) -> None:
        """鼠标双击回调（在监听线程里跑，所以另起一个线程读选区）。"""
        if self._closing or not self.cfg.get("select_double_popup", True):
            return
        threading.Thread(target=self._read_selection_and_pop, args=(x, y), daemon=True).start()

    def _on_select_double_key(self) -> None:
        """键盘功能键双击回调：光标位置即选区位置。"""
        if self._closing or not self.cfg.get("select_double_popup", True):
            return
        x, y = cursor_position()
        threading.Thread(target=self._read_selection_and_pop, args=(x, y), daemon=True).start()

    def _read_selection_and_pop(self, x: int, y: int) -> None:
        text = read_selection_uia()
        if not text and control_type_at(x, y) in TEXT_CONTROL_TYPES:
            # 安全兜底：确认光标下面是文本控件，才允许「备份 → Ctrl+C → 还原」。
            # 资源管理器 / 桌面这类地方双击绝不按 Ctrl+C，否则会变成复制文件。
            text = grab_selection(preserve=bool(self.cfg.get("preserve_clipboard", True)))
        if not text or not HANZI_RE.search(text):
            return
        self.post(self.show_mini, text, x, y)

    def show_mini(self, text: str, x: int = 0, y: int = 0) -> None:
        text = (text or "").strip()
        if not text or self._closing:
            return
        if self._mini is not None:
            try:
                self._mini.close()
            except Exception:
                pass
            self._mini = None
        try:
            self._mini = MiniPopup(self, text, x, y)
        except Exception as exc:
            print(f"[warn] 迷你浮窗打开失败：{exc}", file=sys.stderr)
            self._mini = None

    # ---------------- 单字点击 / 多音字切换（US7 / US9）----------------
    def on_char_click(self, view, idx: int) -> None:
        if idx >= len(view.items):
            return
        it = view.items[idx]
        readings = it["readings"]
        if not readings:
            return

        if self._mini is not None and view is self._mini.view:
            self._mini._cancel_hide()

        # 多音字：点一下换下一个读音，其余读音仍列在多音字行里
        if len(readings) > 1:
            view.alt[idx] = (view.alt.get(idx, 0) + 1) % len(readings)
            view.render()
            if view is self.ruby_view:
                self._update_geometry()
            elif self._mini is not None:
                self._mini.fit_to_content()

        if self.cfg.get("read_char_on_click", True):
            self.speech.speak(it["char"])

        if self._mini is not None and view is self._mini.view:
            self._mini._schedule_hide()

    # ---------------- 设置 ----------------
    def open_settings(self) -> None:
        win = self._settings_win
        if win is not None and win.alive:
            # 已经开着 → 前置唤起，不要开第二个（注意 win 是包装对象，得用 .win）
            try:
                win.win.deiconify()
                win.win.lift()
                win.win.focus_force()
            except Exception:
                self._settings_win = None
                self.open_settings()
            return
        self._settings_win = SettingsWindow(self)

    # ---------------- US11 首启引导 / US12 手写板 ----------------
    def open_first_run(self) -> None:
        if self._closing:
            return
        guide = self._guide
        if guide is not None and getattr(guide, "alive", False):
            try:
                guide.win.deiconify()
                guide.win.lift()
                guide.win.focus_force()
            except Exception:
                self._guide = None
            return
        self._guide = FirstRunWindow(self)

    def open_handwriting(self) -> None:
        if not self.module_enabled("handwriting"):
            self._flash_hint("手写模块未启用：设置 → 功能模块")
            return
        pad = self._pad
        if pad is not None and getattr(pad, "alive", False):
            try:
                pad.win.deiconify()
                pad.win.lift()
                pad.win.focus_force()
            except Exception:
                self._pad = None
            return
        self._pad = HandwritingPad(self)

    def apply_settings(self, values: dict) -> None:
        old_theme = (self.cfg.get("theme"), self.cfg.get("theme_background"))
        old_font = int(self.cfg.get("font_size", 32))
        old_tone = self.cfg.get("tone_style", "symbol")
        old_resize = bool(self.cfg.get("resize_enabled", True))
        old_select = (self.cfg.get("select_double_button"),
                      self.cfg.get("select_double_modifier"),
                      self.cfg.get("select_double_mode"),
                      self.cfg.get("select_double_key"))
        old_hand = self.module_enabled("handwriting")

        self.cfg.update(values)
        self.cfg["schemaVersion"] = CONFIG_SCHEMA
        save_config(self.cfg)

        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self._refresh_pin()

        # US13：主题/背景变了就地重绘（不用重启）
        new_theme = (self.cfg.get("theme"), self.cfg.get("theme_background"))
        if new_theme != old_theme:
            self.rebuild_ui()
            return

        if int(self.cfg.get("font_size", 32)) != old_font:
            self.font_size = int(self.cfg["font_size"])
            self._build_fonts()
            self._restyle_widgets()
            self.refresh()

        self.speech.set_rate(int(self.cfg.get("speech_rate", 0)))
        self.speech.set_voice(self.cfg.get("tts_voice", "auto"))

        # US9：标调方式变了要重新渲染（多音字切换状态一并重置）
        if (self.cfg.get("tone_style", "symbol") != old_tone
                or self.cfg.get("filter_non_han") != values.get("filter_non_han")):
            self.refresh()

        # US5：热区厚度/开关变了重新铺一遍
        if bool(self.cfg.get("resize_enabled", True)) != old_resize:
            self._layout_resize_zones()
            self._sync_resize_zones()

        if self.cfg.get("auto_clipboard"):
            self._start_clipboard_watch()
        elif self._clip_stop is not None:
            self._clip_stop.set()
            self._clip_stop = None

        self._start_trigger()
        self._start_hotkeys()

        # US6 / US15：按钮、修饰键、模式、功能键任一变化都重启监听
        new_select = (self.cfg.get("select_double_button"),
                      self.cfg.get("select_double_modifier"),
                      self.cfg.get("select_double_mode"),
                      self.cfg.get("select_double_key"))
        if new_select != old_select or self._mouse is None:
            self._start_select_double()

        # US12：手写入口随模块开关出现/消失
        if self.module_enabled("handwriting") != old_hand:
            self.rebuild_ui()
            return

        self.hint.configure(text=self._hint_text())
        self._flash_hint("设置已保存")

    def rebuild_ui(self) -> None:
        """按当前配色把主界面整体重画一遍（US13 主题即时生效）。"""
        text = ""
        try:
            text = self.entry.get()
        except Exception:
            pass
        self.theme = normalize_theme(self.cfg.get("theme"))
        self.colors = theme_colors(self.theme, self.cfg.get("theme_background"))
        try:
            self.root.configure(bg=self.colors["panel"])
        except Exception:
            pass
        try:
            self.outer.destroy()
        except Exception:
            pass
        for child in list(self.root.winfo_children()):
            if isinstance(child, tk.Menu):
                try:
                    child.destroy()
                except Exception:
                    pass
        self._image_refs.clear()
        self._build_ui()
        self._bind_events()
        if text:
            try:
                self.entry.insert(0, text)
            except Exception:
                pass
        self._sync_placeholder()
        self.refresh()
        self._sync_resize_zones()
        self.hint.configure(text=self._hint_text())
        self._flash_hint("主题已应用")

    def _restyle_widgets(self) -> None:
        self.title.configure(font=self.font_ui)
        for w in (self.btn_copy, self.btn_speak):
            w.configure(font=self.font_ui)
        for w in (self.btn_close, self.btn_max, self.btn_min):
            w.configure(font=self.font_ctrl)
        self.entry.configure(font=self.font_entry)
        self.hint.configure(font=self.font_hint)
        self.multi.configure(font=(self.cn_font, 9))


# --------------------------------------------------------------------------
# US12：手写（系统引擎优先，ONNX 离线模型备选）
# --------------------------------------------------------------------------
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


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


class HandwritingPad:
    """US12：内置手写板。米字格画布用来试写，识别交给系统手写引擎。"""

    def __init__(self, app: HanziPopup):
        self.app = app
        self.cfg = app.cfg
        self.colors = app.colors
        self.alive = True
        self.strokes = []
        self._cur = None
        self._drag = (0, 0)
        c = self.colors

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("手写板")
        self.win.configure(bg=c["panel"])
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self._build()
        self._center()
        self.win.deiconify()
        self.win.bind("<Escape>", lambda _e: self.close())
        self.mouse.focus_set()

    def _build(self) -> None:
        c = self.colors
        outer = tk.Frame(self.win, bg=c["panel"], highlightthickness=1,
                         highlightbackground=c["border"], highlightcolor=c["border"])
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=c["panel"], height=40)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="手写板", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold")).pack(side="left", padx=14)
        close = tk.Label(header, text="×", bg=c["panel"], fg=c["fg_dim"],
                         font=self.app.font_ui, padx=10, cursor="hand2")
        close.pack(side="right", padx=(0, 8))
        close.bind("<Button-1>", lambda _e: self.close())
        close.bind("<Enter>", lambda _e: close.configure(bg=c["hover"], fg=c["danger"]))
        close.bind("<Leave>", lambda _e: close.configure(bg=c["panel"], fg=c["fg_dim"]))
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._do_drag)
        header.bind("<ButtonRelease-1>", lambda _e: _release_grab(self.win))

        tk.Frame(outer, bg=c["border"], height=1).pack(fill="x")

        board = tk.Frame(outer, bg=c["panel"])
        board.pack(fill="both", expand=True, padx=14, pady=(12, 6))
        self.canvas = tk.Canvas(board, width=380, height=260, bg=c["panel_alt"],
                                highlightthickness=1, highlightbackground=c["border"],
                                cursor="pencil")
        self.canvas.pack(fill="both", expand=True)
        self._draw_grid()
        self.canvas.bind("<Configure>", lambda _e: self._draw_grid())
        self.canvas.bind("<ButtonPress-1>", self._stroke_start)
        self.canvas.bind("<B1-Motion>", self._stroke_move)
        self.canvas.bind("<ButtonRelease-1>", self._stroke_end)

        # 画布下面放一个不可见 Entry 只是为了拿到键盘焦点，不影响交互
        self.mouse = tk.Frame(outer, bg=c["panel"], height=0)
        self.mouse.pack(fill="x")

        tools = tk.Frame(outer, bg=c["panel"])
        tools.pack(fill="x", padx=14, pady=(0, 4))
        self._btn(tools, "识别", self.recognize, primary=True).pack(side="left")
        self._btn(tools, "撤销", self.undo).pack(side="left", padx=6)
        self._btn(tools, "清空", self.clear).pack(side="left")
        self._btn(tools, "系统手写面板", self.system_panel).pack(side="right")

        self.status = tk.Label(outer, text=handwriting_status(self.cfg.get("handwriting_engine")),
                               bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
                               anchor="w", justify="left", wraplength=380)
        self.status.pack(fill="x", padx=14, pady=(0, 10))

    def _btn(self, master, text, cmd, primary=False):
        c = self.colors
        bg = c["accent"] if primary else c["panel_alt"]
        fg = c["accent_fg"] if primary else c["fg"]
        lbl = tk.Label(master, text=text, bg=bg, fg=fg,
                       font=(self.app.cn_font, 10), padx=14, pady=5, cursor="hand2")
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", lambda _e: lbl.configure(
            bg=c["accent"] if primary else c["hover"]))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=bg))
        return lbl

    def _draw_grid(self) -> None:
        """米字格：虚线十字 + 对角线，随画板尺寸自适应。"""
        c = self.colors
        self.canvas.delete("grid")
        w = self.canvas.winfo_width() or 380
        h = self.canvas.winfo_height() or 260
        if w < 20 or h < 20:
            return
        dash = (4, 6)
        self.canvas.create_line(w / 2, 6, w / 2, h - 6, fill=c["border"], dash=dash,
                                tags="grid")
        self.canvas.create_line(6, h / 2, w - 6, h / 2, fill=c["border"], dash=dash,
                                tags="grid")
        self.canvas.create_line(6, 6, w - 6, h - 6, fill=c["border"], dash=dash,
                                tags="grid")
        self.canvas.create_line(w - 6, 6, 6, h - 6, fill=c["border"], dash=dash,
                                tags="grid")
        self.canvas.tag_lower("grid")

    # ---- 书写 ----
    def _stroke_start(self, event) -> None:
        self._cur = [(event.x, event.y)]
        self.strokes.append(self._cur)
        self.canvas.create_oval(event.x - 1, event.y - 1, event.x + 1, event.y + 1,
                                fill=self.colors["fg"], outline="")

    def _stroke_move(self, event) -> None:
        if not self._cur:
            return
        x, y = event.x, event.y
        px, py = self._cur[-1]
        self._cur.append((x, y))
        self.canvas.create_line(px, py, x, y, fill=self.colors["fg"],
                                width=3, capstyle="round")

    def _stroke_end(self, _event=None) -> None:
        self._cur = None

    def undo(self) -> None:
        if not self.strokes:
            return
        self.strokes.pop()
        self._redraw()

    def clear(self) -> None:
        self.strokes = []
        self._redraw()

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._draw_grid()
        for stroke in self.strokes:
            for (px, py), (x, y) in zip(stroke, stroke[1:]):
                self.canvas.create_line(px, py, x, y, fill=self.colors["fg"],
                                        width=3, capstyle="round")

    # ---- 识别 ----
    def recognize(self) -> None:
        if not any(len(s) >= 2 for s in self.strokes):
            self._set_status("先在画板上写一个字，或直接点「系统手写面板」")
            return
        if self.cfg.get("handwriting_engine") == "offline":
            self._set_status(handwriting_status("offline")
                             + "；改用系统手写面板同样可以出字")
            return
        self.system_panel()

    def system_panel(self) -> None:
        ok = open_system_handwriting(self.app)
        if ok:
            self._set_status("已唤起系统手写面板：写在面板里，识别结果会直接进输入框")
            self.win.after(400, self.close)
        else:
            self._set_status("系统手写面板不可用：可试 Win + Ctrl + O 手动打开")

    def _set_status(self, msg: str) -> None:
        try:
            self.status.configure(text=msg)
        except Exception:
            pass

    # ---- 窗口 ----
    def _start_drag(self, event) -> None:
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _center(self) -> None:
        w, h = 420, 430
        self.win.update_idletasks()
        x = self.app.root.winfo_x() + (self.app.root.winfo_width() - w) // 2
        y = self.app.root.winfo_y() + (self.app.root.winfo_height() - h) // 2
        x = max(40, min(x, self.win.winfo_screenwidth() - w - 40))
        y = max(40, min(y, self.win.winfo_screenheight() - h - 60))
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def close(self) -> None:
        self.alive = False
        try:
            self.win.destroy()
        except Exception:
            pass
        if getattr(self.app, "_pad", None) is self:
            self.app._pad = None


class FirstRunWindow:
    """US11：首次启动的一次性引导页，列出第 2 批可选功能供勾选。"""

    def __init__(self, app: HanziPopup):
        self.app = app
        self.cfg = app.cfg
        self.colors = app.colors
        self.alive = True
        self.vars = {}
        self._drag = (0, 0)
        c = self.colors

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("欢迎使用")
        self.win.configure(bg=c["panel"])
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self._build()
        self._center()
        self.win.deiconify()
        self.win.bind("<Escape>", lambda _e: self.confirm())

    def _build(self) -> None:
        c = self.colors
        outer = tk.Frame(self.win, bg=c["panel"], highlightthickness=1,
                         highlightbackground=c["border"], highlightcolor=c["border"])
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=c["panel"])
        header.pack(fill="x", padx=18, pady=(16, 6))
        tk.Label(header, text="欢迎使用 汉字拼音浮窗", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 13, "bold"), anchor="w").pack(fill="x")
        tk.Label(header,
                 text="先挑几个想用的功能吧：下面都是可选项，之后在「设置 → 功能模块」里随时能改。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 9),
                 anchor="w", justify="left", wraplength=420).pack(fill="x", pady=(6, 0))
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._do_drag)
        header.bind("<ButtonRelease-1>", lambda _e: _release_grab(self.win))

        listwrap = tk.Frame(outer, bg=c["panel_alt"])
        listwrap.pack(fill="both", expand=True, padx=18, pady=10)

        mods = self.cfg.get("modules") or {}
        for idx, mod in enumerate(MODULES):
            var = tk.BooleanVar(value=bool(mods.get(mod["key"], mod.get("default", False))))
            self.vars[mod["key"]] = var
            row = tk.Frame(listwrap, bg=c["panel_alt"])
            row.pack(fill="x", padx=10, pady=1)
            tk.Checkbutton(
                row, text=mod["label"], variable=var, bg=c["panel_alt"], fg=c["fg"],
                selectcolor=c["panel"], activebackground=c["panel_alt"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2", width=18,
            ).pack(side="left")
            tk.Label(row, text=mod["hint"], bg=c["panel_alt"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 8), anchor="w").pack(side="left", padx=(4, 0))

        footer = tk.Frame(outer, bg=c["panel"])
        footer.pack(fill="x", padx=18, pady=(0, 16))
        tk.Label(footer, text="不选也能用：拼音、朗读、复制、选中双击浮窗都是基础功能。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
                 anchor="w").pack(fill="x")

        btns = tk.Frame(footer, bg=c["panel"])
        btns.pack(fill="x", pady=(8, 0))
        start = tk.Label(btns, text="开始使用", bg=c["accent"], fg=c["accent_fg"],
                         font=(self.app.cn_font, 10), padx=18, pady=6, cursor="hand2")
        start.pack(side="right")
        start.bind("<Button-1>", lambda _e: self.confirm())
        none = tk.Label(btns, text="全部不选", bg=c["panel_alt"], fg=c["fg"],
                        font=(self.app.cn_font, 10), padx=14, pady=6, cursor="hand2")
        none.pack(side="right", padx=8)
        none.bind("<Button-1>", lambda _e: self._set_all(False))

    def _set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)

    def confirm(self) -> None:
        if not self.alive:
            return
        self.cfg["modules"] = {k: bool(v.get()) for k, v in self.vars.items()}
        self.cfg["first_run"] = False
        save_config(self.cfg)
        self.close()
        self.app.rebuild_ui()

    def _start_drag(self, event) -> None:
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _center(self) -> None:
        w, h = 480, 560
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = max(60, (self.win.winfo_screenheight() - h) // 2 - 40)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def close(self) -> None:
        self.alive = False
        try:
            self.win.destroy()
        except Exception:
            pass
        if getattr(self.app, "_guide", None) is self:
            self.app._guide = None


# --------------------------------------------------------------------------
# 设置窗口
# --------------------------------------------------------------------------
class SettingsWindow:
    def __init__(self, app: HanziPopup):
        self.app = app
        self.cfg = app.cfg
        self.colors = app.colors
        self.alive = True
        self.vars = {}
        self.pages = {}
        self.nav_items = {}
        self.current = SETTING_GROUPS[0]["key"]
        self._status_job = None
        self._drag = (0, 0)

        c = self.colors
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title(f"设置 · {APP_TITLE}")
        self.win.configure(bg=c["panel"])
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)

        self._build()
        self._center()
        self.win.deiconify()
        self.win.bind("<Escape>", lambda _e: self.close())
        # 滚轮在任何子控件上都能带动内容区（设置窗口是置顶的，不影响主窗口）
        self.win.bind_all("<MouseWheel>", self._on_content_wheel)

        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._do_drag)
        self.header.bind("<ButtonRelease-1>", self._end_drag)

    # ---- 骨架 ----
    def _build(self) -> None:
        c = self.colors
        self.outer = tk.Frame(self.win, bg=c["panel"], highlightthickness=1,
                              highlightbackground=c["border"], highlightcolor=c["border"])
        self.outer.pack(fill="both", expand=True)

        self.header = tk.Frame(self.outer, bg=c["panel"], height=44)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        tk.Label(self.header, text="设置", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold")).pack(side="left", padx=16)

        close = tk.Label(self.header, text="×", bg=c["panel"], fg=c["fg_dim"],
                         font=self.app.font_ui, padx=10, cursor="hand2")
        close.pack(side="right", padx=(0, 8))
        close.bind("<Button-1>", lambda _e: self.close())
        close.bind("<Enter>", lambda _e: close.configure(bg=c["hover"], fg=c["danger"]))
        close.bind("<Leave>", lambda _e: close.configure(bg=c["panel"], fg=c["fg_dim"]))

        tk.Frame(self.outer, bg=c["border"], height=1).pack(fill="x")

        # 底部按钮（先占位，避免被 body 的 expand 挤掉）
        tk.Frame(self.outer, bg=c["border"], height=1).pack(fill="x", side="bottom")
        footer = tk.Frame(self.outer, bg=c["panel"], height=56)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self.status = tk.Label(footer, text="", bg=c["panel"], fg=c["danger"],
                               font=(self.app.cn_font, 9), anchor="w")
        self.status.pack(side="left", padx=16)

        self._button(footer, "保存", self.save, primary=True).pack(side="right", padx=(6, 14), pady=12)
        self._button(footer, "取消", self.close).pack(side="right", padx=4, pady=12)
        self._button(footer, "恢复默认", self.reset_default).pack(side="right", padx=4, pady=12)

        body = tk.Frame(self.outer, bg=c["panel"])
        body.pack(fill="both", expand=True)

        # 左侧分组导航
        self.side = tk.Frame(body, bg=c["panel_alt"], width=140)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        for group in SETTING_GROUPS:
            self._nav(group["key"], group["title"])
        self._nav("about", "关于")

        # 右侧内容（设置项会越加越多，这里做成可滚动的）
        wrap = tk.Frame(body, bg=c["panel"])
        wrap.pack(side="left", fill="both", expand=True)

        self.content_canvas = tk.Canvas(wrap, bg=c["panel"], highlightthickness=0, bd=0)
        self.content_canvas.pack(side="left", fill="both", expand=True)
        self.content_scroll = tk.Scrollbar(
            wrap, orient="vertical", command=self.content_canvas.yview, width=9,
            troughcolor=c["panel"], bg=c["scroll"], relief="flat", bd=0,
            activebackground=c["border"],
        )
        self.content_canvas.configure(yscrollcommand=self._on_content_scroll)

        self.content = tk.Frame(self.content_canvas, bg=c["panel"])
        self._content_id = self.content_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self.content.bind(
            "<Configure>",
            lambda _e: self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all")),
        )
        self.content_canvas.bind(
            "<Configure>",
            lambda e: self.content_canvas.itemconfigure(self._content_id, width=e.width),
        )
        self.content_canvas.bind("<MouseWheel>", self._on_content_wheel)
        self.content.bind("<MouseWheel>", self._on_content_wheel)

        for group in SETTING_GROUPS:
            self.pages[group["key"]] = self._build_group_page(group)
        self.pages["about"] = self._build_about_page()

        self._show_page(self.current)

    def _on_content_scroll(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.content_scroll.pack_forget()
        elif not self.content_scroll.winfo_ismapped():
            self.content_scroll.pack(side="right", fill="y")
        self.content_scroll.set(first, last)

    def _on_content_wheel(self, event) -> None:
        self.content_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _nav(self, key: str, title: str) -> None:
        c = self.colors
        lbl = tk.Label(self.side, text=title, bg=c["panel_alt"], fg=c["fg_dim"],
                       font=(self.app.cn_font, 11), anchor="w", padx=18, pady=9,
                       cursor="hand2")
        lbl.pack(fill="x", pady=1)
        lbl.bind("<Button-1>", lambda _e, k=key: self._show_page(k))
        lbl.bind("<Enter>", lambda _e, l=lbl, k=key: self._nav_hover(l, k, True))
        lbl.bind("<Leave>", lambda _e, l=lbl, k=key: self._nav_hover(l, k, False))
        self.nav_items[key] = lbl

    def _nav_hover(self, lbl, key, enter: bool) -> None:
        c = self.colors
        if key == self.current:
            return
        lbl.configure(bg=c["hover"] if enter else c["panel_alt"])

    def _show_page(self, key: str) -> None:
        c = self.colors
        self.current = key
        for frame in self.pages.values():
            frame.pack_forget()
        # 内容区是可滚动的，页面只负责占满宽度，高度按需
        self.pages[key].pack(fill="x", padx=18, pady=14)
        self.content_canvas.yview_moveto(0)

        for k, lbl in self.nav_items.items():
            if k == key:
                lbl.configure(bg=c["panel"], fg=c["accent"],
                              font=(self.app.cn_font, 11, "bold"))
            else:
                lbl.configure(bg=c["panel_alt"], fg=c["fg_dim"],
                              font=(self.app.cn_font, 11))

    def _button(self, master, text, cmd, primary=False):
        c = self.colors
        bg = c["accent"] if primary else c["panel_alt"]
        fg = "#0f1512" if primary else c["fg"]
        btn = tk.Label(master, text=text, bg=bg, fg=fg,
                       font=(self.app.cn_font, 10), padx=16, pady=6, cursor="hand2")
        btn.bind("<Button-1>", lambda _e: cmd())
        hover = c["accent"] if primary else c["hover"]
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
        return btn

    # ---- 页面 ----
    def _choices_for(self, item: dict) -> list:
        """静态选项 + 运行时来源（目前只有系统嗓音列表）。"""
        choices = list(item["choices"])
        if item.get("choices_from") == "voices":
            known = {value for _lb, value in choices}
            for name, gender, culture in list_sapi_voices():
                if name in known:
                    continue
                tag = (culture or "").upper()
                label = f"{name} · {tag}" if tag else name
                choices.append((label, name))
        return choices

    def _build_group_page(self, group: dict) -> tk.Frame:
        c = self.colors
        page = tk.Frame(self.content, bg=c["panel"])
        tk.Label(page, text=group["title"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        if group["key"] == "module":
            self._build_modules_block(page)
        for item in group["items"]:
            self._build_item(page, item)
        return page

    def _build_modules_block(self, parent) -> None:
        """US11：15 个可选模块的开关（本期只做开关与入口，功能随迭代交付）。"""
        c = self.colors
        tk.Label(parent, text="可选功能模块", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(parent, text="勾选即启用；未启用的模块不加载依赖、不显示入口。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
                 anchor="w", justify="left").pack(fill="x", pady=(2, 8))

        grid = tk.Frame(parent, bg=c["panel"])
        grid.pack(fill="x")
        mods = self.cfg.get("modules") or {}
        self.module_vars = {}
        for idx, mod in enumerate(MODULES):
            var = tk.BooleanVar(value=bool(mods.get(mod["key"], mod.get("default", False))))
            self.module_vars[mod["key"]] = var
            tk.Checkbutton(
                grid, text=mod["label"], variable=var, bg=c["panel"], fg=c["fg"],
                selectcolor=c["panel_alt"], activebackground=c["panel"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2",
            ).grid(row=idx, column=0, sticky="w", pady=1)
            tk.Label(grid, text=mod["hint"], bg=c["panel"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 8), anchor="w").grid(
                row=idx, column=1, sticky="w", padx=(10, 0))

        tk.Frame(parent, bg=c["border"], height=1).pack(fill="x", pady=(10, 10))

    def _build_item(self, parent, item: dict) -> None:
        c = self.colors
        row = tk.Frame(parent, bg=c["panel"])
        row.pack(fill="x")
        # 标签列固定宽度（像素），否则长标签会爬到控件上去
        row.columnconfigure(0, minsize=176)
        row.columnconfigure(1, weight=1)

        tk.Label(row, text=item["label"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 10), anchor="w", justify="left").grid(
            row=0, column=0, sticky="w", pady=3)

        holder = tk.Frame(row, bg=c["panel"])
        holder.grid(row=0, column=1, sticky="w")
        ctrl = holder          # 控件都往这一格塞

        key = item["key"]
        default = DEFAULT_CONFIG.get(key)
        kind = item["type"]

        if kind == "bool":
            var = tk.BooleanVar(value=bool(self.cfg.get(key, default)))
            chk = tk.Checkbutton(
                ctrl, text="启用", variable=var, bg=c["panel"], fg=c["fg_dim"],
                selectcolor=c["panel_alt"], activebackground=c["panel"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2",
            )
            chk.pack(side="left")
            self.vars[key] = var
        elif kind == "int":
            var = tk.StringVar(value=str(self.cfg.get(key, default)))
            tk.Spinbox(
                ctrl, from_=item["min"], to=item["max"], increment=item.get("step", 1),
                textvariable=var, width=6, bg=c["entry_bg"], fg=c["fg"],
                buttonbackground=c["panel_alt"], relief="flat",
                insertbackground=c["fg"], font=(self.app.cn_font, 10),
                highlightthickness=0, bd=0,
            ).pack(side="left")
            if item.get("suffix"):
                tk.Label(ctrl, text=item["suffix"], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 9)).pack(side="left", padx=(4, 0))
            self.vars[key] = var
        elif kind == "color":
            var = tk.StringVar(value=str(self.cfg.get(key) or ""))
            tk.Entry(
                ctrl, textvariable=var, width=10, bg=c["entry_bg"], fg=c["fg"],
                relief="flat", insertbackground=c["fg"], highlightthickness=0, bd=0,
                font=(self.app.cn_font, 10),
            ).pack(side="left", ipady=3, padx=(0, 6))

            def pick_color(v=var):
                from tkinter import colorchooser
                try:
                    _rgb, hexv = colorchooser.askcolor(
                        color=v.get() or None, parent=self.win, title="选择背景色")
                except Exception:
                    return
                if hexv:
                    v.set(hexv)

            pick = tk.Label(ctrl, text="选择…", bg=c["panel_alt"], fg=c["fg"],
                            font=(self.app.cn_font, 9), padx=8, pady=3, cursor="hand2")
            pick.pack(side="left")
            pick.bind("<Button-1>", lambda _e: pick_color())
            follow = tk.Label(ctrl, text="跟随主题", bg=c["panel_alt"], fg=c["fg_dim"],
                              font=(self.app.cn_font, 9), padx=8, pady=3, cursor="hand2")
            follow.pack(side="left", padx=(4, 0))
            follow.bind("<Button-1>", lambda _e: var.set(""))
            self.vars[key] = var
        elif kind == "choice":
            choices = self._choices_for(item)
            current = self.cfg.get(key, default)
            if item.get("readonly"):
                tk.Label(ctrl, text=choices[0][0], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 10)).pack(side="left")
                self.vars[key] = tk.StringVar(value=current)
            else:
                label = next((lb for lb, val in choices if val == current), choices[0][0])
                var = tk.StringVar(value=label)
                self._dropdown(ctrl, var, choices)
                self.vars[key] = var
                self.vars.setdefault("__choices__", {})[key] = dict(choices)

        if item.get("hint"):
            tk.Label(parent, text=item["hint"], bg=c["panel"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 8), anchor="w", justify="left").pack(
                fill="x", pady=(0, 10))

    def _dropdown(self, row, var, choices) -> None:
        """统一样式的下拉选择：Label + 弹出菜单（替代深色主题下发白的 OptionMenu）。"""
        c = self.colors
        holder = tk.Frame(row, bg=c["entry_bg"], highlightthickness=0)
        holder.pack(side="left")

        text = tk.Label(holder, textvariable=var, bg=c["entry_bg"], fg=c["fg"],
                        font=(self.app.cn_font, 10), padx=8, pady=3, cursor="hand2")
        text.pack(side="left")
        try:
            self._caret = ImageTk.PhotoImage(make_caret_image(9, c["fg_dim"]))
            self.app._image_refs.append(self._caret)
            arrow = tk.Label(holder, image=self._caret, bg=c["entry_bg"],
                             cursor="hand2", padx=6)
        except Exception:
            arrow = tk.Label(holder, text="v", bg=c["entry_bg"], fg=c["fg_dim"],
                             font=(self.app.cn_font, 8), cursor="hand2", padx=6)
        arrow.pack(side="left", padx=(0, 2))

        menu = tk.Menu(row, tearoff=0, bg=c["panel_alt"], fg=c["fg"],
                       activebackground=c["accent"], activeforeground="#0f1512",
                       bd=0, font=(self.app.cn_font, 10))
        for lb, _val in choices:
            menu.add_command(label=lb, command=lambda v=lb: var.set(v))

        def popup(_e=None):
            try:
                menu.tk_popup(holder.winfo_rootx(),
                              holder.winfo_rooty() + holder.winfo_height() + 2)
            finally:
                menu.grab_release()

        for w in (text, arrow, holder):
            w.bind("<Button-1>", popup)
            w.bind("<Enter>", lambda _e: [x.configure(bg=c["hover"]) for x in (text, arrow, holder)])
            w.bind("<Leave>", lambda _e: [x.configure(bg=c["entry_bg"]) for x in (text, arrow, holder)])

    def _build_about_page(self) -> tk.Frame:
        c = self.colors
        page = tk.Frame(self.content, bg=c["panel"])
        tk.Label(page, text="关于", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold"), anchor="w").pack(fill="x", pady=(0, 12))

        rows = [
            ("版本", VERSION),
            ("配置版本", f"schemaVersion = {CONFIG_SCHEMA}"),
            ("配置目录", os.path.dirname(config_path())),
            ("运行环境", f"Python {platform.python_version()} · {platform.system()}"),
        ]
        for name, value in rows:
            row = tk.Frame(page, bg=c["panel"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=name, bg=c["panel"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 9), width=9, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=c["panel"], fg=c["fg"],
                     font=(self.app.cn_font, 9), anchor="w", justify="left",
                     wraplength=370).pack(side="left", fill="x")

        btns = tk.Frame(page, bg=c["panel"])
        btns.pack(fill="x", pady=(16, 0))
        self._button(btns, "打开配置文件夹", self._open_config_dir).pack(side="left")
        self._button(btns, "项目主页",
                     lambda: webbrowser.open(PROJECT_URL)).pack(side="left", padx=8)

        tk.Label(
            page,
            text="认字由系统手写引擎负责，本工具负责拼音、朗读与复制。\n"
                 "双击触发键唤起 · Esc 隐藏 · Ctrl+Enter 朗读 · 标题栏图钉切换置顶\n"
                 "首次启动的模块清单可在「功能模块」页随时增删。",
            bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
            anchor="w", justify="left",
        ).pack(fill="x", pady=(18, 0))
        return page

    def _open_config_dir(self) -> None:
        path = os.path.dirname(config_path())
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self._set_status(f"打开目录失败：{exc}")

    # ---- 交互 ----
    def _start_drag(self, event) -> None:
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())
        try:
            event.widget.grab_set()   # 抓住指针，鼠标跑出标题栏也能继续拖
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _end_drag(self, _event=None) -> None:
        _release_grab(self.win)

    def _center(self) -> None:
        w, h = 640, 560
        self.win.update_idletasks()
        x = self.app.root.winfo_x() + (self.app.root.winfo_width() - w) // 2
        y = self.app.root.winfo_y() + (self.app.root.winfo_height() - h) // 2
        x = max(40, min(x, self.win.winfo_screenwidth() - w - 40))
        y = max(40, min(y, self.win.winfo_screenheight() - h - 60))
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _set_status(self, msg: str) -> None:
        self.status.configure(text=msg)
        if self._status_job:
            try:
                self.win.after_cancel(self._status_job)
            except Exception:
                pass
        self._status_job = self.win.after(3000, lambda: self.status.configure(text=""))

    def reset_default(self) -> None:
        for group in SETTING_GROUPS:
            for item in group["items"]:
                key = item["key"]
                if key not in self.vars:
                    continue
                default = DEFAULT_CONFIG.get(key)
                if item["type"] == "bool":
                    self.vars[key].set(bool(default))
                elif item["type"] == "int":
                    self.vars[key].set(str(default))
                elif item["type"] == "color":
                    self.vars[key].set(str(default or ""))
                elif item["type"] == "choice" and not item.get("readonly"):
                    choices = self._choices_for(item)
                    label = next((lb for lb, val in choices if val == default),
                                 choices[0][0])
                    self.vars[key].set(label)
        for key, var in getattr(self, "module_vars", {}).items():
            var.set(bool(DEFAULT_CONFIG["modules"].get(key, False)))
        self._set_status("已恢复默认值（尚未保存）")

    def _collect(self) -> dict:
        values = {}
        for group in SETTING_GROUPS:
            for item in group["items"]:
                key = item["key"]
                var = self.vars.get(key)
                if var is None:
                    continue
                if item["type"] == "bool":
                    values[key] = bool(var.get())
                elif item["type"] == "int":
                    try:
                        num = int(str(var.get()).strip())
                    except Exception:
                        raise ValueError(f"「{item['label']}」需要填写数字")
                    if not (item["min"] <= num <= item["max"]):
                        raise ValueError(
                            f"「{item['label']}」需在 {item['min']} ~ {item['max']} 之间")
                    values[key] = num
                elif item["type"] == "choice" and not item.get("readonly"):
                    mapping = self.vars["__choices__"][key]
                    label = var.get()
                    if label not in mapping:
                        raise ValueError(f"「{item['label']}」取值无效")
                    values[key] = mapping[label]
                elif item["type"] == "color":
                    raw = str(var.get() or "").strip()
                    if not raw:
                        values[key] = None
                    elif _hex_to_rgb(raw) is None:
                        raise ValueError(f"「{item['label']}」需要 #rrggbb 形式的颜色，或留空")
                    else:
                        values[key] = raw if raw.startswith("#") else "#" + raw
        # US11：模块开关
        values["modules"] = {
            key: bool(var.get()) for key, var in getattr(self, "module_vars", {}).items()
        }
        return values

    def save(self) -> None:
        try:
            values = self._collect()
        except ValueError as exc:
            self._set_status(str(exc))
            return

        trigger = values.get("trigger_key")
        if trigger and trigger not in TriggerKeyListener.SUPPORTED:
            self._set_status("该按键暂不支持，请换一个")
            return

        # US15：键盘模式下「选中双击功能键」必须与「双击唤起键」不同
        if values.get("select_double_popup") and values.get("select_double_mode") == "key":
            sel_key = str(values.get("select_double_key") or "")
            if not sel_key:
                self._set_status("键盘模式需要选一个功能键，或改回鼠标模式")
                return
            if sel_key == trigger:
                ok = messagebox.askyesno(
                    "快捷键冲突",
                    "该键与唤起快捷键冲突，是否互换唤起与选中的快捷键？",
                    parent=self.win,
                )
                if not ok:
                    self._restore_choice("select_double_key",
                                         self.cfg.get("select_double_key", "shift"))
                    self._set_status("已取消，未做修改")
                    return
                values["trigger_key"], values["select_double_key"] = sel_key, trigger

        self.app.apply_settings(values)
        self.close()

    def _restore_choice(self, key: str, value: str) -> None:
        """把某个下拉框回退到 cfg 里的旧值（用户点了「取消」时用）。"""
        mapping = self.vars.get("__choices__", {}).get(key)
        var = self.vars.get(key)
        if not mapping or var is None:
            return
        label = next((lb for lb, val in mapping.items() if val == value), None)
        if label:
            var.set(label)

    def close(self) -> None:
        self.alive = False
        try:
            self.win.unbind_all("<MouseWheel>")
        except Exception:
            pass
        if self._status_job is not None:
            try:
                self.win.after_cancel(self._status_job)
            except Exception:
                pass
            self._status_job = None
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.app._settings_win is self:
            self.app._settings_win = None


# --------------------------------------------------------------------------
# 单实例
# --------------------------------------------------------------------------
def acquire_single_instance():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        sock.listen(1)
        return sock
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=1.0) as conn:
                conn.sendall(b"show\n")
        except Exception:
            pass
        return None


def serve_instance(sock, app: HanziPopup) -> None:
    def worker():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            try:
                conn.recv(16)
                app.post(app.show)
            except Exception:
                pass
            finally:
                conn.close()

    threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def enable_dpi_awareness() -> None:
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def work_area(root):
    """返回桌面可用工作区 (x, y, w, h)，单位与 tkinter 一致（逻辑像素）。

    Windows 上通过 SPI_GETWORKAREA 取得，自动避开任务栏——否则「最大化」会盖住
    托盘区，用户反而找不到托盘图标。其它平台退化为整块屏幕。
    """
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0
            ):
                pw = ctypes.windll.user32.GetSystemMetrics(0) or sw
                # 进程 DPI aware 时 ctypes 拿到物理像素，tkinter 是逻辑像素，需要换算
                ratio = (pw / float(sw)) if sw else 1.0
                return (
                    int(rect.left / ratio),
                    int(rect.top / ratio),
                    int((rect.right - rect.left) / ratio),
                    int((rect.bottom - rect.top) / ratio),
                )
        except Exception:
            pass
    return (0, 0, sw, sh)


def run_selftest() -> int:
    samples = ["好", "重", "重庆银行", "行", "靐", "Hello 世界"]
    for s in samples:
        items = analyze(s)
        print(f"{s!r}")
        print("  拼音: ", pinyin_plain(items))
        print("  字对: ", pinyin_pairs(items).replace("\n", " | "))

    print()
    failures = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(name)

    # FR1 过滤
    check("FR1 过滤非中文/非标点", filter_text("Hello 你好 123！") == "你好！",
          repr(filter_text("Hello 你好 123！")))
    items = analyze("Hello 你好 123！")
    check("FR1 只注音中文", "".join(i["char"] for i in items) == "你好！",
          "".join(i["char"] for i in items))
    check("FR1 标点不注音", all(not i["readings"] for i in items if i["char"] == "！"))
    check("FR1 关闭过滤保留原文", filter_text("abc 你好", False) == "abc 你好")

    # US13 主题
    check("US13 5 套主题", len(THEMES) == 5, str(sorted(THEMES)))
    check("US13 默认 Dark+", DEFAULT_CONFIG["theme"] == "dark_plus")
    dark = theme_colors("dark_plus")
    light = theme_colors("light_plus")
    check("US13 深浅两套颜色不同", dark["panel"] != light["panel"])
    custom = theme_colors("dark_plus", "#203040")
    check("US13 背景色覆盖生效", custom["panel"].lower() == "#203040", custom["panel"])
    check("US13 覆盖后其余色自适应", custom["panel_alt"] != dark["panel_alt"])
    check("US13 非法背景色被忽略",
          theme_colors("dark_plus", "not-a-color")["panel"] == dark["panel"])

    # US11 模块
    check("US11 15 个可选模块", len(MODULES) == 15, str(len(MODULES)))
    mods = default_modules()
    check("US11 默认只开手写",
          mods["handwriting"] and sum(1 for v in mods.values() if v) == 1)

    # US15 快捷键
    check("US15 空值即禁用", TriggerKeyListener("", 400, lambda: None).disabled)
    check("US15 已移除抓取热键", "hotkey" not in DEFAULT_CONFIG)
    old = {"schemaVersion": 3, "hotkey": "<ctrl>+<alt>+p", "theme": "dark"}
    new = migrate(dict(old))
    check("US15 migrate 清除 hotkey", "hotkey" not in new)
    check("US13 migrate 主题别名", new["theme"] == "dark_plus", new["theme"])
    check("配置 schemaVersion 升级", new["schemaVersion"] == CONFIG_SCHEMA,
          str(new["schemaVersion"]))
    check("US11 migrate 补齐 modules", isinstance(new.get("modules"), dict)
          and len(new["modules"]) == 15)
    check("US17 配置项存在", DEFAULT_CONFIG["popup_dismiss_on_outside_click"] is True)
    check("US12 手写引擎默认 system", DEFAULT_CONFIG["handwriting_engine"] == "system")

    print("\n配置路径:", config_path())
    cfg = load_config()
    print("schemaVersion:", cfg.get("schemaVersion"),
          "| trigger:", repr(cfg.get("trigger_key")),
          "| theme:", cfg.get("theme"),
          "| modules on:", [k for k, v in (cfg.get("modules") or {}).items() if v])
    print("\n结果:", "全部通过" if not failures else f"{len(failures)} 项未通过 -> {failures}")
    return 0 if not failures else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="汉字拼音浮窗")
    parser.add_argument("--selftest", action="store_true", help="不启动界面，仅测试拼音与配置")
    parser.add_argument("--text", default=None, help="启动时预填的文字")
    parser.add_argument("--hidden", action="store_true", help="启动后只驻留托盘")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()

    enable_dpi_awareness()
    instance = acquire_single_instance()
    if instance is None:
        return 0

    cfg = load_config()
    if args.hidden:
        cfg["start_hidden"] = True
    app = HanziPopup(cfg)
    serve_instance(instance, app)
    if args.text:
        app.set_text(args.text)

    try:
        app.root.mainloop()
    finally:
        try:
            instance.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
