# -*- coding: utf-8 -*-
"""US7 迷你浮窗：贴着光标弹出、可拖动 / 固定 / 超时淡出。"""

from __future__ import annotations

import sys
import time
import tkinter as tk

from ..clipboard import write_clipboard
from ..pinyin import analyze, pinyin_pairs, pinyin_plain
from .common import _release_grab
from .ruby_view import RubyView


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
