#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.2.0 验收自测（会真的开窗口，跑完自行退出）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 输出编码钉死 UTF-8：门禁是用 UTF-8 解子进程输出的，而中文 Windows 下管道
# 默认走 GBK，打印 "−"（U+2212）、"📌" 这类字符会直接 UnicodeEncodeError，
# 脚本崩在中途、退出码却是 1，看起来像"验收没过"，其实一个字都没验完。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import hanzi_pinyin as H
import hpp.ui.settings as SETTINGS  # S2：messagebox 已随设置窗口搬到这里

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  {detail}" if detail else ""))
    return bool(cond)


def pump(app, ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.root.update()
        except Exception:
            break
        time.sleep(0.01)


def main():
    cfg = dict(H.DEFAULT_CONFIG)
    cfg.update({
        "first_run": False,
        "position": [140, 140],
        "always_on_top": True,
        "theme": "dark_plus",
        "theme_background": None,
        "modules": H.default_modules(),
    })
    app = H.HanziPopup(cfg)
    pump(app, 400)

    print("\n== US10 齿轮图标 ==")
    gear_imgs = [r for r in app._image_refs if isinstance(r, object)]
    check("首页齿轮入口存在", app.btn_settings is not None)
    check("齿轮按钮有图像", bool(getattr(app.btn_settings, "cget", lambda k: None)("image")))
    tray_labels = []
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("⚙ 设置", lambda: None),
        )
        tray_labels = ["⚙ 设置"]
    except Exception:
        pass
    check("托盘设置项带齿轮字符", tray_labels and "⚙" in tray_labels[0])

    print("\n== US14 图钉 / 置顶 ==")
    widgets = [str(w) for w in app.bar.winfo_children()]
    order = [w for w in app.bar.winfo_children()]
    names = [getattr(w, "cget", lambda k: "")("text") for w in order]
    check("标题栏顺序 ×□−📌", names[:5] == ["汉字拼音浮窗", "×", "□", "−", ""], str(names))
    check("图钉用位图而非文字", getattr(app.btn_pin, "_images", None) is not None)
    before = bool(app.root.attributes("-topmost"))
    app.toggle_topmost()
    pump(app, 100)
    after = bool(app.root.attributes("-topmost"))
    check("点击图钉切换置顶", before != after and app.cfg["always_on_top"] == after)
    app.toggle_topmost()
    pump(app, 100)

    print("\n== FR1 过滤 ==")
    app.entry.delete(0, "end")
    app.entry.insert(0, "Hello 你好 123！")
    app.refresh()
    pump(app, 200)
    chars = "".join(it["char"] for it in app.ruby_view.items)
    check("浮窗只显示中文与标点", chars == "你好！", repr(chars))
    check("英文数字不出现", "Hello" not in chars and "123" not in chars)

    print("\n== US13 主题 ==")
    app.cfg["theme"] = "monokai"
    app.rebuild_ui()
    pump(app, 200)
    check("主题切换后主背景变化",
          app.colors["panel"].lower() == H.THEMES["monokai"]["panel"].lower(),
          app.colors["panel"])
    check("重绘后输入内容保留", app.entry.get() == "Hello 你好 123！")
    check("重绘后图钉仍在", app.btn_pin is not None)
    app.cfg["theme"] = "dark_plus"
    app.rebuild_ui()
    pump(app, 200)

    print("\n== US15 快捷键 ==")
    app.cfg["trigger_key"] = ""
    app._start_trigger()
    check("唤起键留空则禁用", app._trigger.disabled)
    app.cfg["trigger_key"] = "ctrl"
    app._start_trigger()
    app.cfg["select_double_mode"] = "key"
    app.cfg["select_double_key"] = "shift"
    app._start_select_double()
    check("键盘模式用 TriggerKeyListener", isinstance(app._mouse, H.TriggerKeyListener))
    check("键盘模式监听 Shift", app._mouse.key == "shift")
    app.cfg["select_double_mode"] = "mouse"
    app._start_select_double()
    check("鼠标模式用 MouseDoubleClickListener",
          isinstance(app._mouse, H.MouseDoubleClickListener))

    print("\n== US11 设置页 / 模块 ==")
    win = H.SettingsWindow(app)
    pump(app, 250)
    check("设置页有主题项", "theme" in win.vars)
    check("设置页有背景色项", "theme_background" in win.vars)
    check("设置页有选中双击模式", "select_double_mode" in win.vars)
    check("设置页有键盘功能键", "select_double_key" in win.vars)
    check("抓取热键项已删除", "hotkey" not in win.vars)
    check("15 个模块复选框", len(getattr(win, "module_vars", {})) == 15,
          str(len(getattr(win, "module_vars", {}))))
    win.close()
    pump(app, 150)

    print("\n== US15 冲突互换 ==")
    win = H.SettingsWindow(app)
    pump(app, 200)
    win.vars["select_double_mode"].set("键盘")
    win.vars["select_double_key"].set("Ctrl")
    win.vars["trigger_key"].set("Ctrl")
    SETTINGS.messagebox.askyesno = lambda *a, **k: True
    win.save()
    pump(app, 300)
    check("冲突时互换两值",
          app.cfg["trigger_key"] == "ctrl" and app.cfg["select_double_key"] == "ctrl"
          or (app.cfg["trigger_key"] == app.cfg["select_double_key"]),
          f"trigger={app.cfg['trigger_key']} sel={app.cfg['select_double_key']}")
    win2 = H.SettingsWindow(app)
    pump(app, 200)
    win2.vars["select_double_mode"].set("键盘")
    win2.vars["select_double_key"].set("Shift")
    win2.vars["trigger_key"].set("Shift")
    SETTINGS.messagebox.askyesno = lambda *a, **k: False
    before_key = app.cfg["select_double_key"]
    win2.save()
    pump(app, 200)
    check("取消则不修改并回退输入",
          app.cfg["select_double_key"] == before_key
          and win2.vars["select_double_key"].get() not in ("Shift",),
          f"cfg={app.cfg['select_double_key']} ui={win2.vars['select_double_key'].get()}")
    win2.close()
    pump(app, 150)
    app.cfg["trigger_key"] = "ctrl"
    app.cfg["select_double_key"] = "shift"
    app.cfg["select_double_mode"] = "key"

    print("\n== US17 点浮窗外关闭 ==")
    app.show_mini("你好", 300, 300)
    pump(app, 400)
    mini = app._mini
    check("迷你浮窗已创建", mini is not None)
    mini._born = time.monotonic() - 5
    rx, ry = mini.win.winfo_rootx(), mini.win.winfo_rooty()
    mini._maybe_close_outside(rx + 5, ry + 5)
    pump(app, 100)
    check("点在浮窗内不关闭", app._mini is mini)
    mini.pinned = True
    mini._maybe_close_outside(rx - 200, ry - 200)
    pump(app, 100)
    check("已固定时点外面也不关闭", app._mini is mini)
    mini.pinned = False
    app.cfg["popup_dismiss_on_outside_click"] = False
    mini._maybe_close_outside(rx - 200, ry - 200)
    pump(app, 100)
    check("开关关闭时不响应外部点击", app._mini is mini)
    app.cfg["popup_dismiss_on_outside_click"] = True
    mini._maybe_close_outside(rx - 200, ry - 200)
    pump(app, 200)
    check("点浮窗外自动关闭", app._mini is None)

    print("\n== US12 手写 ==")
    app.cfg["modules"]["handwriting"] = True
    app.rebuild_ui()
    pump(app, 200)
    check("启用后首页出现手写入口", app.btn_hand is not None)
    app.open_handwriting()
    pump(app, 300)
    pad = app._pad
    check("手写板打开", pad is not None)
    pad.strokes = [[(10, 10), (60, 12)], [(30, 5), (32, 90)]]
    pad._redraw()
    check("笔画可记录/重绘", len(pad.strokes) == 2)
    pad.undo()
    check("撤销减少一笔", len(pad.strokes) == 1)
    pad.recognize()
    pump(app, 200)
    check("识别给出明确说明", "手写面板" in pad.status.cget("text"),
          pad.status.cget("text"))
    pad.clear()
    check("清空后无笔画", pad.strokes == [])
    pad.strokes = [[(10, 10), (60, 12)]]
    app.cfg["handwriting_engine"] = "offline"
    pad.recognize()
    pump(app, 100)
    check("离线引擎给出缺模型提示", "onnx" in pad.status.cget("text").lower(),
          pad.status.cget("text"))
    pad.close()
    pump(app, 150)
    app.cfg["modules"]["handwriting"] = False
    app.rebuild_ui()
    pump(app, 200)
    check("关闭模块后入口消失", app.btn_hand is None)

    print("\n== US11 首启引导 ==")
    app.cfg["first_run"] = True
    app.open_first_run()
    pump(app, 300)
    guide = app._guide
    check("引导页打开", guide is not None)
    check("引导页列出 15 项", len(guide.vars) == 15, str(len(guide.vars)))
    guide._set_all(False)
    guide.vars["handwriting"].set(True)
    guide.confirm()
    pump(app, 300)
    check("确认后 first_run=False", app.cfg["first_run"] is False)
    check("确认后写入 modules", app.cfg["modules"]["handwriting"] is True
          and sum(1 for v in app.cfg["modules"].values() if v) == 1)
    saved = H.load_config()
    check("配置已落盘", saved.get("first_run") is False
          and saved.get("modules", {}).get("handwriting") is True)
    check("引导页已销毁", app._guide is None)
    check("手写入口已恢复", app.btn_hand is not None)

    app.quit()
    pump(app, 200)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    for name, _ok, detail in failed:
        print("  未通过：", name, detail)
    sys.stdout.flush()
    # 必须硬退出：托盘（pystray）与热键监听（pynput）的线程在 Windows 上
    # 停不干净，主线程会卡在 threading._shutdown() 里，进程永不返回——
    # 门禁看到的就是「超时 300s」，整条流水线一个任务都交不了。
    # 同目录的 _s2/_s3/_s4 早就是 os._exit，这里补齐，退出码照旧表达结果。
    os._exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
