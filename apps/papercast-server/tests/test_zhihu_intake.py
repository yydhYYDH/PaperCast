"""知乎源 intake 的契约测试：把抓取脚本的产出映射成与 PDF 同形状的解析结果。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import models
from app.modules import intake as intake_mod


def _fake_run_factory(captured: dict):
    def fake_run(cmd, capture_output=True, text=True, timeout=0):
        out_dir = Path(cmd[cmd.index("-o") + 1])
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        meta = {
            "url": cmd[2],
            "title": "知乎测试标题够长了吧",
            "author": "作者",
            "textChars": 2000,
            "images": [
                {"src": "https://pic.example/a.jpg", "w": 1080, "h": 600,
                 "file": "images/img00.jpg", "alt": "图A"},
            ],
        }
        (out_dir / "article.md").write_text(
            "# 知乎测试标题够长了吧\n\n正文一段。\n\n![img0](https://pic.example/a.jpg)\n", encoding="utf-8"
        )
        (out_dir / "images" / "img00.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(meta, ensure_ascii=False), stderr="")

    return fake_run


def test_fetch_zhihu_source_maps_to_parse_result(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))

    src = models.SourceInput(kind="zhihu", value="https://zhuanlan.zhihu.com/p/123")
    parsed, meta = intake_mod._fetch_zhihu_source(src, tmp_path, lambda *a, **k: None)

    assert captured["cmd"][2] == "https://zhuanlan.zhihu.com/p/123"
    assert parsed.meta["pdfTitle"] == "知乎测试标题够长了吧"
    # 远程图片引用被改成本地 images/ 路径
    assert "](images/img00.jpg)" in parsed.markdown
    assert "https://pic.example/a.jpg" not in parsed.markdown
    # figures 与 PDF 通道同形状
    assert len(parsed.figures) == 1
    f = parsed.figures[0]
    assert f.file == "images/img00.jpg" and f.width == 1080 and f.height == 600
    # 解析器该写的产物都写了，且图片已落盘
    assert (tmp_path / "content.md").is_file()
    assert (tmp_path / "figures.json").is_file()
    assert (tmp_path / "images" / "img00.jpg").is_file()


def test_fetch_zhihu_source_accepts_bare_id(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured))
    src = models.SourceInput(kind="zhihu", value="2089744357020770674")
    intake_mod._fetch_zhihu_source(src, tmp_path, lambda *a, **k: None)
    assert captured["cmd"][2] == "https://zhuanlan.zhihu.com/p/2089744357020770674"


def test_fetch_zhihu_source_rejects_non_zhihu_url(tmp_path):
    src = models.SourceInput(kind="url", value="https://example.com/post/1")
    with pytest.raises(intake_mod.IntakeError) as ei:
        intake_mod._fetch_zhihu_source(src, tmp_path, lambda *a, **k: None)
    assert ei.value.code == "URL_UNSUPPORTED"
