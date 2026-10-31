"""全局常量：应用标识、版本、端口、汉字正则。

VERSION 是唯一来源，README / 打包脚本 / 设置页都从这里取，避免多处漂移。
"""
from __future__ import annotations

import os
import re

HANZI_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
APP_NAME = "HanziPinyinPopup"
APP_TITLE = "汉字拼音浮窗"
VERSION = "1.2.2"
CONFIG_SCHEMA = 5
SINGLE_INSTANCE_PORT = 47653
PROJECT_URL = "https://github.com/LVE0CL/hanzi_pinyin"


def single_instance_port() -> int:
    """单实例端口。

    HPP_PORT 可覆盖默认端口——开发时同时开好几个实例（比如三个人各调各的
    模块），不覆盖的话第二个实例只会把 "show" 发给第一个然后自己退出。
    """
    try:
        return int(os.environ.get("HPP_PORT") or SINGLE_INSTANCE_PORT)
    except (TypeError, ValueError):
        return SINGLE_INSTANCE_PORT
