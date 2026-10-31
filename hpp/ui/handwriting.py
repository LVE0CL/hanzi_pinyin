# -*- coding: utf-8 -*-
"""US12 内置手写板：米字格画布试写，识别交给系统手写引擎。"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from ..paths import handwriting_status, open_system_handwriting
from .common import _release_grab

if TYPE_CHECKING:  # pragma: no cover
    # 外壳反过来 import 本模块，运行时真去 import 会成环。
    from hanzi_pinyin import HanziPopup


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
