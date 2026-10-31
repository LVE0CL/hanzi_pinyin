"""图标：运行时用 Pillow 自绘（Tk 在 Windows 上不渲染 emoji）。"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 图标（运行时绘制，不依赖外部资源文件）
# --------------------------------------------------------------------------
def _cjk_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def make_app_image(size: int = 64):
    """应用图标：圆角方块 + 「拼」字。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.24), fill=(42, 122, 90, 255))
    font = _cjk_font(int(s * 0.62))
    if font is not None:
        try:
            box = d.textbbox((0, 0), "拼", font=font)
            w, h = box[2] - box[0], box[3] - box[1]
            d.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]), "拼",
                   font=font, fill=(255, 255, 255, 255))
        except Exception:
            pass
    return img.resize((size, size), Image.LANCZOS)


def make_gear_image(size: int = 18, color: str = "#8b939e"):
    """齿轮图标：圆环 + 8 个齿，运行时绘制。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = s / 2
    ring_r = s * 0.27
    inner_r = s * 0.31
    outer_r = s * 0.45
    width = max(2, int(s * 0.11))
    for i in range(8):
        ang = i * math.pi / 4 + math.pi / 8
        d.line(
            [cx + inner_r * math.cos(ang), cy + inner_r * math.sin(ang),
             cx + outer_r * math.cos(ang), cy + outer_r * math.sin(ang)],
            fill=color, width=width,
        )
    d.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
              outline=color, width=width)
    return img.resize((size, size), Image.LANCZOS)


def make_pin_image(size: int = 16, color: str = "#8f8f8f", filled: bool = False):
    """US14：图钉图标。filled=True 表示「已钉住」（实心高亮），否则描边。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    width = max(2, int(s * 0.10))
    head = [s * 0.28, s * 0.12, s * 0.72, s * 0.44]        # 钉帽（椭圆）
    body = [(s * 0.32, s * 0.40), (s * 0.68, s * 0.40), (s * 0.60, s * 0.60),
            (s * 0.40, s * 0.60)]
    if filled:
        d.ellipse(head, fill=color)
        d.polygon(body, fill=color)
        d.line([s * 0.5, s * 0.58, s * 0.5, s * 0.90], fill=color, width=width)
    else:
        d.ellipse(head, outline=color, width=width)
        d.line(body + [body[0]], fill=color, width=width, joint="curve")
        d.line([s * 0.5, s * 0.58, s * 0.5, s * 0.90], fill=color, width=width)
    return img.resize((size, size), Image.LANCZOS)


def make_caret_image(size: int = 9, color: str = "#8b939e"):
    """下拉箭头：向下的小三角。Tk 自带箭头在深色主题下会变成空白方块，故自绘。"""
    scale = 4
    w, h = size * scale, int(size * scale * 0.62)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 0), (w - 1, 0), (w / 2, h - 1)], fill=color)
    return img.resize((size, max(4, int(size * 0.62))), Image.LANCZOS)
