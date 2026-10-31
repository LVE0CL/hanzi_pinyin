#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汉字拼音浮窗 · Hanzi Pinyin Popup  v1.2.2
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

v1.2.1 修复：
    · 双击 exe 后主窗口不出现（start_hidden 残留 + 裸 deiconify 不渲染）
      → 手动启动一律显示主窗口，--hidden 才驻留托盘；启动后 0.9 s 兜底再拉一次

v1.2.2 修复：
    · 首启引导页 15 项一次铺开，「开始使用」被挤出窗口点不到
      → 改成 7 项一页、左右翻页；新增 × / Esc 关闭，退出即用默认配置
    · 输入框左侧被占位提示遮挡，点不进去、选不中、打不了字
      → 占位提示点击即把焦点交给输入框
    · 选中双击 Shift 弹的是固定内容而非选中文字
      → Shift 未松开时发出的其实是 Ctrl+Shift+C（复制失败后读到旧剪贴板）；
        改为先等修饰键松开、剪贴板无变化不再冒充选区、焦点在自己身上直接跳过

v1.3.0 重构 S1：
    · 叶子模块搬到 hpp/（constants / modules / config / theme / pinyin /
      icons / speech / selection / clipboard / hotkeys），本文件暂留 UI 与编排

v1.3.0 重构 S2：
    · UI 组件搬到 hpp/ui/（ruby_view / mini_popup / handwriting /
      first_run / settings）与 hpp/paths.py，外壳只剩主窗口与装配

许可证：MIT
"""

from __future__ import annotations

import argparse
import os
import platform
import queue
import socket
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:  # pragma: no cover
    sys.exit(
        "当前 Python 没有 tkinter，请安装带 tkinter 的官方 Python：\n"
        "  https://www.python.org/downloads/"
    )

try:
    from PIL import ImageTk
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 Pillow，请先执行：pip install -r requirements.txt")

# ---- 以下均为 hpp 包内的模块（S1/S2 已迁出，此处仅做导入）-------------
from hpp.clipboard import (
    grab_selection,
    read_clipboard,
    set_clip_widget,
    write_clipboard,
)
from hpp.config import (
    DEFAULT_CONFIG,
    config_path,
    load_config,
    migrate,
    save_config,
)
from hpp.constants import (
    APP_NAME,
    APP_TITLE,
    CONFIG_SCHEMA,
    HANZI_RE,
    VERSION,
    single_instance_port,
)
from hpp.hotkeys import MouseDoubleClickListener, TriggerKeyListener
from hpp.features import (
    annotate_all,
    attach_all,
    build_panels,
    collect_self_checks,
    load_features,
    notify_text,
)
from hpp.icons import make_app_image
from hpp.modules import MODULES, default_modules
from hpp.pinyin import analyze, filter_text, pinyin_pairs, pinyin_plain
from hpp.selection import (
    TEXT_CONTROL_TYPES,
    control_type_at,
    cursor_position,
    pressed_modifiers,
    read_selection_uia,
)
from hpp.speech import Speech, list_sapi_voices
from hpp.theme import (
    THEMES,
    TRIGGER_LABELS,
    normalize_theme,
    theme_colors,
)
from hpp.ui import (
    PLACEHOLDER,
    BottomBar,
    FirstRunWindow,
    HandwritingPad,
    MiniPopup,
    ResizeZones,
    RubyView,
    SettingsWindow,
    TitleBar,
)





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

        set_clip_widget(self.root)
        # 记下自己的顶层窗口句柄：读选区时要判断前台是不是自己
        try:
            self._hwnd = int(self.root.winfo_id())
        except Exception:
            self._hwnd = 0

        self.root.title(APP_TITLE)
        self.root.overrideredirect(True)
        self.root.configure(bg=self.colors["panel"])
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))

        self._set_window_icon()
        self._build_fonts()
        # 功能模块要在建界面之前就位：面板是界面的一部分
        self._load_features()
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
            # 用 show() 而不是裸 deiconify()：它带 lift()/topmost 重设，
            # 无边框窗口在部分 Windows + Tk 组合下只有 deiconify 会"存在但不渲染"
            self.show()
            self.root.after(900, self._ensure_visible)

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
    # ---------------- 布局 ----------------
    def _build_ui(self) -> None:
        c = self.colors
        self.outer = tk.Frame(
            self.root, bg=c["panel"], highlightthickness=1,
            highlightbackground=c["border"], highlightcolor=c["border"],
        )
        self.outer.pack(fill="both", expand=True)

        # ---- 标题栏（自带拖动与复制/朗读/图钉/最小化/最大化/关闭）----
        self.titlebar = TitleBar(self, self.outer)

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
            font=self.font_entry, anchor="w", cursor="xterm",
        )
        self.placeholder.place(x=10, rely=0.5, anchor="w")
        # 叠在上面的 Label 会吞掉点击：不把焦点交回去，用户点左侧大半区域
        # 既选不中文字也打不了字。
        self.placeholder.bind("<Button-1>", self._placeholder_click)
        self.placeholder.bind("<B1-Motion>", self._placeholder_click)

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

        # ---- 功能模块的内嵌面板（S4）：一个都没有时整块不占位置 ----
        self.feature_host = tk.Frame(self.outer, bg=c["panel"])
        self.feature_panels = build_panels(self.features, self.feature_host)
        if self.feature_panels:
            self.feature_host.pack(fill="x", padx=12, pady=(0, 4))

        # ---- 底部：提示 + 手写入口 + 设置齿轮 ----
        self.bottom = BottomBar(self, self.outer)
        self.bottom.set_default(self._hint_text())

        self._build_menu()
        for w in (self.outer, self.bottom.hint, self.multi):
            w.bind("<Button-3>", self._popup_menu)

        # ---- US5：8 向缩放热区（浮在最上层，只占几像素边缘）----
        self.zones = ResizeZones(self, self.outer)

    def _build_menu(self) -> None:
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

    # ---------------- 功能模块（S4）----------------
    def _load_features(self) -> None:
        """按当前模块开关重新加载功能模块（设置里改开关后要重来一遍）。"""
        self.features = load_features(self.cfg)
        attach_all(self.features, self)

    def reload_features(self) -> None:
        """给外部（首启引导 / 设置窗口）用：开关变了，重载模块并重画界面。"""
        self._load_features()
        self.rebuild_ui()

    # ---------------- 兼容属性 ----------------
    # 主窗口重画后控件对象会换新的，用属性取而不是缓存引用，
    # 外部（含验收脚本）按这些名字拿到的永远是当前这一份。
    @property
    def bar(self):
        return self.titlebar.bar

    @property
    def btn_pin(self):
        return self.titlebar.btn_pin

    @property
    def btn_settings(self):
        return self.bottom.btn_settings

    @property
    def btn_hand(self):
        return self.bottom.btn_hand



    def _hint_text(self) -> str:
        key = self.cfg.get("trigger_key", "ctrl")
        if not key:
            return "选中文字双击弹浮窗 · Esc 隐藏 · Ctrl+Enter 朗读"
        label = TRIGGER_LABELS.get(key, "Ctrl")
        return f"双击 {label} 唤起 · Esc 隐藏 · Ctrl+Enter 朗读"


    def module_enabled(self, key: str) -> bool:
        """US11：模块开关统一从这里读，未启用的模块不显示入口。"""
        mods = self.cfg.get("modules") or {}
        return bool(mods.get(key, False))


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

    def _placeholder_click(self, _event=None) -> str:
        """点占位提示＝点输入框：交出焦点并让提示消失。"""
        self._focus_entry()
        self._sync_placeholder()
        return "break"


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
        # S4：模块先给每个字补信息（比如声调数字），再交给注音视图画
        items = annotate_all(self.features, items)
        self.ruby_view.set_items(items)

        multi_lines = [
            f"{it['char']}  " + " / ".join(it["readings"])
            for it in items if len(it["readings"]) > 1
        ]
        self.multi.configure(text="　".join(multi_lines[:3]) if multi_lines else "")
        self._update_geometry()
        # 渲染完再通知面板，此时几何已经算好，面板可以按需改动高度
        notify_text(self.features, text, items)

    def _update_geometry(self) -> None:
        if self._maximized:
            wx, wy, ww, wh = work_area(self.root)
            # 标题栏 + 输入框 + 多音字 + 底部，再算上功能模块面板的高度
            chrome = 34 + 46 + 26 + 34
            if self.feature_panels:
                chrome += self.feature_host.winfo_reqheight()
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
        self.bottom.flash(msg)

    def toggle_topmost(self) -> None:
        new = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", new)
        self.cfg["always_on_top"] = new
        save_config(self.cfg)
        self.titlebar.refresh_pin()
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

    def _ensure_visible(self) -> None:
        """兜底：启动后若窗口其实没被渲染出来，再拉一次。

        某些 Windows/Tk 组合下无边框窗口会出现"窗口对象存在、屏幕上看不到"，
        用户双击图标后什么都看不到就会以为程序没启动。
        """
        if self._closing or self._hidden:
            return
        try:
            if not self.root.winfo_viewable():
                self.show()
        except Exception:
            pass

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
        self.zones.sync()   # US5：最大化时禁用拖动改大小

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
            self.bottom.cancel()
        except Exception:
            pass
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

        def worker():
            # 第二下功能键按下时手还没松：此刻若立刻发 Ctrl+C，
            # 系统收到的是 Ctrl+Shift+C（多数程序里不是复制），
            # 复制没成功就会把剪贴板里的旧内容当选区——表现为
            # 「每次都弹同一段固定文字」。所以先等修饰键松开。
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline and pressed_modifiers():
                time.sleep(0.02)
            time.sleep(0.08)
            x, y = cursor_position()
            self._read_selection_and_pop(x, y)

        threading.Thread(target=worker, daemon=True).start()

    def _foreground_is_mine(self) -> bool:
        """前台窗口是不是自己——自己身上只可能读到自己输入框里的字。"""
        if platform.system() != "Windows" or not self._hwnd:
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # winfo_id() 给的是子窗口句柄，要取根祖先才能和 GetForegroundWindow 比
            mine = int(user32.GetAncestor(ctypes.c_void_p(self._hwnd), 2) or 0)  # GA_ROOT
            fg = int(user32.GetForegroundWindow() or 0)
            # 任一为 0（获取失败）都必须判 False：0 == 0 会误判成"是我"，
            # 那样会把所有外部选区都挡掉。
            if not mine or not fg:
                return False
            return mine == fg
        except Exception:
            return False

    def _read_selection_and_pop(self, x: int, y: int) -> None:
        if self._foreground_is_mine():
            return
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
        old_modules = dict(self.cfg.get("modules") or {})

        self.cfg.update(values)
        self.cfg["schemaVersion"] = CONFIG_SCHEMA
        save_config(self.cfg)

        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self.titlebar.refresh_pin()

        # 模块开关变了：重载功能模块并整体重绘（新模块的面板/入口要出现或消失）
        if (self.cfg.get("modules") or {}) != old_modules:
            self.reload_features()
            return

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
            self.zones.layout()
            self.zones.sync()

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

        self.bottom.set_default(self._hint_text())
        # 模块自己的设置项（比如五度图高度）也要立刻生效
        self.refresh()
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
        self.zones.sync()
        self.bottom.set_default(self._hint_text())
        self._flash_hint("主题已应用")

    def _restyle_widgets(self) -> None:
        self.titlebar.restyle()
        self.bottom.restyle()
        self.entry.configure(font=self.font_entry)
        self.multi.configure(font=(self.cn_font, 9))







# --------------------------------------------------------------------------
# 单实例
# --------------------------------------------------------------------------
def acquire_single_instance():
    port = single_instance_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return sock
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as conn:
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

    # S4：功能模块自检。这里把所有「已实现」的模块都加载一遍（含没勾上的），
    # 否则自检会漏掉用户暂时关掉的代码。
    cfg = load_config()
    feats = load_features(cfg, include_disabled=True)
    check("S4 已实现模块可加载", len(feats) >= 2, str(sorted(feats)))
    for name, ok, detail in collect_self_checks(feats):
        check(name, ok, detail)

    print("\n配置路径:", config_path())
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
    parser.add_argument(
        "--config-dir", default=None, metavar="DIR",
        help="把配置读写放到指定目录（多实例/并行开发调试用）",
    )
    args = parser.parse_args(argv)

    # 必须在任何 load_config() 之前生效
    if args.config_dir:
        os.environ["HPP_CONFIG_DIR"] = os.path.abspath(args.config_dir)

    if args.selftest:
        return run_selftest()

    enable_dpi_awareness()
    instance = acquire_single_instance()
    if instance is None:
        return 0

    cfg = load_config()
    if args.hidden:
        cfg["start_hidden"] = True
    else:
        # 手动双击启动（没带 --hidden）一律显示主窗口。
        # 否则用户点了图标屏幕上什么都没有，只会以为"程序打不开"。
        cfg["start_hidden"] = False
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
