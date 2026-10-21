"""GitHub 仓库通道：元数据 + README + 图片 → content.md + images/ + figures.json。

出口和 arxiv 通道同构：优先走环境代理、失败回退直连；带可重试状态码的退避重试。
GitHub REST API 对匿名请求有 60 次/小时的限流（共享代理 IP 经常已被打满），所以
优先用 GITHUB_TOKEN / GH_TOKEN，其次从已登录的 gh CLI 取 token，最后才匿名。

只打官方 API（api.github.com）与原始文件（raw.githubusercontent.com），不抓 HTML 页面。
产出与 PDF/知乎通道同形状，下游（understand / article / poster）无需感知来源。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import httpx

from . import pdf_parser

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
UA = "PaperCast/0.1 (github intake; +https://github.com/yydhYYDH/PaperCast)"
RETRYABLE_STATUS = frozenset({403, 408, 425, 429, 500, 502, 503, 504})
ATTEMPTS = 4
TIMEOUT = 30.0

REPO_RE = re.compile(r"(?:github\.com[:/])?([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[#/?].*)?$", re.I)
MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>", re.I)
BADGE_HINT = ("badge", "shields.io", "badgen", "codecov", "travis-ci", "github/workflows", "visitor", "star-history")


def normalize_repo(value: str) -> tuple[str, str]:
    """把各种写法归一成 (owner, repo)。"""
    v = (value or "").strip()
    v = re.sub(r"^git@github\.com:", "", v)
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    m = REPO_RE.search(v)
    if not m:
        raise ValueError(f"无法识别的 GitHub 仓库：{value!r}")
    return m.group(1), m.group(2)


def _token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(key)
        if v:
            return v.strip()
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    h = {"User-Agent": UA, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    tok = _token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _client(timeout: float, *, trust_env: bool) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=trust_env)


async def _get(url: str, *, accept: str = "application/vnd.github+json", timeout: float = TIMEOUT) -> httpx.Response:
    """直连优先、失败回退代理；可重试状态码退避重试。"""
    last: Exception | None = None
    for trust_env in (True, False):
        async with _client(timeout, trust_env=trust_env) as client:
            for i in range(ATTEMPTS):
                try:
                    resp = await client.get(url, headers=_headers(accept))
                except httpx.TransportError as e:
                    last = e
                else:
                    if resp.status_code not in RETRYABLE_STATUS:
                        return resp
                    last = httpx.HTTPStatusError(
                        f"GitHub 返回 {resp.status_code}（重试 {i + 1}/{ATTEMPTS}）",
                        request=resp.request, response=resp,
                    )
                if i < ATTEMPTS - 1:
                    import asyncio

                    await asyncio.sleep(1.2 * (2**i))
    assert last is not None
    raise last


async def _download(url: str, dest: Path) -> bool:
    try:
        resp = await _get(url, accept="application/octet-stream", timeout=60.0)
    except Exception:
        return False
    if resp.status_code != 200 or not resp.content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return 0, 0


def _is_badge(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in BADGE_HINT)


def _raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"{RAW}/{owner}/{repo}/{branch}/{path.lstrip('/')}"


async def _grab_image(url: str, owner: str, repo: str, branch: str, images_dir: Path, index: int) -> tuple[str, int, int] | None:
    """下载一张图到 images/，返回 (相对路径, w, h)。失败返回 None。"""
    if _is_badge(url):
        return None
    resolved = url
    if not url.lower().startswith("http"):
        resolved = _raw_url(owner, repo, branch, url.split("#")[0].split("?")[0])
    name = Path(resolved.split("?")[0]).name or f"img{index}.png"
    name = re.sub(r"[^\w.\-]", "_", name)[:80]
    if not Path(name).suffix:
        name += ".png"
    dest = images_dir / name
    if not dest.exists() and not await _download(resolved, dest):
        return None
    w, h = _image_size(dest)
    if w < 40 or h < 40:
        dest.unlink(missing_ok=True)
        return None
    return f"images/{name}", w, h


async def parse_repo(repo_url: str, work: Path, *, log=None) -> tuple[object, dict]:
    """GitHub 仓库 → (ParseResult, meta)。"""
    def _log(level: str, msg: str) -> None:
        if log:
            log(level, msg)

    owner, repo = normalize_repo(repo_url)
    _log("info", f"归一化仓库：{owner}/{repo}")

    meta_resp = await _get(f"{API}/repos/{owner}/{repo}")
    meta_resp.raise_for_status()
    info = meta_resp.json()
    branch = info.get("default_branch") or "main"
    full_name = info.get("full_name") or f"{owner}/{repo}"

    # README（原始 markdown）
    readme = ""
    try:
        r = await _get(f"{API}/repos/{owner}/{repo}/readme", accept="application/vnd.github.raw")
        if r.status_code == 200:
            readme = r.text
    except Exception as e:
        _log("warn", f"README 获取失败，继续：{type(e).__name__}: {str(e)[:120]}")

    # 最新发布
    release = {}
    try:
        rr = await _get(f"{API}/repos/{owner}/{repo}/releases/latest")
        if rr.status_code == 200:
            release = rr.json()
    except Exception:
        pass

    # 文件树（用于挑图 / 列关键文档）
    tree_paths: list[str] = []
    try:
        tr = await _get(f"{API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
        if tr.status_code == 200:
            tree_paths = [n.get("path", "") for n in tr.json().get("tree", []) if n.get("type") == "blob"]
    except Exception:
        pass

    images_dir = work / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 正文：README 里的图片引用换成本地
    md = readme
    figures: list = []
    seen: set[str] = set()

    async def add(url: str, caption: str) -> str | None:
        res = await _grab_image(url, owner, repo, branch, images_dir, len(figures))
        if not res:
            return None
        rel, w, h = res
        if rel in seen:
            return rel
        seen.add(rel)
        figures.append(
            pdf_parser.Figure(
                id=f"img{len(figures)}", kind="img", number=str(len(figures) + 1),
                caption=caption or Path(rel).stem, file=rel, page=0, bbox=[],
                width=w, height=h, source="raster",
            )
        )
        return rel

    # README 图片（markdown + html）
    for m in MD_IMG_RE.finditer(readme):
        alt, url = m.group(1), m.group(2)
        rel = await add(url, alt)
        if rel:
            md = md.replace(m.group(0), f"![{alt}]({rel})")
    for m in HTML_IMG_RE.finditer(readme):
        url = m.group(1)
        rel = await add(url, "")
        if rel:
            md = md.replace(f'src="{url}"', f'src="{rel}"').replace(f"src='{url}'", f'src="{rel}"')

    # 仓库里可用的示意图（README 图少时补充，供卡片使用）
    if len(figures) < 3:
        candidates = [
            p for p in tree_paths
            if re.search(r"\.(png|jpg|jpeg|webp)$", p, re.I)
            and not re.search(r"icon|logo|mipmap|launcher|vendor|ggml|themes|test", p, re.I)
        ]
        # 优先带 les / sched / arch / overview / diagram / screenshot 的图
        candidates.sort(key=lambda p: (0 if re.search(r"les|sched|arch|overview|diagram|screenshot|banner", p, re.I) else 1, len(p)))
        for p in candidates[:5]:
            if len(figures) >= 6:
                break
            url = _raw_url(owner, repo, branch, p)
            await add(url, Path(p).stem)

    # 组装 content.md
    stars = info.get("stargazers_count") or 0
    forks = info.get("forks_count") or 0
    license_id = (info.get("license") or {}).get("spdx_id") or ""
    topics = info.get("topics") or []
    parts = [
        f"# {full_name}",
        "",
        info.get("description") or "",
        "",
        f"**仓库**：{info.get('html_url') or f'https://github.com/{full_name}'}",
        f"**Star**：{stars} · **Fork**：{forks} · **主语言**：{info.get('language') or '—'}"
        + (f" · **许可**：{license_id}" if license_id else ""),
    ]
    if topics:
        parts.append("**Topics**：" + ", ".join(topics))
    if release:
        rname = release.get("name") or release.get("tag_name") or ""
        parts.append(f"**最新发布**：{release.get('tag_name', '')} — {rname}（{(release.get('published_at') or '')[:10]}）")
    parts.append(f"**活跃度**：创建于 {(info.get('created_at') or '')[:10]}，最近推送 {(info.get('pushed_at') or '')[:10]}")
    if info.get("homepage"):
        parts.append(f"**主页**：{info.get('homepage')}")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(md)

    # 关键文档清单（补充上下文，保证正文体量）
    doc_files = [p for p in tree_paths if p.startswith("docs/") and p.lower().endswith(".md")]
    if doc_files:
        parts += ["", "---", "", "## 仓库文档索引", ""]
        parts += [f"- `{p}`" for p in sorted(doc_files)[:40]]

    content = "\n".join(parts)

    (work / "content.md").write_text(content, encoding="utf-8")
    (work / "figures.json").write_text(
        __import__("json").dumps([f.as_dict() for f in figures], ensure_ascii=False, indent=1), encoding="utf-8"
    )

    title = full_name
    desc = (info.get("description") or "").strip()
    if desc:
        title = f"{full_name}：{desc}"

    parsed = pdf_parser.ParseResult(
        meta={
            "pdfTitle": title[:160],
            "pdfAuthor": owner,
            "sourceUrl": info.get("html_url") or f"https://github.com/{full_name}",
        },
        markdown=content, figures=figures, sections=[], warnings=[],
    )
    gh_meta = {
        "fullName": full_name,
        "description": desc,
        "stars": stars,
        "forks": forks,
        "language": info.get("language") or "",
        "license": license_id,
        "topics": topics,
        "homepage": info.get("homepage") or "",
        "createdAt": (info.get("created_at") or "")[:10],
        "pushedAt": (info.get("pushed_at") or "")[:10],
        "defaultBranch": branch,
        "release": {"tag": release.get("tag_name", ""), "name": release.get("name", ""),
                    "publishedAt": (release.get("published_at") or "")[:10]} if release else None,
        "textChars": len(content),
        "images": len(figures),
    }
    _log("ok", f"仓库解析完成：{full_name} / {stars}★ / {len(content)} 字 / {len(figures)} 图")
    return parsed, gh_meta
