# -*- coding: utf-8 -*-
"""主窗口的几块「零件」：标题栏、底部工具条、八向缩放热区。

S3 从 HanziPopup 里整块搬出来的，逻辑一行没改，只是把 `self.xxx` 换成了
`self.app.xxx`。之所以单独成文件：主窗口每次改主题都整体重画，这几块的重画
细节（哪些按钮要换字体、图钉有几种状态、热区怎么重新 place）跟主窗口的业务
逻辑没有关系，混在一起看很累。

约定：零件只读 app 的 cfg / colors / font_*，动作一律回调 app 的公开方法
（quit / toggle_maximize / hide_to_tray / copy_pinyin / speak_current /
toggle_topmost / open_settings / open_handwriting）。
"""
from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

from ..config import save_config
from ..constants import APP_TITLE
from ..icons import make_gear_image, make_pin_image
from .common import _release_grab


class TitleBar:
    """自定义标题栏：标题 + 复制/朗读 + 图钉 + 最小化/最大化/关闭。

    整条栏都能拖动窗口：Tk 把事件先派给最深的控件，所以按钮不会把拖动吃掉。
    """

    HEIGHT = 34

    def __init__(self, app, master):
        self.app = app
        self.colors = app.colors
        c = self.colors
        self._drag_origin = (0, 0)

        self.bar = tk.Frame(master, bg=c["panel"], height=self.HEIGHT)
        self.bar.pack(fill="x", side="top")
        self.bar.pack_propagate(False)

        self.title = tk.Label(self.bar, text=APP_TITLE, bg=c["panel"],
                              fg=c["fg_dim"], font=app.font_ui)
        self.title.pack(side="left", padx=(12, 0))

        self.btn_close = self._button("×", app.quit, danger=True, big=True)
        self.btn_close.pack(side="right", padx=(0, 8))
        self.btn_max = self._button("□", app.toggle_maximize, big=True)
        self.btn_max.pack(side="right", padx=2)
        self.btn_min = self._button("−", app.hide_to_tray, big=True)
        self.btn_min.pack(side="right", padx=2)
        # US14：图钉紧挨在「−」左侧，点击切换始终置顶
        self.btn_pin = self._pin_button()
        self.btn_pin.pack(side="right", padx=(2, 4))

        self.btn_copy = self._button("复制", app.copy_pinyin)
        self.btn_copy.pack(side="right", padx=(2, 10))
        self.btn_speak = self._button("朗读", app.speak_current)
        self.btn_speak.pack(side="right", padx=2)

        for w in (self.bar, self.title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Button-3>", app._popup_menu)

    # ---------------- 按钮 ----------------
    def _button(self, text, cmd, danger=False, big=False) -> tk.Label:
        c = self.colors
        lbl = tk.Label(self.bar, text=text, bg=c["panel"], fg=c["fg_dim"],
                       font=self.app.font_ctrl if big else self.app.font_ui,
                       padx=8, cursor="hand2")
        hover_fg = c["danger"] if danger else c["fg"]
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", lambda _e: lbl.configure(bg=c["hover"], fg=hover_fg))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=c["panel"], fg=c["fg_dim"]))
        return lbl

    def _pin_button(self) -> tk.Label:
        """US14：置顶图钉。钉住 = 实心 + 强调色，松开 = 描边。"""
        c = self.colors
        lbl = tk.Label(self.bar, bg=c["panel"], cursor="hand2", padx=7, pady=2)
        lbl._images = {}
        try:
            for state in ("on", "off", "hover"):
                if state == "on":
                    img = make_pin_image(16, c["accent"], filled=True)
                elif state == "off":
                    img = make_pin_image(16, c["fg_dim"], filled=False)
                else:
                    img = make_pin_image(16, c["fg"], filled=bool(
                        self.app.cfg.get("always_on_top", True)))
                photo = ImageTk.PhotoImage(img)
                lbl._images[state] = photo
                self.app._image_refs.append(photo)
            lbl.configure(image=lbl._images[
                "on" if self.app.cfg.get("always_on_top", True) else "off"])
        except Exception:
            lbl.configure(text="钉", fg=c["fg_dim"], font=self.app.font_ui)
        lbl.bind("<Button-1>", lambda _e: self.app.toggle_topmost())
        lbl.bind("<Enter>", lambda _e: lbl.configure(
            image=lbl._images["hover"], bg=c["hover"]))
        lbl.bind("<Leave>", lambda _e: (lbl.configure(bg=c["panel"]), self.refresh_pin()))
        return lbl

    def refresh_pin(self) -> None:
        lbl = getattr(self, "btn_pin", None)
        if lbl is None:
            return
        images = getattr(lbl, "_images", None) or {}
        key = "on" if self.app.cfg.get("always_on_top", True) else "off"
        if key in images:
            try:
                lbl.configure(image=images[key])
            except Exception:
                pass

    def restyle(self) -> None:
        """字号变了以后只换字体，不重建控件。"""
        self.title.configure(font=self.app.font_ui)
        for w in (self.btn_copy, self.btn_speak):
            w.configure(font=self.app.font_ui)
        for w in (self.btn_close, self.btn_max, self.btn_min):
            w.configure(font=self.app.font_ctrl)

    # ---------------- 拖动 ----------------
    def _start_drag(self, event) -> None:
        if self.app._maximized:
            return
        self._drag_origin = (event.x_root - self.app.root.winfo_x(),
                             event.y_root - self.app.root.winfo_y())
        # 拖动时鼠标很容易跑出标题栏，抓住指针才能持续收到 <B1-Motion>
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        if self.app._maximized:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.app.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event=None) -> None:
        _release_grab(self.app.root)


class BottomBar:
    """底部一行：左边提示语（会临时显示「已复制」之类），右边手写入口 + 设置齿轮。

    提示语的临时文案要能自己收回来，所以「默认文案」和「闪一下」两件事都放在
    这里，主窗口只负责告诉它默认文案是什么。
    """

    def __init__(self, app, master):
        self.app = app
        self.colors = app.colors
        c = self.colors
        self.default_text = ""
        self._hint_job = None

        self.frame = tk.Frame(master, bg=c["panel"])
        self.frame.pack(fill="x", padx=12, pady=(2, 8))

        self.hint = tk.Label(
            self.frame, text="", bg=c["panel"], fg=c["fg_dim"],
            font=app.font_hint, anchor="w",
        )
        self.hint.pack(side="left", padx=(2, 0))

        self.btn_settings = self._gear_button()
        self.btn_settings.pack(side="right", padx=(6, 2))

        # US12：手写入口只在模块开启时出现
        self.btn_hand = None
        self.rebuild_hand_entry()

    def _gear_button(self) -> tk.Label:
        c = self.colors
        try:
            normal = ImageTk.PhotoImage(make_gear_image(18, c["fg_dim"]))
            hover = ImageTk.PhotoImage(make_gear_image(18, c["accent"]))
            self.app._image_refs.extend([normal, hover])
            lbl = tk.Label(self.frame, image=normal, bg=c["panel"], cursor="hand2",
                           padx=4, pady=2)
            lbl.bind("<Enter>", lambda _e: lbl.configure(image=hover, bg=c["hover"]))
            lbl.bind("<Leave>", lambda _e: lbl.configure(image=normal, bg=c["panel"]))
        except Exception:
            lbl = tk.Label(self.frame, text="设置", bg=c["panel"], fg=c["fg_dim"],
                           font=self.app.font_hint, cursor="hand2", padx=6)
            lbl.bind("<Enter>", lambda _e: lbl.configure(fg=c["accent"]))
            lbl.bind("<Leave>", lambda _e: lbl.configure(fg=c["fg_dim"]))
        lbl.bind("<Button-1>", lambda _e: self.app.open_settings())
        return lbl

    def rebuild_hand_entry(self) -> None:
        """手写模块开关变化时重建入口（关掉就彻底不出现）。"""
        if self.btn_hand is not None:
            try:
                self.btn_hand.destroy()
            except Exception:
                pass
            self.btn_hand = None
        if not self.app.module_enabled("handwriting"):
            return
        c = self.colors
        lbl = tk.Label(self.frame, text="手写", bg=c["panel"], fg=c["fg_dim"],
                       font=self.app.font_hint, padx=6, cursor="hand2")
        lbl.pack(side="right", padx=(6, 2))
        lbl.bind("<Button-1>", lambda _e: self.app.open_handwriting())
        lbl.bind("<Enter>", lambda _e: lbl.configure(fg=c["accent"]))
        lbl.bind("<Leave>", lambda _e: lbl.configure(fg=c["fg_dim"]))
        self.btn_hand = lbl

    def set_default(self, text: str) -> None:
        self.default_text = text
        self.hint.configure(text=text, fg=self.colors["fg_dim"])

    def flash(self, msg: str, ms: int = 1400) -> None:
        self.hint.configure(text=msg, fg=self.colors["accent"])
        if self._hint_job is not None:
            try:
                self.app.root.after_cancel(self._hint_job)
            except Exception:
                pass
        self._hint_job = self.app.root.after(ms, self._restore_hint)

    def _restore_hint(self) -> None:
        self._hint_job = None
        try:
            self.hint.configure(text=self.default_text, fg=self.colors["fg_dim"])
        except Exception:
            pass

    def cancel(self) -> None:
        if self._hint_job is not None:
            try:
                self.app.root.after_cancel(self._hint_job)
            except Exception:
                pass
            self._hint_job = None

    def restyle(self) -> None:
        self.hint.configure(font=self.app.font_hint)
        if self.btn_hand is not None:
            self.btn_hand.configure(font=self.app.font_hint)


class ResizeZones:
    """US5：窗口四边/四角的八向拖动热区。

    热区浮在所有控件之上（place 后创建即置顶），但只占几像素边缘，正中间留给
    标题栏拖动和正文点击，两者不冲突。
    """

    CURSORS = {
        "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
        "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
        "nw": "size_nw_se", "se": "size_nw_se",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
    }
    NAMES = ("n", "s", "w", "e", "nw", "ne", "sw", "se")

    def __init__(self, app, master):
        self.app = app
        self.master = master
        self.zones = {}
        self.mode = None
        self.origin = None
        self.build()

    def _pad(self) -> int:
        return max(3, int(self.app.cfg.get("resize_pad", 6)))

    def build(self) -> None:
        pad = self._pad()
        for name in self.NAMES:
            frame = tk.Frame(self.master, bg=self.app.colors["panel"],
                             cursor=self.CURSORS[name])
            frame.bind("<ButtonPress-1>", lambda e, n=name: self._start(e, n))
            frame.bind("<B1-Motion>", self._drag)
            frame.bind("<ButtonRelease-1>", self._end)
            self.zones[name] = (frame, pad)
        self.layout()
        self.sync()

    def layout(self) -> None:
        pad = self._pad()
        # name: (relx, rely, anchor, width, height, x, y)；width/height 为 None 表示拉伸到边
        spec = {
            "n": (0, 0, "nw", None, pad, 0, 0),
            "s": (0, 1, "sw", None, pad, 0, -pad),
            "w": (0, 0, "nw", pad, None, 0, 0),
            "e": (1, 0, "ne", pad, None, 0, 0),
            "nw": (0, 0, "nw", pad * 2, pad * 2, 0, 0),
            "ne": (1, 0, "ne", pad * 2, pad * 2, 0, 0),
            "sw": (0, 1, "sw", pad * 2, pad * 2, 0, 0),
            "se": (1, 1, "se", pad * 2, pad * 2, 0, 0),
        }
        for name, (frame, _old) in self.zones.items():
            relx, rely, anchor, w, h, x, y = spec[name]
            frame.place(
                relx=relx, rely=rely, anchor=anchor, x=x, y=y,
                width=w, height=h,
                relwidth=1.0 if w is None else None,
                relheight=1.0 if h is None else None,
            )
            self.zones[name] = (frame, pad)

    def sync(self) -> None:
        """最大化时或用户关掉缩放时，把热区藏起来。"""
        show = bool(self.app.cfg.get("resize_enabled", True)) and not self.app._maximized
        if show:
            # place_forget 之后必须重新 place 才能回来
            self.layout()
            for frame, _pad in self.zones.values():
                frame.lift()
        else:
            for frame, _pad in self.zones.values():
                frame.place_forget()

    def _start(self, event, name: str) -> None:
        cfg = self.app.cfg
        if self.app._maximized or not cfg.get("resize_enabled", True):
            return
        self.mode = name
        root = self.app.root
        self.origin = (
            event.x_root, event.y_root,
            root.winfo_width(), root.winfo_height(),
            root.winfo_x(), root.winfo_y(),
        )
        # 热区只有几像素宽，抓住指针才能一路跟到松开
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _drag(self, event) -> None:
        if not self.mode or not self.origin:
            return
        cfg = self.app.cfg
        sx, sy, w0, h0, x0, y0 = self.origin
        dx, dy = event.x_root - sx, event.y_root - sy
        min_w = max(160, int(cfg.get("min_width", 320)))
        min_h = max(120, int(cfg.get("min_height", 200)))

        w, h, x, y = w0, h0, x0, y0
        if "e" in self.mode:
            w = max(min_w, w0 + dx)
        if "s" in self.mode:
            h = max(min_h, h0 + dy)
        if "w" in self.mode:
            w = max(min_w, w0 - dx)
            x = x0 + (w0 - w)
        if "n" in self.mode:
            h = max(min_h, h0 - dy)
            y = y0 + (h0 - h)

        self.app.width, self.app.height = int(w), int(h)
        self.app.root.geometry(f"{int(w)}x{int(h)}+{x}+{y}")

    def _end(self, _event=None) -> None:
        if not self.mode:
            _release_grab(self.app.root)
            return
        self.mode = None
        self.origin = None
        _release_grab(self.app.root)
        self.app.cfg["window_width"] = int(self.app.width)
        self.app.cfg["window_height"] = int(self.app.height)
        save_config(self.app.cfg)
        self.app.refresh()
