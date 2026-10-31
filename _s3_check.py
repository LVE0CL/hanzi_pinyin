# -*- coding: utf-8 -*-
"""S3 结构验证：标题栏 / 底部条 / 八向热区搬到 hpp/ui/widgets.py 之后仍然好用。

用临时配置目录，不动用户真实配置。
"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_CFG_DIR = tempfile.mkdtemp(prefix="hpp-s3-")
os.environ["HPP_CONFIG_DIR"] = _CFG_DIR
os.environ["HPP_PORT"] = "47671"

import hanzi_pinyin as H

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  {detail}" if detail else ""))


def pump(app, ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.root.update()
        except Exception:
            break
        time.sleep(0.01)


def main():
    cfg = H.migrate(dict(H.DEFAULT_CONFIG))
    cfg["first_run"] = False
    cfg["start_hidden"] = False
    cfg["window_width"], cfg["window_height"] = 420, 240
    app = H.HanziPopup(cfg)
    pump(app, 400)
    app.show()
    pump(app, 500)

    print("\n== 零件就位 ==")
    check("标题栏来自 hpp.ui.widgets.TitleBar",
          type(app.titlebar).__module__ == "hpp.ui.widgets"
          and type(app.titlebar).__name__ == "TitleBar")
    check("底部条来自 BottomBar", type(app.bottom).__name__ == "BottomBar")
    check("热区来自 ResizeZones", type(app.zones).__name__ == "ResizeZones")

    print("\n== 兼容属性（外部按旧名字取控件）==")
    check("app.bar", app.bar is app.titlebar.bar)
    check("app.btn_pin", app.btn_pin is app.titlebar.btn_pin)
    check("app.btn_settings", app.btn_settings is app.bottom.btn_settings)
    check("app.btn_hand 是当前手写入口", app.btn_hand is app.bottom.btn_hand)

    print("\n== 标题栏 ==")
    kids = [w for w in app.bar.winfo_children()]
    check("标题栏有 7 个控件", len(kids) == 7, len(kids))
    check("复制/朗读在标题栏内", app.titlebar.btn_copy in kids and app.titlebar.btn_speak in kids)
    check("图钉是位图", bool(getattr(app.btn_pin, "_images", None)))
    x0, y0 = app.root.winfo_x(), app.root.winfo_y()
    app.titlebar._start_drag(NS(x_root=x0 + 100, y_root=y0 + 10, widget=app.bar))
    app.titlebar._do_drag(NS(x_root=x0 + 140, y_root=y0 + 40))
    app.titlebar._end_drag()
    pump(app, 150)
    check("拖标题栏能移动窗口",
          (app.root.winfo_x(), app.root.winfo_y()) == (x0 + 40, y0 + 30),
          f"{app.root.winfo_x()},{app.root.winfo_y()}")

    print("\n== 八向热区 ==")
    check("8 个热区", len(app.zones.zones) == 8, len(app.zones.zones))
    check("热区都在窗口上", all(z[0].winfo_ismapped() for z in app.zones.zones.values()))
    w0, h0 = app.root.winfo_width(), app.root.winfo_height()
    app.zones._start(NS(x_root=500, y_root=400, widget=app.zones.zones["se"][0]), "se")
    app.zones._drag(NS(x_root=560, y_root=450, widget=app.zones.zones["se"][0]))
    app.zones._end()
    pump(app, 200)
    check("拖右下角变大", app.root.winfo_width() > w0 and app.root.winfo_height() > h0,
          f"{w0}x{h0} -> {app.root.winfo_width()}x{app.root.winfo_height()}")
    check("尺寸写进配置", int(cfg.get("window_width", 0)) == app.root.winfo_width())

    print("\n== 最大化时收起热区 ==")
    app.toggle_maximize()
    pump(app, 300)
    check("最大化后热区隐藏",
          not any(z[0].winfo_ismapped() for z in app.zones.zones.values()))
    app.toggle_maximize()
    pump(app, 300)
    check("还原后热区回来",
          all(z[0].winfo_ismapped() for z in app.zones.zones.values()))

    print("\n== 底部提示语 ==")
    default_text = app.bottom.default_text
    check("默认提示语非空", bool(default_text), default_text)
    app.bottom.flash("已复制拼音", ms=80)
    check("闪现文案即时生效", app.bottom.hint.cget("text") == "已复制拼音")
    pump(app, 300)
    check("到点自动还原", app.bottom.hint.cget("text") == default_text,
          app.bottom.hint.cget("text"))

    print("\n== 手写入口随开关出现/消失 ==")
    app.cfg["modules"]["handwriting"] = False
    app.bottom.rebuild_hand_entry()
    pump(app, 100)
    check("关掉后入口消失", app.btn_hand is None)
    app.cfg["modules"]["handwriting"] = True
    app.bottom.rebuild_hand_entry()
    pump(app, 100)
    check("打开后入口回来", app.btn_hand is not None)

    print("\n== 主题切换后零件跟着换色 ==")
    old_titlebar = app.titlebar
    app.cfg["theme"] = "light_plus"
    app.rebuild_ui()
    pump(app, 300)
    check("重画后是新零件", app.titlebar is not old_titlebar)
    check("标题栏配色随主题",
          str(app.titlebar.bar.cget("bg")).lower() == app.colors["panel"].lower(),
          app.titlebar.bar.cget("bg"))
    check("兼容属性指向新控件", app.bar is app.titlebar.bar)
    check("热区重建且可见", all(z[0].winfo_ismapped() for z in app.zones.zones.values()))

    app.quit()
    pump(app, 200)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    for name, _ok, detail in failed:
        print("  未通过：", name, detail)
    sys.stdout.flush()
    os._exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
