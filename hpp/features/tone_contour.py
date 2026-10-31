# -*- coding: utf-8 -*-
"""声调五度图：把每个字的调值画成 1–5 度的折线。

赵元任的五度标记法里，调值用两个到三个数字表示相对音高（5 最高、1 最低）：

    阴平 55 · 阳平 35 · 上声 214 · 去声 51 · 轻声记为 33

这是 S4 的第二个 Feature，也是第一个带内嵌面板的模块——用来验证
`panel()` / `annotate()` / `on_text()` / `settings_spec()` 四个挂点都能用。
"""
from __future__ import annotations

import tkinter as tk

from .base import Feature

# 调值：每个数字是五度标记法里的一度
TONE_CONTOURS = {
    1: (5, 5),          # 阴平
    2: (3, 5),          # 阳平
    3: (2, 1, 4),       # 上声（先降后升）
    4: (5, 1),          # 去声
    0: (3, 3),          # 轻声：记作中平
}

# 带调符号 → 调类。拼音里的调号只会出现在元音上，逐字扫一遍就够。
_TONE_MARKS = {
    1: "āēīōūǖĀĒĪŌŪǕ",
    2: "áéíóúǘÁÉÍÓÚǗ",
    3: "ǎěǐǒǔǚǍĚǏǑǓǙ",
    4: "àèìòùǜÀÈÌÒÙǛ",
}


def tone_number(reading: str) -> int:
    """从一个音节里读出声调（0 = 轻声/读不出来）。

    兼容两种写法：带调符号（`shì`）和数字后缀（`shi4`）。
    """
    if not reading:
        return 0
    tail = reading[-1]
    if tail.isdigit():
        value = int(tail)
        return value if 1 <= value <= 4 else 0
    for tone, marks in _TONE_MARKS.items():
        for mark in marks:
            if mark in reading:
                return tone
    return 0


class ToneContourPanel:
    """一条横向的调值曲线带：每个字一格，上面是字，下面是它的调值折线。"""

    CELL_W = 44
    GAP = 2
    LABEL_H = 16

    def __init__(self, app, parent):
        self.app = app
        self.colors = app.colors
        self.frame = tk.Frame(parent, bg=self.colors["panel"])
        self.canvas = tk.Canvas(
            self.frame, bg=self.colors["panel"], highlightthickness=0, bd=0, height=0,
        )
        self.canvas.pack(fill="x")

    def height(self) -> int:
        raw = self.app.cfg.get("tone_contour_scale", 54)
        try:
            return max(36, min(90, int(raw)))
        except (TypeError, ValueError):
            return 54

    def _y_of(self, level: float, top: int, bottom: int) -> float:
        """五度 → 像素。1 度贴底，5 度贴顶。"""
        return bottom - (level - 1) * (bottom - top) / 4.0

    def update(self, items: list) -> None:
        cv = self.canvas
        cv.delete("all")
        cells = [it for it in (items or []) if str(it.get("char", "")).strip()]
        cells = cells[:12]          # 再多窗口也放不下，只画前 12 个
        if not cells:
            cv.configure(height=0)
            return

        height = self.height()
        cv.configure(height=height)
        c = self.colors
        top = self.LABEL_H + 2
        bottom = height - 4

        for idx, it in enumerate(cells):
            x0 = idx * (self.CELL_W + self.GAP)
            x1 = x0 + self.CELL_W
            cx = (x0 + x1) / 2

            cv.create_text(cx, 1, text=it["char"], anchor="n",
                           fill=c["fg"], font=self.app.font_hint)

            tone = int(it.get("tone", 0) or 0)
            levels = TONE_CONTOURS.get(tone)
            if not levels:
                # 没有读音的字（标点、拉丁字母）只留个占位短线
                cv.create_line(x0 + 12, self._y_of(3, top, bottom),
                               x1 - 12, self._y_of(3, top, bottom),
                               fill=c["border"], width=1)
                continue

            # 五度参考线：浅浅地铺一层，方便看出高低
            for level in range(1, 6):
                y = self._y_of(level, top, bottom)
                cv.create_line(x0 + 4, y, x1 - 4, y, fill=c["border"], width=1)

            points = []
            span = len(levels) - 1 or 1
            for i, level in enumerate(levels):
                px = x0 + 8 + (x1 - x0 - 16) * (i / span if span else 0)
                points.extend([px, self._y_of(level, top, bottom)])
            if len(points) >= 4:
                cv.create_line(*points, fill=c["accent"], width=2,
                               capstyle="round", joinstyle="round", smooth=False)
            for i in range(0, len(points), 2):
                r = 2
                cv.create_oval(points[i] - r, points[i + 1] - r,
                               points[i] + r, points[i + 1] + r,
                               fill=c["accent"], outline=c["accent"])


class ToneContourFeature(Feature):
    key = "tone_contour"
    label = "声调五度图"

    def __init__(self) -> None:
        super().__init__()
        self.panel_widget = None

    def panel(self, parent):
        self.panel_widget = ToneContourPanel(self.app, parent)
        return self.panel_widget.frame

    def annotate(self, items: list) -> list:
        for it in items:
            readings = it.get("readings") or []
            it["tone"] = tone_number(readings[0]) if readings else 0
        return items

    def on_text(self, text: str, items: list) -> None:
        if self.panel_widget is not None:
            self.panel_widget.update(items)

    def settings_spec(self) -> list:
        return [
            {
                "key": "tone_contour_scale",
                "label": "五度图高度",
                "type": "int",
                "min": 36,
                "max": 90,
                "step": 4,
                "suffix": "px",
                "default": 54,
                "hint": "调值曲线占的高度；字调小的时候可以跟着调小，省出正文空间",
            },
        ]

    def self_check(self) -> list:
        return [
            ("五度表覆盖 5 种声调", len(TONE_CONTOURS) == 5, sorted(TONE_CONTOURS)),
            ("阴平 shì 判四声", tone_number("shì") == 4, "shì"),
            ("阳平 má 判二声", tone_number("má") == 2, "má"),
            ("上声 hǎo 判三声", tone_number("hǎo") == 3, "hǎo"),
            ("去声 mā 判一声", tone_number("mā") == 1, "mā"),
            ("数字调号 shi4 判四声", tone_number("shi4") == 4, "shi4"),
            ("无调号判轻声", tone_number("de") == 0, "de"),
        ]


FEATURE = ToneContourFeature
