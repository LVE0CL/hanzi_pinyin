# -*- coding: utf-8 -*-
"""本地存储：一个小 JSON 文件，原子写、坏文件不崩。

为什么不复用 `config.py`：配置是「用户能在设置页里改的偏好」，丢了大不了恢复默认；
这里存的是用户一点点攒出来的数据（自定义读音、生词本……），丢了就是白用。所以
写入必须原子——先写 `.tmp`、`fsync`、再 `os.replace`。中途断电最多留下一个没人读
的 `.tmp`，`store.json` 要么是旧的完整版，要么是新的完整版，不会是半截 JSON。

分区结构（顶层每个键归一个功能模块所有，互不覆盖）::

    {
      "schemaVersion": 1,
      "lexicon": {"银行": ["yín", "xíng"]},    # custom_pronunciation
      "words":   {},                           # srs_review（T04 填）
      "stats":   {},                           # learning_stats
      "saved_at": "2026-10-31T08:31:00+00:00"  # UTC，展示时再转本地时区
    }

新增分区不用改这里：`get_section()` / `set_section()` 认任意顶层键。
**接口说明见 `.team/store-api.md`**，M1 按那份文档调，别看着实现猜。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone

from .config import config_path

SCHEMA_VERSION = 1
STORE_NAME = "store.json"

# 同一进程里可能有两个模块同时写（比如面板按钮 + 定时任务），串行化一下。
_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# 路径与默认结构
# --------------------------------------------------------------------------
def store_path() -> str:
    """`store.json` 的绝对路径：与 `config.json` 同目录。

    走 `config_path()` 而不是自己拼 APPDATA，是为了白拿「HPP_CONFIG_DIR 开发期
    隔离」——`--config-dir .dev/M0` 一开，数据也跟着挪到那个目录，不碰用户的真数据。
    """
    return os.path.join(os.path.dirname(config_path()), STORE_NAME)


def default_data() -> dict:
    """空的 store 结构。所有读取都以此为基础补全，缺键不算错。"""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "lexicon": {},
        "words": {},
        "stats": {},
        "saved_at": "",
    }


# --------------------------------------------------------------------------
# 规范化：手改坏了、旧版本少键、类型不对，都在这里兜住
# --------------------------------------------------------------------------
def _clean_lexicon(raw) -> dict:
    """`{词: [音节, ...]}`：丢掉空词、空音节、非列表值，字符串按空格拆。"""
    out = {}
    if not isinstance(raw, dict):
        return out
    for word, syllables in raw.items():
        if not isinstance(word, str) or not word.strip():
            continue
        if isinstance(syllables, str):
            syllables = syllables.split()
        if not isinstance(syllables, (list, tuple)):
            continue
        cleaned = []
        for item in syllables:
            text = str(item).strip()
            if text:
                cleaned.append(text)
        if cleaned:
            out[word.strip()] = cleaned
    return out


def _normalize(data) -> dict:
    """把任意输入整成一份可用的 store：缺的补、坏的换、别的模块的分区原样留着。"""
    base = default_data()
    if not isinstance(data, dict):
        return base
    out = dict(base)
    out.update(data)                     # 未知顶层键（别的模块的分区）不许丢
    try:
        out["schemaVersion"] = int(data.get("schemaVersion", SCHEMA_VERSION) or SCHEMA_VERSION)
    except (TypeError, ValueError):
        out["schemaVersion"] = SCHEMA_VERSION
    out["lexicon"] = _clean_lexicon(data.get("lexicon"))
    for key in ("words", "stats"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    if not isinstance(out.get("saved_at"), str):
        out["saved_at"] = ""
    return out


def _quarantine(path: str, exc: Exception) -> None:
    """坏文件改名留证：用户下次启动还能用，我们也能拿到现场。"""
    bad = path + ".bad"
    try:
        os.replace(path, bad)
        print(f"[warn] store 文件损坏，已备份为 {os.path.basename(bad)}：{exc}", file=sys.stderr)
    except Exception:
        print(f"[warn] store 文件损坏且无法备份：{exc}", file=sys.stderr)


# --------------------------------------------------------------------------
# 读写
# --------------------------------------------------------------------------
def load(path: str | None = None) -> dict:
    """读 store。文件不存在 / 内容坏掉都返回默认结构，**永不抛异常**。"""
    path = path or store_path()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
    except FileNotFoundError:
        return default_data()
    except Exception as exc:              # JSON 坏、权限、编码错，一律按坏文件处理
        _quarantine(path, exc)
        return default_data()
    return _normalize(raw)


def save(data: dict, path: str | None = None) -> bool:
    """原子写 store，返回是否成功。写 `.tmp` → fsync → os.replace，不抛异常。"""
    path = path or store_path()
    payload = _normalize(data)
    payload["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
        return True
    except Exception as exc:
        print(f"[warn] 保存 store 失败：{exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------
# 分区读写（任意顶层键，给后面的模块留口子）
# --------------------------------------------------------------------------
def get_section(name: str, path: str | None = None, default=None):
    """取一个顶层分区；不存在就返回 `default`。"""
    data = load(path)
    value = data.get(name)
    return default if value is None else value


def set_section(name: str, value, path: str | None = None) -> bool:
    """覆盖写一个顶层分区，其余分区原样保留。"""
    path = path or store_path()
    with _LOCK:
        data = load(path)
        data[name] = value
        return save(data, path)


# --------------------------------------------------------------------------
# 自定义读音词库（custom_pronunciation 的专属分区）
# --------------------------------------------------------------------------
def get_lexicon(path: str | None = None) -> dict:
    """`{词: [带调音节, ...]}`，返回副本，调用方随便改。"""
    return dict(load(path).get("lexicon") or {})


def set_lexicon(entries: dict, path: str | None = None, replace: bool = False) -> dict:
    """写入词条（默认合并），返回写完之后**完整**的词库。

    replace=True 表示「这份就是全部」，用于面板里删条目后整体同步。
    """
    path = path or store_path()
    with _LOCK:
        data = load(path)
        current = {} if replace else dict(data.get("lexicon") or {})
        current.update(_clean_lexicon(entries))
        data["lexicon"] = current
        save(data, path)
        return dict(current)


def remove_lexicon(word: str, path: str | None = None) -> bool:
    """删一条词条，返回是否真的删掉了（本来就没有 → False）。"""
    path = path or store_path()
    with _LOCK:
        data = load(path)
        current = dict(data.get("lexicon") or {})
        if word not in current:
            return False
        current.pop(word, None)
        data["lexicon"] = current
        save(data, path)
        return True
