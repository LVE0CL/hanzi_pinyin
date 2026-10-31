# -*- coding: utf-8 -*-
"""设置窗口：左侧分组、右侧表单，全部由 SETTING_GROUPS 声明式驱动。"""

from __future__ import annotations

import os
import platform
import subprocess
import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import TYPE_CHECKING

from PIL import ImageTk

from ..config import DEFAULT_CONFIG, config_path
from ..constants import APP_TITLE, CONFIG_SCHEMA, PROJECT_URL, VERSION
from ..hotkeys import TriggerKeyListener
from ..icons import make_caret_image
from ..modules import MODULES
from ..features import merge_settings
from ..settings_spec import SETTING_GROUPS
from ..speech import list_sapi_voices
from ..theme import _hex_to_rgb
from .common import _release_grab

if TYPE_CHECKING:  # pragma: no cover
    # 只为类型标注服务：外壳（hanzi_pinyin.py）反过来 import 本模块，
    # 运行时真去 import 会成环。
    from hanzi_pinyin import HanziPopup


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
        # S4：功能模块可以往「功能模块」页追加自己的设置项，
        # 页面的构建、取值、恢复默认都走这份合并后的表
        self.groups = merge_settings(SETTING_GROUPS, getattr(app, "features", {}))
        self.current = self.groups[0]["key"]
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
        # 滚轮在任何子控件上都能带动内容区（设置窗口是置顶的，不影响主窗口）
        self.win.bind_all("<MouseWheel>", self._on_content_wheel)

        self.header.bind("<ButtonPress-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._do_drag)
        self.header.bind("<ButtonRelease-1>", self._end_drag)

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
        for group in self.groups:
            self._nav(group["key"], group["title"])
        self._nav("about", "关于")

        # 右侧内容（设置项会越加越多，这里做成可滚动的）
        wrap = tk.Frame(body, bg=c["panel"])
        wrap.pack(side="left", fill="both", expand=True)

        self.content_canvas = tk.Canvas(wrap, bg=c["panel"], highlightthickness=0, bd=0)
        self.content_canvas.pack(side="left", fill="both", expand=True)
        self.content_scroll = tk.Scrollbar(
            wrap, orient="vertical", command=self.content_canvas.yview, width=9,
            troughcolor=c["panel"], bg=c["scroll"], relief="flat", bd=0,
            activebackground=c["border"],
        )
        self.content_canvas.configure(yscrollcommand=self._on_content_scroll)

        self.content = tk.Frame(self.content_canvas, bg=c["panel"])
        self._content_id = self.content_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self.content.bind(
            "<Configure>",
            lambda _e: self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all")),
        )
        self.content_canvas.bind(
            "<Configure>",
            lambda e: self.content_canvas.itemconfigure(self._content_id, width=e.width),
        )
        self.content_canvas.bind("<MouseWheel>", self._on_content_wheel)
        self.content.bind("<MouseWheel>", self._on_content_wheel)

        for group in self.groups:
            self.pages[group["key"]] = self._build_group_page(group)
        self.pages["about"] = self._build_about_page()

        self._show_page(self.current)

    def _on_content_scroll(self, first: str, last: str) -> None:
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.content_scroll.pack_forget()
        elif not self.content_scroll.winfo_ismapped():
            self.content_scroll.pack(side="right", fill="y")
        self.content_scroll.set(first, last)

    def _on_content_wheel(self, event) -> None:
        self.content_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

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
        # 内容区是可滚动的，页面只负责占满宽度，高度按需
        self.pages[key].pack(fill="x", padx=18, pady=14)
        self.content_canvas.yview_moveto(0)

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
    def _choices_for(self, item: dict) -> list:
        """静态选项 + 运行时来源（目前只有系统嗓音列表）。"""
        choices = list(item["choices"])
        if item.get("choices_from") == "voices":
            known = {value for _lb, value in choices}
            for name, gender, culture in list_sapi_voices():
                if name in known:
                    continue
                tag = (culture or "").upper()
                label = f"{name} · {tag}" if tag else name
                choices.append((label, name))
        return choices

    def _build_group_page(self, group: dict) -> tk.Frame:
        c = self.colors
        page = tk.Frame(self.content, bg=c["panel"])
        tk.Label(page, text=group["title"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 12, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        if group["key"] == "module":
            self._build_modules_block(page)
        for item in group["items"]:
            self._build_item(page, item)
        return page

    def _build_modules_block(self, parent) -> None:
        """US11：15 个可选模块的开关（本期只做开关与入口，功能随迭代交付）。"""
        c = self.colors
        tk.Label(parent, text="可选功能模块", bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(parent, text="勾选即启用；未启用的模块不加载依赖、不显示入口。",
                 bg=c["panel"], fg=c["fg_dim"], font=(self.app.cn_font, 8),
                 anchor="w", justify="left").pack(fill="x", pady=(2, 8))

        grid = tk.Frame(parent, bg=c["panel"])
        grid.pack(fill="x")
        mods = self.cfg.get("modules") or {}
        self.module_vars = {}
        for idx, mod in enumerate(MODULES):
            var = tk.BooleanVar(value=bool(mods.get(mod["key"], mod.get("default", False))))
            self.module_vars[mod["key"]] = var
            tk.Checkbutton(
                grid, text=mod["label"], variable=var, bg=c["panel"], fg=c["fg"],
                selectcolor=c["panel_alt"], activebackground=c["panel"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2",
            ).grid(row=idx, column=0, sticky="w", pady=1)
            tk.Label(grid, text=mod["hint"], bg=c["panel"], fg=c["fg_dim"],
                     font=(self.app.cn_font, 8), anchor="w").grid(
                row=idx, column=1, sticky="w", padx=(10, 0))

        tk.Frame(parent, bg=c["border"], height=1).pack(fill="x", pady=(10, 10))

    def _build_item(self, parent, item: dict) -> None:
        c = self.colors
        row = tk.Frame(parent, bg=c["panel"])
        row.pack(fill="x")
        # 标签列固定宽度（像素），否则长标签会爬到控件上去
        row.columnconfigure(0, minsize=176)
        row.columnconfigure(1, weight=1)

        tk.Label(row, text=item["label"], bg=c["panel"], fg=c["fg"],
                 font=(self.app.cn_font, 10), anchor="w", justify="left").grid(
            row=0, column=0, sticky="w", pady=3)

        holder = tk.Frame(row, bg=c["panel"])
        holder.grid(row=0, column=1, sticky="w")
        ctrl = holder          # 控件都往这一格塞

        key = item["key"]
        default = item["default"] if "default" in item else DEFAULT_CONFIG.get(key)
        kind = item["type"]

        if kind == "bool":
            var = tk.BooleanVar(value=bool(self.cfg.get(key, default)))
            chk = tk.Checkbutton(
                ctrl, text="启用", variable=var, bg=c["panel"], fg=c["fg_dim"],
                selectcolor=c["panel_alt"], activebackground=c["panel"],
                activeforeground=c["fg"], font=(self.app.cn_font, 9),
                highlightthickness=0, bd=0, anchor="w", cursor="hand2",
            )
            chk.pack(side="left")
            self.vars[key] = var
        elif kind == "int":
            var = tk.StringVar(value=str(self.cfg.get(key, default)))
            tk.Spinbox(
                ctrl, from_=item["min"], to=item["max"], increment=item.get("step", 1),
                textvariable=var, width=6, bg=c["entry_bg"], fg=c["fg"],
                buttonbackground=c["panel_alt"], relief="flat",
                insertbackground=c["fg"], font=(self.app.cn_font, 10),
                highlightthickness=0, bd=0,
            ).pack(side="left")
            if item.get("suffix"):
                tk.Label(ctrl, text=item["suffix"], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 9)).pack(side="left", padx=(4, 0))
            self.vars[key] = var
        elif kind == "color":
            var = tk.StringVar(value=str(self.cfg.get(key) or ""))
            tk.Entry(
                ctrl, textvariable=var, width=10, bg=c["entry_bg"], fg=c["fg"],
                relief="flat", insertbackground=c["fg"], highlightthickness=0, bd=0,
                font=(self.app.cn_font, 10),
            ).pack(side="left", ipady=3, padx=(0, 6))

            def pick_color(v=var):
                from tkinter import colorchooser
                try:
                    _rgb, hexv = colorchooser.askcolor(
                        color=v.get() or None, parent=self.win, title="选择背景色")
                except Exception:
                    return
                if hexv:
                    v.set(hexv)

            pick = tk.Label(ctrl, text="选择…", bg=c["panel_alt"], fg=c["fg"],
                            font=(self.app.cn_font, 9), padx=8, pady=3, cursor="hand2")
            pick.pack(side="left")
            pick.bind("<Button-1>", lambda _e: pick_color())
            follow = tk.Label(ctrl, text="跟随主题", bg=c["panel_alt"], fg=c["fg_dim"],
                              font=(self.app.cn_font, 9), padx=8, pady=3, cursor="hand2")
            follow.pack(side="left", padx=(4, 0))
            follow.bind("<Button-1>", lambda _e: var.set(""))
            self.vars[key] = var
        elif kind == "choice":
            choices = self._choices_for(item)
            current = self.cfg.get(key, default)
            if item.get("readonly"):
                tk.Label(ctrl, text=choices[0][0], bg=c["panel"], fg=c["fg_dim"],
                         font=(self.app.cn_font, 10)).pack(side="left")
                self.vars[key] = tk.StringVar(value=current)
            else:
                label = next((lb for lb, val in choices if val == current), choices[0][0])
                var = tk.StringVar(value=label)
                self._dropdown(ctrl, var, choices)
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
                 "双击触发键唤起 · Esc 隐藏 · Ctrl+Enter 朗读 · 标题栏图钉切换置顶\n"
                 "首次启动的模块清单可在「功能模块」页随时增删。",
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
        try:
            event.widget.grab_set()   # 抓住指针，鼠标跑出标题栏也能继续拖
        except Exception:
            pass

    def _do_drag(self, event) -> None:
        self.win.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _end_drag(self, _event=None) -> None:
        _release_grab(self.win)

    def _center(self) -> None:
        w, h = 640, 560
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
        for group in self.groups:
            for item in group["items"]:
                key = item["key"]
                if key not in self.vars:
                    continue
                default = item["default"] if "default" in item else DEFAULT_CONFIG.get(key)
                if item["type"] == "bool":
                    self.vars[key].set(bool(default))
                elif item["type"] == "int":
                    self.vars[key].set(str(default))
                elif item["type"] == "color":
                    self.vars[key].set(str(default or ""))
                elif item["type"] == "choice" and not item.get("readonly"):
                    choices = self._choices_for(item)
                    label = next((lb for lb, val in choices if val == default),
                                 choices[0][0])
                    self.vars[key].set(label)
        for key, var in getattr(self, "module_vars", {}).items():
            var.set(bool(DEFAULT_CONFIG["modules"].get(key, False)))
        self._set_status("已恢复默认值（尚未保存）")

    def _collect(self) -> dict:
        values = {}
        for group in self.groups:
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
                elif item["type"] == "color":
                    raw = str(var.get() or "").strip()
                    if not raw:
                        values[key] = None
                    elif _hex_to_rgb(raw) is None:
                        raise ValueError(f"「{item['label']}」需要 #rrggbb 形式的颜色，或留空")
                    else:
                        values[key] = raw if raw.startswith("#") else "#" + raw
        # US11：模块开关
        values["modules"] = {
            key: bool(var.get()) for key, var in getattr(self, "module_vars", {}).items()
        }
        return values

    def save(self) -> None:
        try:
            values = self._collect()
        except ValueError as exc:
            self._set_status(str(exc))
            return

        trigger = values.get("trigger_key")
        if trigger and trigger not in TriggerKeyListener.SUPPORTED:
            self._set_status("该按键暂不支持，请换一个")
            return

        # US15：键盘模式下「选中双击功能键」必须与「双击唤起键」不同
        if values.get("select_double_popup") and values.get("select_double_mode") == "key":
            sel_key = str(values.get("select_double_key") or "")
            if not sel_key:
                self._set_status("键盘模式需要选一个功能键，或改回鼠标模式")
                return
            if sel_key == trigger:
                ok = messagebox.askyesno(
                    "快捷键冲突",
                    "该键与唤起快捷键冲突，是否互换唤起与选中的快捷键？",
                    parent=self.win,
                )
                if not ok:
                    self._restore_choice("select_double_key",
                                         self.cfg.get("select_double_key", "shift"))
                    self._set_status("已取消，未做修改")
                    return
                values["trigger_key"], values["select_double_key"] = sel_key, trigger

        self.app.apply_settings(values)
        self.close()

    def _restore_choice(self, key: str, value: str) -> None:
        """把某个下拉框回退到 cfg 里的旧值（用户点了「取消」时用）。"""
        mapping = self.vars.get("__choices__", {}).get(key)
        var = self.vars.get(key)
        if not mapping or var is None:
            return
        label = next((lb for lb, val in mapping.items() if val == value), None)
        if label:
            var.set(label)

    def close(self) -> None:
        self.alive = False
        try:
            self.win.unbind_all("<MouseWheel>")
        except Exception:
            pass
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
