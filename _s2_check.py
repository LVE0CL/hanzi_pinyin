# -*- coding: utf-8 -*-
"""S2 结构验证：搬走的 UI 组件在新位置还能正常构造、渲染、销毁。

不碰磁盘配置（只构造不保存），跑完 os._exit 避免 Tk 后台线程拖住进程。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    app = H.HanziPopup(cfg)
    pump(app, 400)

    print("\n== 主窗口 ==")
    app.show()
    pump(app, 600)
    check("主窗口可见", bool(app.root.winfo_viewable()))
    check("窗口有实际尺寸", app.root.winfo_width() > 200 and app.root.winfo_height() > 100,
          f"{app.root.winfo_width()}x{app.root.winfo_height()}")

    print("\n== RubyView（hpp/ui/ruby_view.py）==")
    app.entry.delete("0", "end")
    app.entry.insert("0", "世界你好")
    app._schedule_refresh()
    pump(app, 300)
    check("注音视图有内容", len(app.ruby_view.items) == 4, f"{len(app.ruby_view.items)} 项")
    check("渲染出行", len(app.ruby_view.rows) >= 1, f"{len(app.ruby_view.rows)} 行")
    check("cell_width 可用", app.ruby_view.cell_width() > 0, app.ruby_view.cell_width())

    print("\n== SettingsWindow（hpp/ui/settings.py）==")
    win = H.SettingsWindow(app)
    pump(app, 300)
    check("设置窗口打开", win.alive is True)
    check("设置项齐全", len(win.vars) >= 20, f"{len(win.vars)} 项")
    check("分组页齐全", len(win.pages) >= 4, f"{sorted(win.pages)}")
    win.close()
    pump(app, 200)
    check("关闭后 app 引用清空", app._settings_win is None)

    print("\n== FirstRunWindow（hpp/ui/first_run.py）==")
    guide = H.FirstRunWindow(app)
    pump(app, 300)
    check("引导页打开", guide.alive is True)
    check("15 项分 3 页", len(guide.pages) == 3 and [len(p) for p in guide.pages] == [7, 7, 1],
          [len(p) for p in guide.pages])
    check("翻页到第二页", (guide._go(1) or True) and guide.page == 1, f"page={guide.page}")
    guide._go(-5)
    check("上一页越界收敛到首页", guide.page == 0, f"page={guide.page}")
    guide._go(99)
    check("下一页越界收敛到末页", guide.page == 2, f"page={guide.page}")
    guide.close()
    pump(app, 200)
    check("关闭后 app 引用清空", app._guide is None)

    print("\n== HandwritingPad（hpp/ui/handwriting.py）==")
    pad = H.HandwritingPad(app)
    pump(app, 300)
    check("手写板打开", pad.alive is True)
    check("状态文案提到手写", "手写" in pad.status.cget("text"), pad.status.cget("text"))
    pad.close()
    pump(app, 200)
    check("关闭后 app 引用清空", app._pad is None)

    print("\n== MiniPopup（hpp/ui/mini_popup.py）==")
    app.cfg["mini_popup_pinned"] = True          # 固定住，免得 3 秒后自己淡出
    mini = H.MiniPopup(app, "世界", 400, 300)
    pump(app, 400)
    check("迷你浮窗存在", mini.win.winfo_exists() == 1)
    check("浮窗不空", bool(mini.view.items), f"{len(mini.view.items)} 项")
    check("贴到指定位置", abs(mini.win.winfo_x() - 400) < 60,
          f"x={mini.win.winfo_x()}")
    mini.close()
    pump(app, 200)
    check("关闭后 app 引用清空", app._mini is None)

    print("\n== hpp/paths.py ==")
    from hpp.paths import app_dir, handwriting_model_path, handwriting_status
    check("app_dir 指向项目根", os.path.basename(app_dir()) == "hanzi-pinyin-popup", app_dir())
    check("模型路径落在项目根下",
          handwriting_model_path().startswith(app_dir()), handwriting_model_path())
    check("系统手写状态文案可用", "手写" in handwriting_status("system"),
          handwriting_status("system"))

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
