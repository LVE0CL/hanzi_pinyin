"""选区读取：优先 UI Automation（不动剪贴板），失败由调用方兜底。"""
from __future__ import annotations

import platform
import threading

# --------------------------------------------------------------------------
# 选区读取（US6 / US8）
# --------------------------------------------------------------------------
_UIA_THREADS = set()

MODIFIER_KEYS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
_MODIFIER_STATE = set()   # 非 Windows 平台由键盘监听维护
_MODIFIER_LOCK = threading.Lock()


def _init_uia_in_thread():
    """uiautomation 要求每个使用它的线程各自初始化 COM，否则会静默失败。"""
    tid = threading.get_ident()
    if tid in _UIA_THREADS:
        return True
    if platform.system() != "Windows":
        return False
    try:
        import uiautomation as auto
    except Exception:
        return False
    for name in ("InitializeUIAutomationInCurrentThread", "UIAutomationInitializerInThread"):
        fn = getattr(auto, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            break
    _UIA_THREADS.add(tid)
    return True


def read_selection_uia() -> str:
    """用 UI Automation 直接读焦点控件的文本选区——**完全不碰剪贴板**。

    读不到（控件不支持 TextPattern、没焦点、非 Windows）就返回空串，
    调用方据此判断「没有选区」，从而不去打扰用户。
    """
    if not _init_uia_in_thread():
        return ""
    try:
        import uiautomation as auto

        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return ""
        try:
            pattern = ctrl.GetTextPattern()
        except Exception:
            return ""
        if pattern is None:
            return ""
        try:
            ranges = pattern.GetSelection()
        except Exception:
            return ""
        parts = []
        for r in ranges or []:
            try:
                txt = r.GetText(-1)
            except Exception:
                txt = ""
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip()
    except Exception:
        return ""


# 只有这些控件里的 Ctrl+C 才是「复制文字」，其它（列表、按钮、桌面）按下去可能是复制文件
TEXT_CONTROL_TYPES = {"EditControl", "DocumentControl", "TextControl"}


def control_type_at(x: int, y: int) -> str:
    """光标落点处的 UIA 控件类型名，用来判断「这里能不能安全地按 Ctrl+C」。"""
    if not _init_uia_in_thread():
        return ""
    try:
        import uiautomation as auto

        ctrl = auto.ControlFromPoint(int(x), int(y))
        return getattr(ctrl, "ControlTypeName", "") or ""
    except Exception:
        return ""


def pressed_modifiers() -> set:
    """当前按下的修饰键集合（用于区分双击手势）。"""
    if platform.system() == "Windows":
        try:
            import ctypes

            u = ctypes.windll.user32
            out = set()
            for name, vk in MODIFIER_KEYS.items():
                if u.GetAsyncKeyState(vk) & 0x8000:
                    out.add(name)
            return out
        except Exception:
            return set()
    with _MODIFIER_LOCK:
        return set(_MODIFIER_STATE)



def cursor_position():
    """当前鼠标位置（跨平台）；失败给个能看的默认值。"""
    try:
        from pynput.mouse import Controller

        x, y = Controller().position
        return int(x), int(y)
    except Exception:
        return 200, 200
