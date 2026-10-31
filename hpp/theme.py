"""主题与配色：5 套 VS Code 风色板 + 颜色工具。

所有界面颜色都从这里取，禁止在 UI 里硬编码色值。
"""
from __future__ import annotations

from .settings_spec import SETTING_GROUPS

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
