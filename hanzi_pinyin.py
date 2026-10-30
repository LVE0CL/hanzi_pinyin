#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
汉字拼音浮窗 · Hanzi Pinyin Popup  v1.0.1
=========================================

一个常驻托盘的小浮窗：在任何地方写/打出汉字，立刻看到拼音（多音字全列）、
能朗读、能复制。

v1.0.0 迭代新增：
    · 系统托盘常驻（首页 / 设置 / 退出）
    · 双击 Ctrl 唤起首页（触发键与间隔可配置）
    · 自定义标题栏：× 退出、□ 最大化、− 隐藏到托盘，标题栏可拖动
    · 统一设置界面（通用 / 快捷键 / 功能模块 / 关于），配置带 schemaVersion

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
VERSION = "1.0.1"
CONFIG_SCHEMA = 2
SINGLE_INSTANCE_PORT = 47653
PROJECT_URL = "https://github.com/<your-name>/hanzi-pinyin-popup"

# --------------------------------------------------------------------------
# 配置模型
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "schemaVersion": CONFIG_SCHEMA,
    # 通用
    "start_hidden": False,        # 启动时只驻留托盘
    "always_on_top": True,        # 窗口置顶
    "language": "zh-CN",          # 预留：界面语言
    # 快捷键
    "trigger_key": "ctrl",        # 双击唤起的按键
    "double_click_ms": 400,       # 双击判定间隔
    "hotkey": "<ctrl>+<alt>+p",   # 抓取选中文字 / 唤出
    "quit_hotkey": "<ctrl>+<alt>+q",
    # 功能模块
    "auto_clipboard": False,      # 剪贴板出现汉字时自动显示
    "font_size": 32,              # 汉字字号（点）
    "speech_rate": 0,             # 语速 -10 ~ 10
    "theme": "dark",              # dark / light（切换后需重启）
    # 运行时状态（不算「设置」，但一起持久化）
    "window_width": 420,
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
                "hint": "浮窗始终显示在其他窗口之上",
            },
            {
                "key": "language",
                "label": "界面语言",
                "type": "choice",
                "choices": [("简体中文", "zh-CN")],
                "readonly": True,
                "hint": "多语言为后续版本预留",
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
                ],
                "hint": "连续按两下该键即可唤起首页（现阶段只支持单键）",
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
                "key": "hotkey",
                "label": "抓取选中文字",
                "type": "choice",
                "choices": [
                    ("Ctrl + Alt + P", "<ctrl>+<alt>+p"),
                    ("Ctrl + Shift + P", "<ctrl>+<shift>+p"),
                    ("Alt + Shift + P", "<alt>+<shift>+p"),
                ],
                "hint": "选中文字后按此组合键，浮窗会读取选区并显示拼音",
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
                "key": "theme",
                "label": "界面主题",
                "type": "choice",
                "choices": [("深色", "dark"), ("浅色", "light")],
                "hint": "切换后需重启程序生效",
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

THEMES = {
    "dark": {
        "panel": "#1e2126",
        "panel_alt": "#262a31",
        "border": "#3a4048",
        "fg": "#e8eaed",
        "fg_dim": "#8b939e",
        "accent": "#7fd1a0",
        "hover": "#2f353d",
        "entry_bg": "#171a1e",
        "danger": "#e07070",
        "scroll": "#4a515b",
    },
    "light": {
        "panel": "#ffffff",
        "panel_alt": "#f4f5f7",
        "border": "#d8dbe1",
        "fg": "#1f2328",
        "fg_dim": "#767e89",
        "accent": "#0a7d4f",
        "hover": "#e9ecf1",
        "entry_bg": "#f7f8fa",
        "danger": "#c0392b",
        "scroll": "#c7ccd4",
    },
}


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
    if version < 2:
        # v1 → v2：新增托盘 / 双击唤起相关字段，旧字段名保持不变
        cfg.setdefault("start_hidden", DEFAULT_CONFIG["start_hidden"])
        cfg.setdefault("trigger_key", DEFAULT_CONFIG["trigger_key"])
        cfg.setdefault("double_click_ms", DEFAULT_CONFIG["double_click_ms"])
        version = 2
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


def analyze(text: str) -> list:
    """把一段文字拆成 [{char, readings}]，非汉字（连续的一段）合并为一项。

    readings[0] 是**结合上下文**得到的主读音（"重庆"的"重"读 chóng），
    后面跟的是该字的其他常见读音（多音字）。
    """
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
class Speech:
    """优先用 Windows 自带的 System.Speech（常驻进程，延迟低）；其他平台走系统命令。"""

    def __init__(self, rate: int = 0):
        self.rate = max(-10, min(10, int(rate)))
        self.system = platform.system()
        self._proc = None
        self._lock = threading.Lock()
        self._shell = None

    def set_rate(self, rate: int) -> None:
        rate = max(-10, min(10, int(rate)))
        if rate != self.rate:
            self.rate = rate
            self.close()  # 下次说话时按新语速重建

    def _shell_candidates(self):
        return [self._shell] if self._shell else ["powershell", "pwsh"]

    def _ensure_windows(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate = {self.rate};"
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
                    ps = (
                        "Add-Type -AssemblyName System.Speech;"
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                        f"$s.Rate = {self.rate};"
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
                    subprocess.run(["say", text], timeout=30)
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
# 全局键监听：双击触发
# --------------------------------------------------------------------------
class TriggerKeyListener:
    """监听「双击某个键」触发回调。现阶段只支持单键。"""

    SUPPORTED = ["ctrl", "alt", "shift", "space", "tab", "caps_lock"] + [
        f"f{i}" for i in range(1, 13)
    ]

    def __init__(self, key: str, interval_ms: int, callback):
        self.key = key if key in self.SUPPORTED else "ctrl"
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


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------
PLACEHOLDER = "在这里写字，或按 Ctrl+Alt+P 抓取选区"


class HanziPopup:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.colors = THEMES.get(cfg.get("theme", "dark"), THEMES["dark"])
        self.font_size = int(cfg.get("font_size", 32))
        self.width = int(cfg.get("window_width", 420))
        self._rows = []
        self._refresh_job = None
        self._maximized = False
        self._restore_geo = ""
        self._drag_origin = (0, 0)
        self._settings_win = None
        self._tray = None
        self._hidden = False
        self._clip_stop = None
        self._trigger = None
        self._hotkeys = None
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

        self.speech = Speech(cfg.get("speech_rate", 0))
        self._place_window()

        # 托盘 → 双击触发键 → 热键（失败都有兜底）
        self.tray_ok = self._start_tray()
        self._start_trigger()
        self._start_hotkeys()
        if cfg.get("auto_clipboard"):
            self._start_clipboard_watch()

        if cfg.get("start_hidden") and self.tray_ok:
            self._hidden = True
            self.root.withdraw()
        else:
            self.refresh()
            self.root.deiconify()

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

        self.btn_copy = self._title_button(self.bar, "复制", self.copy_pinyin)
        self.btn_copy.pack(side="right", padx=(2, 10))
        self.btn_speak = self._title_button(self.bar, "朗读", self.speak_current)
        self.btn_speak.pack(side="right", padx=2)

        for w in (self.bar, self.title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
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

        # ---- 右键菜单 ----
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="设置…", command=self.open_settings)
        self.menu.add_command(label="复制「字 + 拼音」", command=self.copy_pairs)
        self.menu.add_command(label="朗读", command=self.speak_current)
        self.menu.add_separator()
        self.menu.add_command(label="切换置顶", command=self.toggle_topmost)
        self.menu.add_command(label="隐藏到托盘", command=self.hide_to_tray)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

        for w in (self.outer, self.hint, self.multi):
            w.bind("<Button-3>", self._popup_menu)

    def _hint_text(self) -> str:
        key = TRIGGER_LABELS.get(self.cfg.get("trigger_key", "ctrl"), "Ctrl")
        return f"双击 {key} 唤起 · Esc 隐藏 · Ctrl+Enter 朗读"

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

    def _do_drag(self, event) -> None:
        if self._maximized:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

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
        cw = self.font_char.measure("国") + 16
        ch = self.font_char.metrics("linespace") + self.font_pinyin.metrics("linespace") + 10
        return cw, ch

    def _item_width(self, it: dict) -> int:
        if it["readings"]:
            return self._cell_metrics()[0]
        ch = it["char"]
        if not ch.strip():
            return 10
        return max(24, self.font_latin.measure(ch) + 10)

    def render_text(self, text: str) -> None:
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self.canvas.yview_moveto(0)

        items = analyze(text)
        if not items:
            self.multi.configure(text="")
            self._update_geometry()
            return

        c = self.colors
        content_w = max(160, self._current_width() - 36)
        cell_h = self._cell_metrics()[1]

        rows_items = []
        cur = []
        cur_w = 0
        for it in items:
            w = self._item_width(it)
            if cur and cur_w + w > content_w:
                rows_items.append(cur)
                cur, cur_w = [], 0
            cur.append((it, w))
            cur_w += w
        if cur:
            rows_items.append(cur)

        multi_lines = [
            f"{it['char']}  " + " / ".join(it["readings"])
            for it in items if len(it["readings"]) > 1
        ]

        for row_items in rows_items:
            row = tk.Frame(self.ruby, bg=c["panel"])
            row.pack(anchor="center")
            self._rows.append(row)
            for it, w in row_items:
                cell = tk.Frame(row, bg=c["panel"], width=w, height=cell_h)
                cell.pack(side="left", padx=2)
                cell.pack_propagate(False)
                if not it["char"].strip():
                    continue
                if it["readings"]:
                    tk.Label(cell, text=it["readings"][0], bg=c["panel"],
                             fg=c["accent"], font=self.font_pinyin).place(
                        relx=0.5, y=1, anchor="n")
                    tk.Label(cell, text=it["char"], bg=c["panel"],
                             fg=c["fg"], font=self.font_char).place(
                        relx=0.5, rely=1.0, y=-1, anchor="s")
                else:
                    tk.Label(cell, text=it["char"], bg=c["panel"],
                             fg=c["fg_dim"], font=self.font_latin).place(
                        relx=0.5, rely=0.58, anchor="center")

        self.multi.configure(text="　".join(multi_lines[:3]))
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

        height = max(168, self.outer.winfo_reqheight())
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if x <= 0 or y <= 0:
            x, y = 120, 120
        self.root.geometry(f"{self.width}x{height}+{x}+{y}")

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
        self.root.geometry(f"{self.width}x240+{x}+{y}")

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
        if not self._maximized:
            self.cfg["position"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.cfg)
        self._hidden = True
        self.root.withdraw()

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
        try:
            if not self._maximized:
                self.cfg["position"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.cfg)
        except Exception:
            pass
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
                pystray.MenuItem("设置", later(self.open_settings)),
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
            lambda: self.post(self.show),
        )
        self._trigger.start()

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

        def on_grab():
            text = self._grab_selection()
            self.post(self.show, text or None)

        def on_quit():
            self.post(self.quit)

        try:
            self._hotkeys = keyboard.GlobalHotKeys({
                self.cfg.get("hotkey", DEFAULT_CONFIG["hotkey"]): on_grab,
                self.cfg.get("quit_hotkey", DEFAULT_CONFIG["quit_hotkey"]): on_quit,
            })
            self._hotkeys.daemon = True
            self._hotkeys.start()
        except Exception as exc:
            print(f"[warn] 注册热键失败：{exc}", file=sys.stderr)
            self._hotkeys = None

    def _grab_selection(self) -> str:
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
        return read_clipboard() or old

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
                        self.post(self.show, stripped)

        threading.Thread(target=worker, daemon=True).start()

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

    def apply_settings(self, values: dict) -> None:
        old_theme = self.cfg.get("theme")
        old_font = int(self.cfg.get("font_size", 32))

        self.cfg.update(values)
        self.cfg["schemaVersion"] = CONFIG_SCHEMA
        save_config(self.cfg)

        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))

        if int(self.cfg.get("font_size", 32)) != old_font:
            self.font_size = int(self.cfg["font_size"])
            self._build_fonts()
            self._restyle_widgets()
            self.refresh()

        self.speech.set_rate(int(self.cfg.get("speech_rate", 0)))

        if self.cfg.get("auto_clipboard"):
            self._start_clipboard_watch()
        elif self._clip_stop is not None:
            self._clip_stop.set()
            self._clip_stop = None

        self._start_trigger()
        self._start_hotkeys()

        self.hint.configure(text=self._hint_text())
        if old_theme != self.cfg.get("theme"):
            self._flash_hint("主题将在重启后生效")
        else:
            self._flash_hint("设置已保存")

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

        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._do_drag)

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

        # 右侧内容
        self.content = tk.Frame(body, bg=c["panel"])
        self.content.pack(side="left", fill="both", expand=True, padx=18, pady=14)

        for group in SETTING_GROUPS:
            self.pages[group["key"]] = self._build_group_page(group)
        self.pages["about"] = self._build_about_page()

        self._show_page(self.current)

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
        self.pages[key].pack(fill="both", expand=True)

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
    def _build_group_page(self, group: dict) -> tk.Frame:
        c = self.colors
        page = tk.Frame(self.content, bg=c["panel"])
        tk.Label(page, text=group["title"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        for item in group["items"]:
            self._build_item(page, item)
        return page

    def _build_item(self, parent, item: dict) -> None:
        c = self.colors
        row = tk.Frame(parent, bg=c["panel"])
        row.pack(fill="x")

        tk.Label(row, text=item["label"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 10), anchor="w", width=15).pack(side="left")

        key = item["key"]
        default = DEFAULT_CONFIG.get(key)
        kind = item["type"]

        if kind == "bool":
            var = tk.BooleanVar(value=bool(self.cfg.get(key, default)))
            chk = tk.Checkbutton(
                row, text="启用", variable=var, bg=c["panel"], fg=c["fg_dim"],
                selectcolor=c["panel_alt"], activebackground=c["panel"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2",
            )
            chk.pack(side="left")
            self.vars[key] = var
        elif kind == "int":
            var = tk.StringVar(value=str(self.cfg.get(key, default)))
            tk.Spinbox(
                row, from_=item["min"], to=item["max"], increment=item.get("step", 1),
                textvariable=var, width=6, bg=c["entry_bg"], fg=c["fg"],
                buttonbackground=c["panel_alt"], relief="flat",
                insertbackground=c["fg"], font=(self.app.cn_font, 10),
                highlightthickness=0, bd=0,
            ).pack(side="left")
            if item.get("suffix"):
                tk.Label(row, text=item["suffix"], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 9)).pack(side="left", padx=(4, 0))
            self.vars[key] = var
        elif kind == "choice":
            choices = item["choices"]
            current = self.cfg.get(key, default)
            if item.get("readonly"):
                tk.Label(row, text=choices[0][0], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 10)).pack(side="left")
                self.vars[key] = tk.StringVar(value=current)
            else:
                label = next((lb for lb, val in choices if val == current), choices[0][0])
                var = tk.StringVar(value=label)
                self._dropdown(row, var, choices)
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
                 "双击触发键唤起 · Esc 隐藏 · Ctrl+Alt+P 抓取选区 · Ctrl+Enter 朗读",
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

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _center(self) -> None:
        w, h = 640, 470
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
                elif item["type"] == "choice" and not item.get("readonly"):
                    label = next((lb for lb, val in item["choices"] if val == default),
                                 item["choices"][0][0])
                    self.vars[key].set(label)
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
        return values

    def save(self) -> None:
        try:
            values = self._collect()
        except ValueError as exc:
            self._set_status(str(exc))
            return

        if values.get("trigger_key") not in TriggerKeyListener.SUPPORTED:
            self._set_status("该按键暂不支持，请换一个")
            return

        if values.get("trigger_key") == "ctrl" and str(
                values.get("hotkey", "")).startswith("<ctrl>"):
            self._set_status("提示：双击 Ctrl 与抓取热键都用到 Ctrl，可能相互干扰")

        self.app.apply_settings(values)
        self.close()

    def close(self) -> None:
        self.alive = False
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
    print("\n配置路径:", config_path())
    cfg = load_config()
    print("schemaVersion:", cfg.get("schemaVersion"),
          "| trigger:", cfg.get("trigger_key"),
          "| theme:", cfg.get("theme"))
    return 0


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
