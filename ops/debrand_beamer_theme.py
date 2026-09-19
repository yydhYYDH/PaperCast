#!/usr/bin/env python3
r"""把 SUSTech beamer 主题去品牌化，产出 ops/beamer-theme-papercast/。

改动（相对上游 reference/upstream/sustech-slides-template）：
  1. 包名/宏名/颜色名 sustech -> papercast（文件名同步）；
  2. 默认不使用校徽（\setlogo{}）；
  3. 默认出处行置空（\setcreditline{}）；
  4. 保留上游版权与许可声明（Apache-2.0, Copyright (c) 2026 杨昊波）并在文件头注明本 fork。
"""
import pathlib
import re
import shutil

WS = pathlib.Path(__file__).resolve().parents[1]
SRC = WS / "var/runs/run_a7b9460d3953/video/论文分享/arXiv 2025 - PAPER2VIDEO/slides-beamer"
UPSTREAM = WS / "reference/upstream/sustech-slides-template"
DST = WS / "ops/beamer-theme-papercast"
FILES = [
    "beamerthemesustech.sty",
    "beamercolorthemesustech.sty",
    "beamerthemesustech-elements.sty",
]
HEADER = """% ---------------------------------------------------------------------------
% 本文件是 __ORIG__ 的去品牌化 fork（PaperCast 论文分享流水线使用）。
% 上游：github.com/yhbcode000/sustech-slides-template，Apache-2.0，
%       Copyright (c) 2026 杨昊波 (Haobo Yang)。许可证全文见同目录 LICENSE-upstream。
% 本 fork 的改动：包名/宏名/颜色名 sustech -> papercast；默认不显示校徽与出处行。
% ---------------------------------------------------------------------------
"""


def transform(text: str, orig_name: str) -> str:
    text = text.replace("SUSTech", "PaperCast").replace("Sustech", "PaperCast")
    text = text.replace("sustech", "papercast")
    text = text.replace("papercast-slides-template", "sustech-slides-template")  # 上游 URL 保持真实
    text = re.sub(r"\\setlogo\{papercast_logo\}", r"\\setlogo{}", text)
    text = re.sub(r"\\setcreditline\{[^}]*\}", r"\\setcreditline{}", text)
    return HEADER.replace("__ORIG__", orig_name) + text


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src = SRC / name
        if not src.exists():
            raise SystemExit(f"缺文件：{src}")
        new_name = name.replace("sustech", "papercast")
        (DST / new_name).write_text(transform(src.read_text(encoding="utf-8"), name), encoding="utf-8")
        print(f"{name} -> {new_name}")
    shutil.copy2(UPSTREAM / "LICENSE", DST / "LICENSE-upstream")
    print("已复制上游 LICENSE -> LICENSE-upstream")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
