"""拼音核心：过滤、注音、多音字消歧、标调转换。

纯计算，不碰任何 Tk 控件，可在子线程安全调用。
"""
from __future__ import annotations

import sys

from .constants import HANZI_RE

try:
    from pypinyin import Style, pinyin as pinyin_of
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 pypinyin，请先执行：pip install -r requirements.txt")


def convert_reading(reading: str, style: str) -> str:
    """把带调拼音（hàn）转成数字调（han4）或无声调（han）。"""
    if not reading or style == "symbol":
        return reading
    try:
        from pypinyin.contrib.tone_convert import to_normal, to_tone3
    except Exception:
        return reading
    try:
        return to_tone3(reading) if style == "num" else to_normal(reading)
    except Exception:
        return reading


# --------------------------------------------------------------------------
# 拼音分析
# --------------------------------------------------------------------------
_COMMON_PAIRS = None


def common_pairs() -> set:
    """pypinyin 的 heteronym 会列出很多生僻又音（"之" → zhī/zhū/zhì）。

    用它的词组词典反查一遍，只保留现代汉语里真实用到的读音。
    """
    global _COMMON_PAIRS
    if _COMMON_PAIRS is None:
        pairs = set()
        try:
            from pypinyin.phrases_dict import phrases_dict

            for word, readings in phrases_dict.items():
                if len(word) != len(readings):
                    continue
                for ch, rs in zip(word, readings):
                    for r in rs:
                        pairs.add((ch, r))
        except Exception:
            pass
        _COMMON_PAIRS = pairs
    return _COMMON_PAIRS


# FR1：只放行「中文 + 标点」，其余字符（英文、数字、符号、emoji、空白）过滤掉
ALLOWED_PUNCT = set(
    "，。！？；：、（）《》〈〉「」『』【】〔〕—－…～·"
    ",.!?;:()[]{}<>'\"-+*/=%&@#|^`$"
)


def filter_text(text: str, enabled: bool = True) -> str:
    """FR1 缺陷修复：把非中文/非标点的字符滤掉。

    "Hello 你好 123！" → "你好！"：标点原样保留、不参与注音，英文数字不报错不串行。
    enabled=False 时原样返回（此时英文数字仍只是展示，不注音）。
    """
    if not enabled or not text:
        return text
    return "".join(
        ch for ch in text if HANZI_RE.match(ch) or ch in ALLOWED_PUNCT
    ).strip()


def analyze(text: str, tone_style: str = "symbol", filter_non_han: bool = True) -> list:
    """把一段文字拆成 [{char, readings}]，非汉字（连续的一段）合并为一项。

    readings[0] 是**结合上下文**得到的主读音（"重庆"的"重"读 chóng），
    后面跟的是该字的其他常见读音（多音字）。
    tone_style 只影响输出的写法（hàn / han4 / han），消歧与过滤始终按带调进行。
    filter_non_han=True 时先做 FR1 过滤，英文/数字/emoji 不参与注音也不显示。
    """
    text = filter_text(text, filter_non_han)
    chars = [ch for ch in text if ch not in "\r\n\t"]
    if not chars:
        return []

    # 整句一起送进去，pypinyin 才会用词组词典消歧
    try:
        contextual = pinyin_of("".join(chars), style=Style.TONE, heteronym=False)
    except Exception:
        contextual = []

    items = []
    buffer = ""  # 连续的非汉字
    for idx, ch in enumerate(chars):
        if not HANZI_RE.match(ch):
            buffer += ch
            continue
        if buffer:
            items.append({"char": buffer, "readings": []})
            buffer = ""

        try:
            readings = pinyin_of(ch, style=Style.TONE, heteronym=True)[0]
        except Exception:
            readings = []
        uniq = []
        for r in readings:
            if r and r != ch and r not in uniq:
                uniq.append(r)

        # 只留下词组词典里出现过的读音，过滤掉生僻又音
        pairs = common_pairs()
        if pairs and uniq:
            kept = [r for r in uniq if (ch, r) in pairs]
            uniq = kept or uniq[:1]

        primary = ""
        if idx < len(contextual) and contextual[idx]:
            cand = contextual[idx][0]
            if cand and cand != ch:
                primary = cand
        if not primary and uniq:
            primary = uniq[0]
        if primary:
            uniq = [primary] + [r for r in uniq if r != primary]
        if tone_style != "symbol" and uniq:
            uniq = [convert_reading(r, tone_style) for r in uniq]

        items.append({"char": ch, "readings": uniq[:3]})

    if buffer:
        items.append({"char": buffer, "readings": []})
    return items


def pinyin_plain(items: list) -> str:
    out = []
    for it in items:
        out.append(it["readings"][0] if it["readings"] else it["char"])
    return " ".join(x for x in out if x.strip())


def pinyin_pairs(items: list) -> str:
    lines = []
    for it in items:
        if it["readings"]:
            lines.append(f"{it['char']}\t{it['readings'][0]}")
        elif it["char"].strip():
            lines.append(it["char"].strip())
    return "\n".join(lines)
