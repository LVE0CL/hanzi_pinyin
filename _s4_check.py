# -*- coding: utf-8 -*-
"""S4 结构验证：Feature 契约、注册表、面板挂载、设置合并、坏模块隔离。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_CFG_DIR = tempfile.mkdtemp(prefix="hpp-s4-")
os.environ["HPP_CONFIG_DIR"] = _CFG_DIR
os.environ["HPP_PORT"] = "47672"

import tkinter as tk

import hanzi_pinyin as H
from hpp.features import (
    Feature,
    annotate_all,
    build_panels,
    collect_self_checks,
    load_features,
    merge_settings,
    notify_text,
)
from hpp.settings_spec import SETTING_GROUPS

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


class Boom(Feature):
    """故意每个挂点都抛异常，验证注册表把它们都兜住了。"""

    key = "boom"
    label = "坏模块"

    def panel(self, parent):
        raise RuntimeError("panel 炸了")

    def annotate(self, items):
        raise RuntimeError("annotate 炸了")

    def on_text(self, text, items):
        raise RuntimeError("on_text 炸了")

    def settings_spec(self):
        raise RuntimeError("settings_spec 炸了")

    def self_check(self):
        raise RuntimeError("self_check 炸了")


def main():
    print("== 注册表 ==")
    check("没勾模块时一个都不加载", load_features({"modules": {}}) == {})
    all_feats = load_features({}, include_disabled=True)
    # 这里只验「两个参考实现还在」，不锁死总数：一旦写成 == ["handwriting",
    # "tone_contour"]，每加一个模块（T01 起 12 个任务）都得回来改别人的验收脚本，
    # 门禁就成了「谁先交谁改脚本」的地雷。模块数量由 registry 与开关负责，
    # 契约由下面的挂点检查负责，不需要在这里数个数。
    check("参考实现模块都在", {"handwriting", "tone_contour"} <= set(all_feats),
          sorted(all_feats))
    check("实例都是 Feature", all(isinstance(f, Feature) for f in all_feats.values()))

    cfg = H.migrate(dict(H.DEFAULT_CONFIG))
    cfg["first_run"] = False
    cfg["start_hidden"] = False
    cfg["modules"] = {k: False for k in cfg["modules"]}
    cfg["modules"]["tone_contour"] = True
    app = H.HanziPopup(cfg)
    pump(app, 400)
    app.show()
    pump(app, 400)

    print("\n== 面板挂载 ==")
    check("只加载勾了的模块", sorted(app.features) == ["tone_contour"], sorted(app.features))
    check("面板建出来了", len(app.feature_panels) == 1, len(app.feature_panels))
    check("面板宿主可见", bool(app.feature_host.winfo_ismapped()))
    panel = app.features["tone_contour"].panel_widget
    check("面板挂在宿主里", panel.frame.master is app.feature_host)

    print("\n== annotate / on_text ==")
    app.set_text("妈妈骂马")
    pump(app, 400)
    tones = [it.get("tone") for it in app.ruby_view.items]
    check("每个字补上了声调", tones == [1, 1, 4, 3], tones)
    check("面板画了东西", len(panel.canvas.find_all()) > 0,
          len(panel.canvas.find_all()))
    check("标点不崩", (app.set_text("你好，世界！"), True)[1])
    pump(app, 300)

    print("\n== settings_spec ==")
    win = H.SettingsWindow(app)
    pump(app, 300)
    check("设置项进了合并表",
          any(i["key"] == "tone_contour_scale"
              for g in win.groups if g["key"] == "module" for i in g["items"]))
    check("表单里有这个控件", "tone_contour_scale" in win.vars)
    values = win._collect()
    # _collect 已经按 int 类型转换过了
    check("_collect 收得到", values.get("tone_contour_scale") == 54,
          values.get("tone_contour_scale"))
    win.vars["tone_contour_scale"].set("80")
    win.save()
    pump(app, 400)
    check("保存后写进配置", int(cfg.get("tone_contour_scale")) == 80,
          cfg.get("tone_contour_scale"))
    check("面板高度跟着变", int(panel.canvas.cget("height")) == 80,
          panel.canvas.cget("height"))

    print("\n== 关掉模块后面板消失 ==")
    cfg["modules"]["tone_contour"] = False
    app.reload_features()
    pump(app, 400)
    check("模块被卸载", app.features == {})
    check("面板没了", app.feature_panels == [])
    check("宿主不占位置", not app.feature_host.winfo_ismapped())
    check("渲染不受影响", len(app.ruby_view.items) > 0, len(app.ruby_view.items))

    print("\n== 坏模块不能拖垮程序 ==")
    boom = Boom()
    host = tk.Frame(app.root)
    check("panel 抛异常被兜住", build_panels({"boom": boom}, host) == [])
    items = [{"char": "汉", "readings": ["hàn"]}]
    check("annotate 抛异常不影响渲染", annotate_all({"boom": boom}, items) == items)
    notify_text({"boom": boom}, "汉", items)          # 不抛就是通过
    check("on_text 抛异常被兜住", True)
    check("settings_spec 抛异常不改表",
          merge_settings(SETTING_GROUPS, {"boom": boom}) == SETTING_GROUPS)
    checks = collect_self_checks({"boom": boom})
    check("self_check 抛异常记为失败项",
          len(checks) == 1 and checks[0][1] is False, checks)

    print("\n== 自检汇总 ==")
    merged = collect_self_checks(all_feats)
    check("两条模块的自检都被收进来", len(merged) >= 8, len(merged))
    check("名称带模块前缀", all(n.startswith("[") for n, _ok, _d in merged),
          merged[0][0])
    check("全部通过", all(ok for _n, ok, _d in merged),
          [n for n, ok, _d in merged if not ok])

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
