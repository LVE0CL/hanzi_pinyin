# -*- coding: utf-8 -*-
"""US11 首次启动引导页：15 个可选模块，7 项一页翻着选。"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from ..config import save_config
from ..modules import MODULES, default_modules
from .common import _release_grab

if TYPE_CHECKING:  # pragma: no cover
    # 外壳反过来 import 本模块，运行时真去 import 会成环。
    from hanzi_pinyin import HanziPopup


class FirstRunWindow:
    """US11：首次启动的一次性引导页。

    15 项按 7 项一页分页——一次性全铺出来会把底部按钮挤出窗口（Tk 不裁剪
    子控件），用户看不到「开始使用」就卡在引导页里出不去了。
    """

    PAGE_SIZE = 7
    WIDTH = 520
    HEIGHT = 470

    def __init__(self, app: HanziPopup):
        self.app = app
        self.cfg = app.cfg
        self.colors = app.colors
        self.alive = True
        self.vars = {}
        self.page = 0
        self._drag = (0, 0)
        c = self.colors

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("欢迎使用")
        self.win.configure(bg=c["panel"])
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        mods = self.cfg.get("modules") or {}
        for mod in MODULES:
            self.vars[mod["key"]] = tk.BooleanVar(
                value=bool(mods.get(mod["key"], mod.get("default", False))))
        self.pages = [MODULES[i:i + self.PAGE_SIZE]
                      for i in range(0, len(MODULES), self.PAGE_SIZE)]

        self._build()
        self._center()
        self.win.deiconify()
        self.win.bind("<Escape>", lambda _e: self.close_with_defaults())

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        c = self.colors
        outer = tk.Frame(self.win, bg=c["panel"], highlightthickness=1,
                         highlightbackground=c["border"], highlightcolor=c["border"])
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=c["panel"])
        header.pack(side="top", fill="x", padx=18, pady=(14, 4))
        title = tk.Label(header, text="欢迎使用 汉字拼音浮窗", bg=c["panel"], fg=c["fg"],
                         font=(self.app.cn_font, 13, "bold"), anchor="w")
        title.pack(side="left")
        close = tk.Label(header, text="×", bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 13), padx=8, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self.close_with_defaults())
        close.bind("<Enter>", lambda _e: close.configure(fg=c["danger"]))
        close.bind("<Leave>", lambda _e: close.configure(fg=c["fg_dim"]))

        tk.Label(outer,
                 text="先挑几个想用的功能吧：都是可选项，之后在「设置 → 功能模块」里随时能改。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 9),
                 anchor="w", justify="left", wraplength=460).pack(
                     side="top", fill="x", padx=18)

        for w in (header, title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", lambda _e: _release_grab(self.win))

        # 先 pack 底部两块，再 pack 会 expand 的列表区：顺序反了的话
        # 列表会把按钮顶出窗口边界（Tk 不裁剪子控件，只会让它看不见）。
        footer = tk.Frame(outer, bg=c["panel"])
        footer.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
        tk.Label(footer, text="不选也能用：拼音、朗读、复制、选中双击浮窗都是基础功能。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
                 anchor="w").pack(side="top", fill="x")
        btns = tk.Frame(footer, bg=c["panel"])
        btns.pack(side="top", fill="x", pady=(8, 0))
        start = tk.Label(btns, text="开始使用", bg=c["accent"], fg=c["accent_fg"],
                         font=(self.app.cn_font, 10), padx=18, pady=6, cursor="hand2")
        start.pack(side="right")
        start.bind("<Button-1>", lambda _e: self.confirm())
        none = tk.Label(btns, text="全部不选", bg=c["panel_alt"], fg=c["fg"],
                        font=(self.app.cn_font, 10), padx=14, pady=6, cursor="hand2")
        none.pack(side="right", padx=8)
        none.bind("<Button-1>", lambda _e: self._set_all(False))

        pager = tk.Frame(outer, bg=c["panel"])
        pager.pack(side="bottom", fill="x", padx=18)
        self.btn_prev = tk.Label(pager, text="‹ 上一页", bg=c["panel_alt"], fg=c["fg"],
                                 font=(self.app.cn_font, 9), padx=10, pady=4, cursor="hand2")
        self.btn_prev.pack(side="left")
        self.btn_prev.bind("<Button-1>", lambda _e: self._go(-1))
        self.btn_next = tk.Label(pager, text="下一页 ›", bg=c["panel_alt"], fg=c["fg"],
                                 font=(self.app.cn_font, 9), padx=10, pady=4, cursor="hand2")
        self.btn_next.pack(side="right")
        self.btn_next.bind("<Button-1>", lambda _e: self._go(1))
        self.lbl_page = tk.Label(pager, text="", bg=c["panel"], fg=c["fg_dim"],
                                 font=(self.app.cn_font, 9))
        self.lbl_page.pack(side="left", expand=True)

        self.pagewrap = tk.Frame(outer, bg=c["panel_alt"])
        self.pagewrap.pack(side="top", fill="both", expand=True, padx=18, pady=10)
        self._render_page()

    def _render_page(self) -> None:
        c = self.colors
        for w in self.pagewrap.winfo_children():
            w.destroy()
        for mod in self.pages[self.page]:
            row = tk.Frame(self.pagewrap, bg=c["panel_alt"])
            row.pack(fill="x", padx=10, pady=2)
            tk.Checkbutton(
                row, text=mod["label"], variable=self.vars[mod["key"]],
                bg=c["panel_alt"], fg=c["fg"], selectcolor=c["panel"],
                activebackground=c["panel_alt"], activeforeground=c["fg"],
                font=(self.app.cn_font, 9), highlightthickness=0, bd=0,
                anchor="w", cursor="hand2", width=18,
            ).pack(side="left")
            tk.Label(row, text=mod["hint"], bg=c["panel_alt"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 8), anchor="w").pack(side="left", padx=(4, 0))

        total = len(self.pages)
        self.lbl_page.configure(text=f"第 {self.page + 1} / {total} 页")
        self.btn_prev.configure(fg=c["fg"] if self.page > 0 else c["fg_dim"])
        self.btn_next.configure(fg=c["fg"] if self.page < total - 1 else c["fg_dim"])

    def _go(self, delta: int) -> None:
        # 收敛到合法范围：连点「下一页」或程序里传个 -5 都不该把页码翻出页数
        page = max(0, min(len(self.pages) - 1, self.page + delta))
        if page != self.page:
            self.page = page
            self._render_page()

    def _set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)

    # ---------------- 结束 ----------------
    def confirm(self) -> None:
        if not self.alive:
            return
        self.cfg["modules"] = {k: bool(v.get()) for k, v in self.vars.items()}
        self.cfg["first_run"] = False
        save_config(self.cfg)
        self.close()
        self.app.rebuild_ui()

    def close_with_defaults(self) -> None:
        """× 或 Esc：不保存勾选，回到默认配置并关闭引导。"""
        if not self.alive:
            return
        self.cfg["modules"] = default_modules()
        self.cfg["first_run"] = False
        save_config(self.cfg)
        self.close()
        self.app.rebuild_ui()
        try:
            self.app.show()
        except Exception:
            pass

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
        w, h = self.WIDTH, self.HEIGHT
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
