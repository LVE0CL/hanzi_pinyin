"""全局常量：应用标识、版本、端口、汉字正则。

VERSION 是唯一来源，README / 打包脚本 / 设置页都从这里取，避免多处漂移。
"""
from __future__ import annotations

import re

HANZI_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
APP_NAME = "HanziPinyinPopup"
APP_TITLE = "汉字拼音浮窗"
VERSION = "1.2.1"
CONFIG_SCHEMA = 4
SINGLE_INSTANCE_PORT = 47653
PROJECT_URL = "https://github.com/LVE0CL/hanzi_pinyin"
