"""app/media_select.py：作品配图的手动增删（列候选 / 存 poster/selected.json）。

2026-10-02 用户反馈：发布面板里配图只能看不能改。这里钉住两条底线：
- 写进去的路径必须真实存在于 run 目录内（越界/不存在一律拒绝，不让投递吃到 run 外的文件）；
- 存了人工选择后，投递口径（modules/publish._pick_media）立刻认这套，而不是继续用自动顺序。
"""

from __future__ import annotations

import json

import pytest

from app import media_select


def _run_tree(tmp_path):
    """一条最简单的 run：两张组图 + 一张论文原图。"""
    run = tmp_path / "run_x"
    deck = run / "poster" / "cards" / "output"
    deck.mkdir(parents=True)
    for name in ("xhs-01.jpg", "xhs-02.jpg"):
        (deck / name).write_bytes(b"x")
    imgs = run / "intake" / "images"
    imgs.mkdir(parents=True)
    (imgs / "fig-1.png").write_bytes(b"x")
    return run


def test_list_media_reports_default_selection_as_chosen(tmp_path):
    run = _run_tree(tmp_path)
    data = media_select.list_media("run_x", run)
    assert data["hasSelection"] is False
    # 有组图时默认投组图（与 publish._pick_media 同口径）
    assert data["selected"] == ["poster/cards/output/xhs-01.jpg", "poster/cards/output/xhs-02.jpg"]
    chosen = [c["path"] for c in data["candidates"] if c["chosen"]]
    assert chosen == data["selected"]
    assert any(c["kind"] == "figure" and not c["chosen"] for c in data["candidates"])


def test_save_media_writes_selection_and_pick_media_honors_it(tmp_path):
    run = _run_tree(tmp_path)
    out = media_select.save_media("run_x", run, ["intake/images/fig-1.png", "poster/cards/output/xhs-02.jpg"])
    assert out["hasSelection"] is True
    saved = json.loads((run / "poster" / "selected.json").read_text(encoding="utf-8"))
    assert saved["images"] == ["intake/images/fig-1.png", "poster/cards/output/xhs-02.jpg"]

    # 投递口径立刻改用它（组图不再是默认那套）
    again = media_select.list_media("run_x", run)
    assert again["hasSelection"] is True
    assert again["selected"] == ["intake/images/fig-1.png", "poster/cards/output/xhs-02.jpg"]


def test_save_media_empty_resets_to_auto(tmp_path):
    run = _run_tree(tmp_path)
    media_select.save_media("run_x", run, ["intake/images/fig-1.png"])
    assert (run / "poster" / "selected.json").is_file()
    out = media_select.save_media("run_x", run, [])
    assert out["hasSelection"] is False
    assert not (run / "poster" / "selected.json").exists()
    # 恢复自动顺序 = 又回到组图那套
    assert media_select.list_media("run_x", run)["selected"][0].startswith("poster/cards/output/")


def test_save_media_rejects_traversal_and_missing(tmp_path):
    run = _run_tree(tmp_path)
    (tmp_path / "outside.png").write_bytes(b"x")
    with pytest.raises(ValueError):
        media_select.save_media("run_x", run, ["../outside.png"])
    with pytest.raises(ValueError):
        media_select.save_media("run_x", run, ["intake/images/nope.png"])
    # 校验失败不该写出半份 selected.json
    assert not (run / "poster" / "selected.json").exists()
