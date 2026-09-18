"""arXiv 通道：元数据 + PDF + 源码包。

只打官方 API（export.arxiv.org / arxiv.org），不抓 HTML 页面（易被反爬、结构漂移）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import httpx

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

ID_RE = re.compile(
    r"(?:arxiv[:/])?\s*(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?",
    re.I,
)


def normalize(value: str) -> tuple[str, str]:
    """把各种写法归一成 (arxivId, version)。

    接受：2510.05096 / arXiv:2510.05096 / https://arxiv.org/abs/2510.05096v2
          / https://arxiv.org/pdf/2510.05096 / hep-th/9901001
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("arXiv 输入为空")
    v = re.sub(r"^https?://(www\.)?arxiv\.org/(abs|pdf|e-print)/", "", v, flags=re.I)
    v = re.sub(r"\.pdf$", "", v, flags=re.I)
    m = ID_RE.search(v)
    if not m:
        raise ValueError(f"无法识别的 arXiv 标识：{value!r}")
    return m.group(1), (m.group(2) or "")


def _text(node, path: str) -> str:
    el = node.find(path)
    return (el.text or "").strip() if el is not None and el.text else ""


async def fetch_metadata(arxiv_id: str, *, timeout: float = 30.0) -> dict:
    """取标题 / 作者 / 摘要 / 日期 / 主分类。"""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cx:
        resp = await cx.get(API, params={"id_list": arxiv_id})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        raise RuntimeError(f"arXiv 未返回该论文：{arxiv_id}")
    title = re.sub(r"\s+", " ", _text(entry, f"{ATOM}title"))
    if not title:
        raise RuntimeError(f"arXiv 元数据为空：{arxiv_id}")
    authors = [
        re.sub(r"\s+", " ", (a.find(f"{ATOM}name").text or "").strip())
        for a in entry.findall(f"{ATOM}author")
        if a.find(f"{ATOM}name") is not None
    ]
    published = _text(entry, f"{ATOM}published")
    updated = _text(entry, f"{ATOM}updated")
    primary = entry.find(f"{ARXIV_NS}primary_category")
    return {
        "arxivId": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": re.sub(r"\s+", " ", _text(entry, f"{ATOM}summary")),
        "published": published,
        "updated": updated,
        "year": int(published[:4]) if published[:4].isdigit() else 0,
        "primaryCategory": primary.get("term") if primary is not None else "",
        "comment": re.sub(r"\s+", " ", _text(entry, f"{ARXIV_NS}comment")),
        "pdfUrl": f"https://arxiv.org/pdf/{arxiv_id}",
        "absUrl": f"https://arxiv.org/abs/{arxiv_id}",
    }


async def download_pdf(arxiv_id: str, dest: Path, *, version: str = "", timeout: float = 180.0) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/pdf/{arxiv_id}{version}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cx:
        async with cx.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes(1 << 16):
                    fh.write(chunk)
    if dest.stat().st_size < 8000 or dest.read_bytes()[:4] != b"%PDF":
        raise RuntimeError(f"arXiv 返回的不是有效 PDF：{url}")
    return dest


async def download_source(arxiv_id: str, dest: Path, *, timeout: float = 120.0) -> Optional[Path]:
    """下载源码包（可选，用于补强章节结构；失败不阻塞主流程）。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cx:
            resp = await cx.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        if dest.stat().st_size < 200:
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        return None


def unpack_source(archive: Path, out_dir: Path) -> Optional[Path]:
    """解包 .tar.gz / .gz / 单文件 .tex；返回源码目录。"""
    import gzip
    import shutil
    import tarfile

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive) as tf:
                for m in tf.getmembers():
                    if m.name.startswith(("/", "..")) or ".." in Path(m.name).parts:
                        continue  # 挡掉路径穿越
                tf.extractall(out_dir)
            return out_dir
        if archive.suffix == ".gz":
            target = out_dir / (archive.stem or "main.tex")
            with gzip.open(archive, "rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            return out_dir
    except Exception:
        return None
    return None
