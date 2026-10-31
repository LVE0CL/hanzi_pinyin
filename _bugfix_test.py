"""三个 bug 的针对性验证（临时脚本，不提交）。"""
import tkinter as tk
import hanzi_pinyin as H

fails = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def pump(app, ms=250):
    end = app.root.tk.call("after", ms, lambda: None)
    app.root.update()
    app.root.after_cancel(end)
    app.root.update()


app = H.HanziPopup(H.load_config())
pump(app, 200)

print("== bug1 引导页分页与可关闭 ==")
app.cfg["first_run"] = True
app.open_first_run()
pump(app, 300)
g = app._guide
check("引导页打开", g is not None)
check("15 项全部登记", len(g.vars) == 15, str(len(g.vars)))
check("分页 7 项一页 → 3 页", len(g.pages) == 3 and [len(p) for p in g.pages] == [7, 7, 1],
      str([len(p) for p in g.pages]))
check("首页可见行数 = 7", len(g.pagewrap.winfo_children()) == 7)

# 关键：开始使用按钮必须落在窗口内
win_h = g.win.winfo_height()
win_y = g.win.winfo_rooty()
target = None
for w in g.win.winfo_children():
    pass


def find_label(widget, text):
    for ch in widget.winfo_children():
        try:
            if ch.cget("text") == text:
                return ch
        except Exception:
            pass
        got = find_label(ch, text)
        if got is not None:
            return got
    return None


lbl = find_label(g.win, "开始使用")
check("找到「开始使用」按钮", lbl is not None)
if lbl is not None:
    bottom = lbl.winfo_rooty() + lbl.winfo_height()
    inside = (lbl.winfo_rooty() >= win_y) and (bottom <= win_y + win_h)
    check("「开始使用」在窗口可视区内", inside,
          f"按钮底部 {bottom} / 窗口底部 {win_y + win_h}")

g._go(1)
pump(app, 100)
check("翻到第 2 页", g.page == 1 and len(g.pagewrap.winfo_children()) == 7)
g._go(1)
pump(app, 100)
check("翻到第 3 页（1 项）", g.page == 2 and len(g.pagewrap.winfo_children()) == 1)
g._go(1)
check("末页不能再往后", g.page == 2)
g._go(-2)
check("可回到首页", g.page == 0)

# 关闭 = 回到默认配置
g.vars["handwriting"].set(False)
g.vars["srs_review"].set(True)
g.close_with_defaults()
pump(app, 300)
defaults = H.default_modules()
check("关闭后引导页销毁", app._guide is None)
check("first_run 置 False", app.cfg["first_run"] is False)
check("模块回到默认值", app.cfg["modules"] == defaults,
      str({k: v for k, v in app.cfg["modules"].items() if v}))
check("主界面可见", bool(app.root.winfo_viewable()))

print("\n== bug2 输入框可点击可输入 ==")
check("占位提示绑定了点击", bool(app.placeholder.bind("<Button-1>")))
app.entry.delete(0, "end")
pump(app, 100)
app._placeholder_click()
pump(app, 150)
check("点占位提示后焦点在输入框", app.root.focus_get() is app.entry,
      str(app.root.focus_get()))
check("占位提示已隐藏", not app.placeholder.winfo_ismapped())
app.entry.insert(0, "你好")
pump(app, 150)
check("能写入文字", app.entry.get() == "你好")
app.entry.selection_range(0, 2)
check("能选中文字", app.entry.selection_present())
app.entry.delete(0, "end")
pump(app, 150)

print("\n== bug3 选区来源 ==")
check("记录了自己的窗口句柄", app._hwnd != 0, hex(app._hwnd or 0))
import ctypes

_u = ctypes.windll.user32
_fg = int(_u.GetForegroundWindow() or 0)
_orig_hwnd = app._hwnd
try:
    app._hwnd = int(_u.GetDesktopWindow() or 0)
    check("句柄不是本进程窗口时判定为 False", app._foreground_is_mine() is False,
          "desktop=" + hex(app._hwnd))
    app._hwnd = int(_u.GetAncestor(ctypes.c_void_p(_fg), 2) or 0)
    check("句柄就是前台窗口时判定为 True", app._foreground_is_mine() is True, hex(_fg))
    app._hwnd = 0
    check("句柄为 0 时判定为 False", app._foreground_is_mine() is False)
finally:
    app._hwnd = _orig_hwnd

# 剪贴板兜底不能把旧内容当选区
import hpp.clipboard as C

import sys

orig_read, orig_write = C.read_clipboard, C.write_clipboard
orig_uia = C.read_selection_uia
_orig_kb = sys.modules.get("pynput.keyboard")
try:
    C.read_clipboard = lambda: "陈年旧内容"
    C.write_clipboard = lambda t: None
    C.read_selection_uia = lambda: ""
    import pynput.keyboard as _kb  # noqa: F401  （确保能导入，不真的按键）

    class _FakeKbd:
        def pressed(self, *a, **k):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return _Ctx()

        def press(self, *a):
            pass

        def release(self, *a):
            pass

    import types
    fake = types.SimpleNamespace(Controller=_FakeKbd, Key=types.SimpleNamespace(ctrl=None))
    import sys
    sys.modules["pynput.keyboard"] = fake
    got = C.grab_selection(preserve=True)
    check("Ctrl+C 没生效时返回空而不是旧剪贴板", got == "", repr(got))
finally:
    C.read_clipboard, C.write_clipboard = orig_read, orig_write
    C.read_selection_uia = orig_uia
    if _orig_kb is not None:
        sys.modules["pynput.keyboard"] = _orig_kb

print()
print("结果：" + (f"{len(fails)} 项失败: {fails}" if fails else "全部通过"))
import os

try:
    app.root.destroy()
except Exception:
    pass
os._exit(1 if fails else 0)
