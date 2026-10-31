"""全局键 / 鼠标监听：双击触发键、选中后双击。"""
from __future__ import annotations

import platform
import sys
import time

from .selection import _MODIFIER_LOCK, _MODIFIER_STATE, pressed_modifiers

# --------------------------------------------------------------------------
# 全局键监听：双击触发
# --------------------------------------------------------------------------
class TriggerKeyListener:
    """监听「双击某个键」触发回调。现阶段只支持单键。"""

    SUPPORTED = ["ctrl", "alt", "shift", "space", "tab", "caps_lock"] + [
        f"f{i}" for i in range(1, 13)
    ]

    def __init__(self, key: str, interval_ms: int, callback):
        # US15：空字符串 = 用户主动禁用，不做任何监听
        self.disabled = not key or key not in self.SUPPORTED
        self.key = key if key in self.SUPPORTED else ""
        self.interval = max(0.15, min(1.0, int(interval_ms) / 1000.0))
        self.callback = callback
        self._last = 0.0
        self._pressed = False
        self._listener = None

    @staticmethod
    def _normalize(key) -> str:
        try:
            from pynput import keyboard
        except Exception:
            return ""
        if isinstance(key, keyboard.Key):
            name = getattr(key, "name", "") or ""
            return {
                "ctrl_l": "ctrl", "ctrl_r": "ctrl",
                "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
                "shift_l": "shift", "shift_r": "shift",
            }.get(name, name)
        try:
            return (key.char or "").lower()
        except Exception:
            return ""

    def start(self) -> bool:
        if self.disabled:
            return False
        try:
            from pynput import keyboard
        except Exception:
            print("[warn] 未安装 pynput，双击唤起不可用", file=sys.stderr)
            return False

        def on_press(key):
            name = self._normalize(key)
            if name != self.key:
                self._last = 0.0
                return
            if self._pressed:  # 过滤系统自动重复
                return
            self._pressed = True
            now = time.monotonic()
            if self._last and (now - self._last) <= self.interval:
                self._last = 0.0
                try:
                    self.callback()
                except Exception as exc:
                    print(f"[warn] 触发回调失败：{exc}", file=sys.stderr)
            else:
                self._last = now

        def on_release(key):
            if self._normalize(key) == self.key:
                self._pressed = False

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            print(f"[warn] 监听 {self.key} 失败：{exc}", file=sys.stderr)
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


class MouseDoubleClickListener:
    """监听「双击鼠标某个键」，并把点击坐标透传给回调（US6）。

    只在两次点击间隔 <= interval 且修饰键匹配时触发；是否真的有选区由回调判断。
    """

    def __init__(self, button: str, modifier: str, interval_ms: int, callback):
        self.button = button if button in ("left", "right", "middle") else "left"
        self.modifier = modifier if modifier in ("none", "ctrl", "alt", "shift") else "none"
        self.interval = max(0.15, min(1.0, int(interval_ms) / 1000.0))
        self.callback = callback
        self._last = 0.0
        self._listener = None
        self._mod_listener = None

    def start(self) -> bool:
        try:
            from pynput import mouse
        except Exception:
            print("[warn] 未安装 pynput，选中双击不可用", file=sys.stderr)
            return False

        if platform.system() != "Windows":
            self._start_modifier_tracker()

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            name = getattr(button, "name", "")
            if name != self.button:
                self._last = 0.0
                return
            now = time.monotonic()
            if self._last and (now - self._last) <= self.interval:
                self._last = 0.0
                if self.modifier != "none" and self.modifier not in pressed_modifiers():
                    return
                try:
                    self.callback(int(x), int(y))
                except Exception as exc:
                    print(f"[warn] 选中双击回调失败：{exc}", file=sys.stderr)
            else:
                self._last = now

        try:
            self._listener = mouse.Listener(on_click=on_click)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as exc:
            print(f"[warn] 启动鼠标监听失败：{exc}", file=sys.stderr)
            self._listener = None
            return False

    def _start_modifier_tracker(self) -> None:
        """非 Windows 没有 GetAsyncKeyState，用键盘监听自己维护修饰键状态。"""
        try:
            from pynput import keyboard
        except Exception:
            return

        mapping = {
            "ctrl_l": "ctrl", "ctrl_r": "ctrl",
            "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
            "shift_l": "shift", "shift_r": "shift",
        }

        def on_press(key):
            name = mapping.get(getattr(key, "name", ""))
            if name:
                with _MODIFIER_LOCK:
                    _MODIFIER_STATE.add(name)

        def on_release(key):
            name = mapping.get(getattr(key, "name", ""))
            if name:
                with _MODIFIER_LOCK:
                    _MODIFIER_STATE.discard(name)

        try:
            self._mod_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._mod_listener.daemon = True
            self._mod_listener.start()
        except Exception:
            self._mod_listener = None

    def stop(self) -> None:
        for listener in (self._listener, self._mod_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._listener = None
        self._mod_listener = None
