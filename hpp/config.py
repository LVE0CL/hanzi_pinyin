"""配置：默认值、路径、迁移、读写。

配置结构变更必须 +1 CONFIG_SCHEMA（constants 里）并在此补 migrate 分支。
"""
from __future__ import annotations

import json
import os
import platform
import sys

from .constants import APP_NAME, CONFIG_SCHEMA
from .modules import default_modules
from .theme import normalize_theme

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




# --------------------------------------------------------------------------
# 配置文件：读取 / 迁移 / 原子写入
# --------------------------------------------------------------------------
def config_path() -> str:
    # 开发期隔离：HPP_CONFIG_DIR 指到一个目录，这个实例就只读写那份配置。
    # 多人/多实例并行调试时靠它，免得互相把对方的模块开关冲掉。
    override = os.environ.get("HPP_CONFIG_DIR")
    if override:
        return os.path.join(os.path.abspath(override), "config.json")
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
