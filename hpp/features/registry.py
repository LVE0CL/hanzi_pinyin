# -*- coding: utf-8 -*-
"""功能模块注册表：按 MODULES 的顺序把 `<key>.py` 变成可插拔的实例。

三条硬规则：

1. **按开关加载**：主界面只加载用户勾了的模块；`--selftest` 会用
   `include_disabled=True` 把所有「已实现」的模块都加载一遍，好让自检覆盖到
   没被勾上的代码。
2. **没实现 ≠ 出错**：模块文件不存在（`find_spec` 返回 None）就静默跳过——15 个
   模块里目前只有几个有实现，勾了没实现的不该报错。
3. **一个坏模块不能拖垮程序**：import / 实例化 / 各回调全部套 try/except，
   出错只在 stderr 记一行，然后当它不存在。
"""
from __future__ import annotations

import importlib
import importlib.util
import sys

from ..modules import MODULES
from .base import Feature


def _warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


def _enabled(cfg: dict, key: str) -> bool:
    return bool((cfg.get("modules") or {}).get(key, False))


def load_features(cfg: dict, include_disabled: bool = False) -> dict:
    """按注册表顺序加载功能模块，返回 `{key: Feature 实例}`。"""
    loaded = {}
    for mod in MODULES:
        key = mod["key"]
        if not include_disabled and not _enabled(cfg, key):
            continue
        modname = f"{__package__}.{key}"
        try:
            spec = importlib.util.find_spec(modname)
        except Exception:
            spec = None
        if spec is None:
            continue                      # 还没实现，静默跳过
        try:
            module = importlib.import_module(modname)
        except Exception as exc:
            _warn(f"模块 {key} 加载失败，已跳过：{exc}")
            continue
        cls = getattr(module, "FEATURE", None)
        if not isinstance(cls, type) or not issubclass(cls, Feature):
            _warn(f"{modname} 没有声明 FEATURE = Feature 子类，已跳过")
            continue
        try:
            loaded[key] = cls()
        except Exception as exc:
            _warn(f"模块 {key} 初始化失败，已跳过：{exc}")
    return loaded


def attach_all(features: dict, app) -> None:
    for key, feat in features.items():
        try:
            feat.attach(app)
        except Exception as exc:
            _warn(f"模块 {key} attach 失败：{exc}")


def build_panels(features: dict, host) -> list:
    """让每个模块把内嵌面板交给 host，返回真正建出来的控件列表。"""
    made = []
    for key, feat in features.items():
        try:
            widget = feat.panel(host)
        except Exception as exc:
            _warn(f"模块 {key} 面板创建失败：{exc}")
            continue
        if widget is None:
            continue
        try:
            widget.pack(fill="x")
        except Exception as exc:
            _warn(f"模块 {key} 面板布局失败：{exc}")
            continue
        made.append(widget)
    return made


def annotate_all(features: dict, items: list) -> list:
    for key, feat in features.items():
        try:
            items = feat.annotate(items) or items
        except Exception as exc:
            _warn(f"模块 {key} annotate 失败：{exc}")
    return items


def notify_text(features: dict, text: str, items: list) -> None:
    for key, feat in features.items():
        try:
            feat.on_text(text, items)
        except Exception as exc:
            _warn(f"模块 {key} on_text 失败：{exc}")


def merge_settings(groups: list, features: dict, group_key: str = "module") -> list:
    """把各模块的 settings_spec() 追加到指定分组页（默认「功能模块」）。"""
    extra = []
    for key, feat in features.items():
        try:
            extra.extend(feat.settings_spec() or [])
        except Exception as exc:
            _warn(f"模块 {key} settings_spec 失败：{exc}")
    if not extra:
        return groups
    merged = []
    for group in groups:
        if group.get("key") == group_key:
            group = dict(group, items=list(group["items"]) + extra)
        merged.append(group)
    return merged


def collect_self_checks(features: dict) -> list:
    """汇总各模块的自检项，统一成 `(名称, 是否通过, 细节)`，名称前带模块 key。"""
    out = []
    for key, feat in features.items():
        try:
            checks = feat.self_check() or []
        except Exception as exc:
            out.append((f"[{key}] 自检异常", False, str(exc)))
            continue
        for item in checks:
            try:
                name, ok = item[0], bool(item[1])
                detail = item[2] if len(item) > 2 else ""
            except Exception:
                out.append((f"[{key}] 自检项格式不对", False, repr(item)))
                continue
            out.append((f"[{key}] {name}", ok, detail))
    return out
