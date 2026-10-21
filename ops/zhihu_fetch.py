#!/usr/bin/env python3
"""抓知乎文章正文 + 图片（像论文一样当素材用）。

知乎文章页要登录态 + 浏览器渲染（直连返回 403），所以走 Playwright + 本仓库的
知乎登录 cookie（`var/secrets/zhihu/cookies.json`），复用 `reference/upstream/zhihu-mcp`
的 `browser.manager`。图片取 `currentSrc`（懒加载真图在 data-original/currentSrc），
按 naturalWidth 过滤头像。

产物（默认落 var/state/zhihu-fetch/<文章id>/）：
    article.md    正文（图片按出现位置内嵌 ![imgNN](src)）
    images/       下载好的正文图片
    meta.json     title/author/url/textChars/images[]（含 src/文件/宽高）

用法：
    ./ops/zhihu_fetch.py <url> [-o OUT] [--no-download] [--json] [--headed]
说明：不需要手动激活 venv —— 脚本会自己用 var/toolchains/zhihu-mcp-venv 解释器重跑。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
ZHIHU_REPO = WS / "reference" / "upstream" / "zhihu-mcp"
ZHIHU_VENV_PY = WS / "var" / "toolchains" / "zhihu-mcp-venv" / "bin" / "python"
DEFAULT_COOKIES = WS / "var" / "secrets" / "zhihu" / "cookies.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# 正文抽取的 JS：递归 walk，遇到 img 就按出现顺序内嵌 markdown，并过滤小图（头像）。
EXTRACT_JS = """() => {
  const root = document.querySelector('.Post-RichText, .RichText, .ArticleItem-content, article') || document.body;
  const minW = __MIN_W__;
  const imgs = [];
  const blockTags = ['p','div','section','h1','h2','h3','h4','li','blockquote','figure','tr'];
  function walk(node, out) {
    node.childNodes.forEach((n) => {
      if (n.nodeType === 3) { out.push(n.textContent); return; }
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'noscript') return;
      if (tag === 'img') {
        const src = n.currentSrc || n.src || n.getAttribute('data-original') || '';
        if (!src || src.startsWith('data:')) return;
        if ((n.naturalWidth || 0) < minW) return;  // 过滤头像/小图标
        let idx = imgs.findIndex((x) => x.src === src);
        if (idx < 0) { imgs.push({src, w: n.naturalWidth || 0, h: n.naturalHeight || 0, alt: n.alt || ''}); idx = imgs.length - 1; }
        out.push('\\n\\n![img' + idx + '](' + src + ')\\n\\n');
        return;
      }
      const block = blockTags.includes(tag);
      if (block) out.push('\\n');
      walk(n, out);
      if (block) out.push('\\n');
    });
  }
  const out = [];
  walk(root, out);
  const text = out.join('').replace(/[ \\t]+\\n/g, '\\n').replace(/\\n{3,}/g, '\\n\\n').trim();
  const author = (document.querySelector('.AuthorInfo-name, .AuthorInfo .UserLink-link') || {}).innerText || '';
  const title = (document.querySelector('.Post-Title') || {}).innerText || document.title;
  return { title, author, text, images: imgs, url: location.href };
}"""


def log(msg: str) -> None:
    print(f"[zhihu_fetch] {msg}", file=sys.stderr, flush=True)


def _ensure_runtime() -> None:
    """把 upstream 仓库加进 sys.path；缺 playwright 时用仓库自带的 venv 重跑自己。"""
    if str(ZHIHU_REPO) not in sys.path:
        sys.path.insert(0, str(ZHIHU_REPO))
    os.environ.setdefault("COOKIES_PATH", str(DEFAULT_COOKIES))
    try:
        import playwright  # noqa: F401
        return
    except Exception:
        pass
    # venv 的 bin/python 是指向同一 miniconda 的软链，resolve() 后路径相同，
    # 不能用 resolve 比较；用环境变量标记防止重跑成死循环。
    if ZHIHU_VENV_PY.exists() and not os.environ.get("ZHIHU_FETCH_REEXEC"):
        log(f"当前解释器没有 playwright，改用 {ZHIHU_VENV_PY} 重跑")
        env = dict(os.environ, ZHIHU_FETCH_REEXEC="1")
        os.execve(str(ZHIHU_VENV_PY), [str(ZHIHU_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], env)
    raise SystemExit("缺少 playwright，且找不到 var/toolchains/zhihu-mcp-venv（先 ./ops/install.sh）")


def article_id(url: str) -> str:
    seg = url.rstrip("/").split("/")[-1].split("?")[0]
    return seg or "article"


def download_images(images: list[dict], out_dir: Path, referer: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, im in enumerate(images):
        src = im["src"]
        ext = os.path.splitext(src.split("?")[0])[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
        name = f"img{i:02d}{ext}"
        try:
            req = urllib.request.Request(src, headers={"User-Agent": UA, "Referer": referer})  # noqa: S310
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                (out_dir / name).write_bytes(resp.read())
            im["file"] = f"images/{name}"
        except Exception as exc:  # 单张失败不影响其它
            im["error"] = f"{type(exc).__name__}: {exc}"
            log(f"图片 {i} 下载失败：{im['error']}")


def fetch(url: str, out: Path, headless: bool, min_w: int) -> dict:
    _ensure_runtime()
    from browser.manager import create_browser  # type: ignore[import-not-found]

    with create_browser(headless=headless) as (_b, _ctx, page):
        page.set_default_timeout(30000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        data = page.evaluate(EXTRACT_JS.replace("__MIN_W__", str(min_w)))

    meta = {
        "url": url,
        "title": (data.get("title") or "").strip(),
        "author": (data.get("author") or "").strip(),
        "fetchedAt": int(datetime.now().timestamp()),
        "textChars": len(data.get("text") or ""),
        "images": data.get("images") or [],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "article.md").write_text(
        f"# {meta['title']}\n\n{data.get('text','')}\n", encoding="utf-8"
    )
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="抓知乎文章正文+图片")
    ap.add_argument("url", help="知乎文章链接（zhuanlan.zhihu.com/p/...）")
    ap.add_argument("-o", "--out", default=None, help="输出目录（默认 var/state/zhihu-fetch/<id>）")
    ap.add_argument("--no-download", action="store_true", help="只抓不下载图片")
    ap.add_argument("--headed", action="store_true", help="有头浏览器（排查用）")
    ap.add_argument("--min-image-width", type=int, default=200, help="小于该宽度的图当头像过滤，默认 200")
    ap.add_argument("--json", action="store_true", help="stdout 打印 meta JSON")
    args = ap.parse_args()

    out = Path(args.out) if args.out else WS / "var" / "state" / "zhihu-fetch" / article_id(args.url)
    meta = fetch(args.url, out, headless=not args.headed, min_w=args.min_image_width)
    if not args.no_download and meta["images"]:
        download_images(meta["images"], out / "images", referer=args.url)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"标题：{meta['title']}")
    log(f"正文：{meta['textChars']} 字 -> {out / 'article.md'}")
    log(f"图片：{len(meta['images'])} 张 -> {out / 'images'}")
    if args.json:
        print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
