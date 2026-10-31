# -*- coding: utf-8 -*-
"""自定义读音词库：给某个词指定读音，优先级高于 pypinyin 的自动消歧。

「银行」pypinyin 会给 yín háng，可人名地名里常读 yín xíng；「重庆」在别人嘴里
可能是 chóng qìng 也可能是 zhòng qìng。这个模块让用户自己拍板，一个词一条，
存在 `store.json` 的 `lexicon` 分区里，下次启动照样生效。

实现上只借 `hpp/pinyin.py` 开好的三个口子（`register_lexicon` / `clear_lexicon` /
`lexicon_size`）——往 pypinyin 的词组词典里塞词条，`analyze()` 走的就是那条路，
所以不需要、也不允许改 `pinyin_plain()` 的默认行为。

结构：
    parse_entry()  两行输入 → (词, [音节])，错了给一句人话
    PronunciationPanel  内嵌面板：列表 + 增删
    CustomPronunciationFeature  挂点：attach / panel / on_text / self_check
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import tkinter as tk

from ... import store
from ...constants import HANZI_RE
from ...pinyin import (
    analyze,
    clear_lexicon,
    lexicon_size,
    pinyin_plain,
    register_lexicon,
)
from ..base import Feature

# 一个音节允许出现的字符：字母（含带调元音）+ 数字调号。
_SYLLABLE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "üāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜêńňǹḿ"
    "0123456789"
)

MAX_WORD_CHARS = 12


def _valid_syllable(text: str) -> bool:
    if not (1 <= len(text) <= 7):
        return False
    return all(ch in _SYLLABLE_CHARS for ch in text)


def parse_entry(word_text: str, reading_text: str) -> tuple:
    """面板两行输入 → `(词, [带调音节], 错误说明)`。错误说明非空即拒绝。

    三条规矩：只认汉字；音节数必须等于字数（pypinyin 的词组词典按字数对齐，
    多给少给都会静默失效）；音节得像个拼音。
    """
    word = (word_text or "").strip()
    if not word:
        return "", [], "先填要管的词"
    if len(word) > MAX_WORD_CHARS:
        return word, [], f"一次最多 {MAX_WORD_CHARS} 个字"
    bad = [ch for ch in word if not HANZI_RE.match(ch)]
    if bad:
        return word, [], "只认汉字，去掉：" + " ".join(bad)

    raw = (reading_text or "").replace("，", " ").replace(",", " ").strip()
    syllables = [s for s in re.split(r"\s+", raw) if s]
    if not syllables:
        return word, [], "再填读音，每个字一个，空格分开"
    if len(syllables) != len(word):
        return word, [], f"「{word}」{len(word)} 个字，这里给了 {len(syllables)} 个音节"
    for syllable in syllables:
        if not _valid_syllable(syllable.lower()):
            return word, [], f"「{syllable}」不像一个拼音音节"
    return word, [s.lower() for s in syllables], ""


class PronunciationPanel:
    """内嵌面板：词条列表 + 一行录入 + 删除按钮。

    刻意做得矮：主窗口高度是「内容 + 面板」算出来的，面板多占 20px，正文就少
    20px。所以列表只露 3 行（滚轮可以翻），错误提示复用同一行状态文字。
    """

    LIST_ROWS = 3

    def __init__(self, feature: "CustomPronunciationFeature", parent):
        self.feature = feature
        self.app = feature.app
        self.text = ""
        c = self.app.colors
        font_ui = self.app.font_ui

        self.frame = tk.Frame(parent, bg=c["panel"])

        head = tk.Frame(self.frame, bg=c["panel"])
        head.pack(fill="x")
        tk.Label(head, text="自定义读音", bg=c["panel"], fg=c["fg"],
                 font=font_ui).pack(side="left")
        self.count = tk.Label(head, text="", bg=c["panel"], fg=c["fg_dim"],
                              font=self.app.font_hint)
        self.count.pack(side="right")

        self.listbox = tk.Listbox(
            self.frame, height=self.LIST_ROWS, activestyle="none",
            bg=c["entry_bg"], fg=c["fg"], font=font_ui,
            selectbackground=c["hover"], selectforeground=c["fg"],
            highlightthickness=1, highlightbackground=c["border"],
            highlightcolor=c["accent"], borderwidth=0, relief="flat",
            exportselection=False,
        )
        self.listbox.pack(fill="x", pady=(3, 4))

        row = tk.Frame(self.frame, bg=c["panel"])
        row.pack(fill="x")
        self.word_var = tk.StringVar()
        self.read_var = tk.StringVar()
        self.word_entry = self._entry(row, self.word_var, width=5)
        self.word_entry.pack(side="left")
        self.read_entry = self._entry(row, self.read_var)
        self.read_entry.pack(side="left", fill="x", expand=True, padx=4)
        self._button(row, "添加", self._add, primary=True).pack(side="left")
        self._button(row, "删除", self._delete).pack(side="left", padx=(4, 0))

        self.status = tk.Label(self.frame, text="", bg=c["panel"],
                               fg=c["fg_dim"], font=self.app.font_hint, anchor="w")
        self.status.pack(fill="x", pady=(2, 0))

        for widget in (self.word_entry, self.read_entry):
            widget.bind("<Return>", lambda _e: self._add())
        self.refresh()
        self._say("例：银行 → yín xíng")

    # ---- 零件 ----
    def _entry(self, parent, var, width=None) -> tk.Entry:
        c = self.app.colors
        entry = tk.Entry(
            parent, textvariable=var, bg=c["entry_bg"], fg=c["fg"],
            insertbackground=c["fg"], disabledbackground=c["entry_bg"],
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=c["border"], highlightcolor=c["accent"],
            font=self.app.font_ui,
        )
        if width:
            entry.configure(width=width)
        return entry

    def _button(self, parent, text, command, primary=False) -> tk.Label:
        c = self.app.colors
        bg = c["accent"] if primary else c["panel_alt"]
        fg = c["accent_fg"] if primary else c["fg"]
        btn = tk.Label(parent, text=text, bg=bg, fg=fg, font=self.app.font_hint,
                       padx=8, pady=2, cursor="hand2")
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=c["hover"] if not primary else c["accent"]))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
        return btn

    def _say(self, message: str, error: bool = False) -> None:
        self.status.configure(text=message, fg=self.app.colors["danger"] if error else self.app.colors["fg_dim"])

    # ---- 数据 ----
    def _rows(self) -> list:
        return list(self.feature.entries.items())

    def refresh(self) -> None:
        """把 feature 里的词条重画到列表上，顺带标出「本句命中」的条。"""
        rows = self._rows()
        self.listbox.delete(0, "end")
        for word, syllables in rows:
            self.listbox.insert("end", f"{word}    {' '.join(syllables)}")
        if rows:
            self.count.configure(text=f"已录 {len(rows)} 条")
        else:
            self.listbox.insert("end", "（还没有词条，上面加一条试试）")
            self.count.configure(text="还没录词条")
        self._mark_hits()

    def _mark_hits(self) -> None:
        """当前文本里出现的词条高亮一下，省得用户自己一行行对。"""
        c = self.app.colors
        text = self.text or ""
        for idx, (word, _syllables) in enumerate(self._rows()):
            hit = word in text
            try:
                self.listbox.itemconfigure(
                    idx,
                    background=c["hover"] if hit else c["entry_bg"],
                    foreground=c["accent"] if hit else c["fg"],
                )
            except tk.TclError:
                pass

    def set_text(self, text: str) -> None:
        self.text = text or ""
        self._mark_hits()

    # ---- 动作 ----
    def _add(self) -> None:
        word, syllables, error = parse_entry(self.word_var.get(), self.read_var.get())
        if error:
            self._say(error, error=True)
            return
        entries = dict(self.feature.entries)
        entries[word] = syllables
        if not self.feature.commit(entries):
            self._say("写盘失败，这条没存下来", error=True)
            return
        self.word_var.set("")
        self.read_var.set("")
        self._say(f"已添加 {word} → {' '.join(syllables)}")
        self.word_entry.focus_set()

    def _delete(self) -> None:
        selection = self.listbox.curselection()
        rows = self._rows()
        if not selection or not rows:
            self._say("先在列表里点一条", error=True)
            return
        index = min(selection[0], len(rows) - 1)
        word = rows[index][0]
        entries = dict(self.feature.entries)
        entries.pop(word, None)
        if not self.feature.commit(entries):
            self._say("写盘失败，没删掉", error=True)
            return
        self._say(f"已删除 {word}，读音回到默认")


class CustomPronunciationFeature(Feature):
    key = "custom_pronunciation"
    label = "自定义读音词库"

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict = {}
        self.panel_widget = None
        self.applied = 0

    # ---- 生命周期 ----
    def attach(self, app) -> None:
        super().attach(app)
        self.entries = store.get_lexicon()
        self._apply()

    def panel(self, parent):
        self.panel_widget = PronunciationPanel(self, parent)
        return self.panel_widget.frame

    def on_text(self, text: str, items: list) -> None:
        if self.panel_widget is not None:
            self.panel_widget.set_text(text)

    # ---- 词条 → pypinyin ----
    def _apply(self) -> int:
        """先把上次注册的撤销，再把当前词条整体注册一遍。

        必须「整体重建」而不是「只加新的」：用户删词条时，只有 clear_lexicon()
        才能把 pypinyin 词典里的原值还回去（它记着每个词的原值）。
        """
        try:
            clear_lexicon()
        except Exception as exc:
            print(f"[warn] 撤销自定义读音失败：{exc}", file=sys.stderr)
        try:
            self.applied = register_lexicon(self.entries) if self.entries else 0
        except Exception as exc:
            print(f"[warn] 注册自定义读音失败：{exc}", file=sys.stderr)
            self.applied = 0
        return self.applied

    def commit(self, entries: dict) -> bool:
        """落盘 → 重建词库 → 重画面板 → 让主窗口重算读音。返回是否真的写进磁盘。"""
        store.set_lexicon(entries, replace=True)
        stored = store.get_lexicon()          # 回读一遍，不信内存里的乐观结果
        self.entries = stored
        self._apply()
        if self.panel_widget is not None:
            self.panel_widget.refresh()
        if self.app is not None:
            try:
                self.app.refresh()
            except Exception as exc:
                print(f"[warn] 刷新主窗口失败：{exc}", file=sys.stderr)
        return stored == {w: list(s) for w, s in (entries or {}).items() if s}

    # ---- 自检 ----
    def self_check(self) -> list:
        checks = []

        tmp = tempfile.mkdtemp(prefix="hpp-store-")
        try:
            path = os.path.join(tmp, "store.json")
            data = store.default_data()
            data["lexicon"] = {"银行": ["yín", "xíng"]}
            wrote = store.save(data, path)
            back = store.load(path).get("lexicon")
            checks.append(("store 原子写可回读",
                           wrote and back == {"银行": ["yín", "xíng"]}, back))

            with open(path, "w", encoding="utf-8") as fp:
                fp.write("{这不是 json")
            broken = store.load(path)
            checks.append(("坏 store 不崩且留证",
                           isinstance(broken, dict) and broken.get("lexicon") == {}
                           and os.path.exists(path + ".bad"),
                           broken.get("lexicon")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 覆盖 → 撤销，全在 finally 里把状态还原成本模块应有的样子（self_check
        # 会被 --selftest 在窗口没起来的时候调用，不能留下全局副作用）
        baseline = ""
        try:
            self._apply()
            baseline = pinyin_plain(analyze("银行"))
            register_lexicon({"银行": ["yín", "xíng"]})
            overridden = pinyin_plain(analyze("银行"))
            clear_lexicon()
            cleared = pinyin_plain(analyze("银行"))
        except Exception as exc:
            overridden, cleared = f"异常：{exc}", ""
        finally:
            self._apply()
            restored = pinyin_plain(analyze("银行"))

        checks.append(("词条覆盖 analyze 读音", overridden == "yín xíng",
                       f"{baseline} -> {overridden}"))
        checks.append(("删词条后读音回到默认", cleared == baseline, cleared))
        checks.append(("重建词库后读音不变", restored == baseline, restored))
        checks.append(("词库规模与词条数一致", lexicon_size() == len(self.entries),
                       f"{lexicon_size()}/{len(self.entries)}"))

        _word, _syllables, error = parse_entry("银行", "yín")
        checks.append(("音节数与字数不符时拒绝", bool(error), error))

        saved = os.environ.get("HPP_CONFIG_DIR")
        probe = tempfile.mkdtemp(prefix="hpp-env-")
        try:
            os.environ["HPP_CONFIG_DIR"] = probe
            target = store.store_path()
            ok = os.path.normcase(target) == os.path.normcase(os.path.join(probe, store.STORE_NAME))
        finally:
            if saved is None:
                os.environ.pop("HPP_CONFIG_DIR", None)
            else:
                os.environ["HPP_CONFIG_DIR"] = saved
            shutil.rmtree(probe, ignore_errors=True)
        checks.append(("store 跟随 HPP_CONFIG_DIR 隔离", ok, target))

        return checks


FEATURE = CustomPronunciationFeature
