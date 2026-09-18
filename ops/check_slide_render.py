#!/usr/bin/env python3
"""检测「文本层有字、但渲染出来是空白」的 span（即真正没显示出来的字）。"""
import pathlib, sys
import pymupdf
from PIL import Image

DECK = pathlib.Path(sys.argv[1]).resolve()
doc = pymupdf.open(DECK / "main.pdf")
frame_dir = DECK.parent / "video" / "video_frames"

def ink_ratio(img, box):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.width), min(y1, img.height)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = img.crop((x0, y0, x1, y1)).convert("L")
    px = list(crop.getdata())
    return sum(1 for v in px if v < 200) / len(px)

pages = [int(x) for x in sys.argv[2:]] or list(range(1, doc.page_count + 1))
bad_total = 0
for pno in pages:
    page = doc[pno - 1]
    png = frame_dir / f"slide_{pno:03d}.png"
    if not png.is_file():
        print(f"page {pno}: no frame png"); continue
    img = Image.open(png)
    sx, sy = img.width / page.rect.width, img.height / page.rect.height
    d = page.get_text("dict")
    bad, spans = [], 0
    for block in d["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                spans += 1
                x0, y0, x1, y1 = span["bbox"]
                ratio = ink_ratio(img, (x0 * sx - 1, y0 * sy - 1, x1 * sx + 1, y1 * sy + 1))
                if ratio is not None and ratio < 0.005:
                    bad.append((text[:30], span["font"], round(ratio, 4)))
    if bad:
        bad_total += len(bad)
        print(f"page {pno}: {len(bad)}/{spans} 个 span 渲染为空 -> {bad[:6]}")
print("total invisible spans:", bad_total)
