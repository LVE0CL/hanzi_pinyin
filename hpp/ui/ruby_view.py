# -*- coding: utf-8 -*-
"""拼音注音视图：拼音在上、汉字在下的格子。

主窗口与迷你浮窗共用同一份渲染，避免两套逻辑走偏。
"""

from __future__ import annotations

import tkinter as tk


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
