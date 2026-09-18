"""小红书卡片图渲染（PIL，不依赖浏览器）。

为什么不用 headless Chrome：卡片的版式是固定的，PIL 直接画即可 —— 少一个浏览器进程、
不依赖 playwright、在只有 CPU 的服务器上更稳。样式控制在 CSS 之外，反而更容易复现。

卡片规格 1080×1440（3:4，小红书竖图标准）。
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
BG = (251, 249, 246)
INK = (26, 26, 26)
SUB = (120, 116, 110)
LINE = (226, 222, 214)
ACCENT = (232, 80, 58)
CARD_BORDER = (231, 227, 220)

def find_font(preferred: str = "") -> Optional[str]:
    """委托给 config.find_cjk_font：只认真的含中文字形的字体。"""
    from ..config import find_cjk_font

    return find_cjk_font(preferred) or None


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """按像素宽度折行；中文逐字断，英文按词断。"""
    lines, cur = [], ""
    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        if token.isspace():
            if cur:
                cur += " "
            continue
        # 英文长词整体放，中文逐字放
        units = [token] if re.fullmatch(r"[A-Za-z0-9\-_/\.]+", token) else list(token)
        for u in units:
            probe = cur + u
            if draw.textlength(probe, font=font) <= max_w or not cur:
                cur = probe
            else:
                lines.append(cur.rstrip())
                cur = u
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _fit_image(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """等比缩放到框内（小图最多放大 2 倍，避免糊）。"""
    iw, ih = img.size
    scale = min(box_w / iw, box_h / ih)
    scale = min(scale, 2.0)
    if scale != 1.0:
        img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
    return img


def render_card(
    *,
    out_path: Path,
    figure_path: Path,
    badge: str,
    headline: str,
    caption_cn: str,
    series: str,
    source_note: str,
    font_path: str,
) -> Optional[Path]:
    try:
        src = Image.open(figure_path).convert("RGB")
    except Exception:
        return None

    card = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(card)
    f_series = _font(font_path, 30)
    f_badge = _font(font_path, 30)
    f_head = _font(font_path, 52)
    f_cap = _font(font_path, 34)
    f_foot = _font(font_path, 26)

    # 顶部强调条
    d.rectangle([0, 0, W, 14], fill=ACCENT)
    d.text((64, 56), series, font=f_series, fill=SUB)
    if badge:
        bw = d.textlength(badge, font=f_badge)
        d.text((W - 64 - bw, 56), badge, font=f_badge, fill=ACCENT)

    # 卡片主标题
    y = 122
    for ln in _wrap(d, headline, f_head, W - 128)[:2]:
        d.text((64, y), ln, font=f_head, fill=INK, stroke_width=1, stroke_fill=INK)
        y += 68
    y += 14

    # 图区
    box_top, box_h = y, 1020 - y
    box_w = W - 128
    fitted = _fit_image(src, box_w - 24, box_h - 24)
    fw, fh = fitted.size
    fx = 64 + (box_w - fw) // 2
    fy = box_top + (box_h - fh) // 2
    d.rectangle([64, box_top, 64 + box_w, box_top + box_h], fill=(255, 255, 255), outline=CARD_BORDER, width=2)
    card.paste(fitted, (fx, fy))

    # 图注
    cy = box_top + box_h + 34
    for ln in _wrap(d, caption_cn, f_cap, W - 128)[:4]:
        d.text((64, cy), ln, font=f_cap, fill=(45, 45, 45))
        cy += 50

    # 页脚
    d.line([64, H - 96, W - 64, H - 96], fill=LINE, width=2)
    foot = _wrap(d, source_note, f_foot, W - 128)[0]
    d.text((64, H - 72), foot, font=f_foot, fill=SUB)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_path, "PNG", optimize=True)
    return out_path


def render_cards(
    picks: list[dict],
    figures_dir: Path,
    out_dir: Path,
    *,
    series: str,
    source_note: str,
    font_preferred: str = "",
) -> tuple[list[str], list[str]]:
    """picks: [{figureId, file, badge, headline, captionCn}]

    figures_dir 是 M1 的 intake 目录（图片在那里），out_dir 是 M2 的 article/cards
    —— 两者必须显式分开：之前靠一个 work_dir 猜，结果卡片写进了 intake/cards/，
    产物登记（相对 article/ 解析）全部落空。
    """
    font_path = find_font(font_preferred)
    if not font_path:
        return [], ["系统里找不到含中文字形的字体，卡片图未渲染（装 fonts-noto-cjk，或设 PAPERCAST_CJK_FONT 指向字体文件）"]
    from ..config import has_cjk_glyphs

    if not has_cjk_glyphs(font_path):
        return [], [f"字体 {font_path} 不含中文字形，卡片图未渲染（中文会变方块）"]
    out_dir = Path(out_dir)
    made, errors = [], []
    for i, p in enumerate(picks, 1):
        fig = Path(figures_dir) / p["file"]
        if not fig.is_file():
            errors.append(f"{p['figureId']}：找不到图文件 {p['file']}")
            continue
        out = out_dir / f"p{i}.png"
        ok = render_card(
            out_path=out,
            figure_path=fig,
            badge=p.get("badge", ""),
            headline=p.get("headline", "") or p.get("captionCn", "")[:20],
            caption_cn=p.get("captionCn", ""),
            series=series,
            source_note=source_note,
            font_path=font_path,
        )
        if ok:
            made.append(f"cards/{out.name}")
        else:
            errors.append(f"{p['figureId']}：渲染失败")
    return made, errors
