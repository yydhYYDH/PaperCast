"""app/store.py：/artifacts 的目录穿越防护 + 上传落盘（纯本地磁盘，无网络）。"""

from __future__ import annotations

import json
import os

import pytest

from app.store import RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs", tmp_path / "uploads")


@pytest.fixture
def run_dir(store):
    rid = "run_abc123"
    d = store.dir(rid)
    (d / "article").mkdir(parents=True)
    (d / "article" / "xhs.md").write_text("# 标题\n", encoding="utf-8")
    (d / "run.json").write_text("{}", encoding="utf-8")
    (d / "error.log").write_text("boom", encoding="utf-8")
    return rid, d


# --------------------------------------------------------------------------- #
# resolve_artifact：正常路径
# --------------------------------------------------------------------------- #

def test_resolve_artifact_returns_real_file(store, run_dir):
    rid, d = run_dir
    got = store.resolve_artifact(rid, "article/xhs.md")
    assert got == (d / "article" / "xhs.md").resolve()


def test_resolve_artifact_normalizes_dot_segments(store, run_dir):
    rid, _ = run_dir
    assert store.resolve_artifact(rid, "article/./xhs.md") is not None


@pytest.mark.parametrize(
    "rel",
    [
        "nope.md",
        "article",
        "",
        ".",
        "../",
        "article/..",
    ],
)
def test_resolve_artifact_returns_none_for_missing_or_directory(store, run_dir, rel):
    rid, _ = run_dir
    assert store.resolve_artifact(rid, rel) is None


# --------------------------------------------------------------------------- #
# resolve_artifact：穿越与内部文件
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "rel",
    [
        "../../../etc/passwd",
        "../../etc/passwd",
        "../run.json",
        "../error.log",
        "article/../../error.log",
        "article/../../../etc/passwd",
        "/etc/passwd",
        "....//....//etc/passwd",
    ],
)
def test_resolve_artifact_blocks_traversal(store, run_dir, rel):
    rid, _ = run_dir
    assert store.resolve_artifact(rid, rel) is None


def test_resolve_artifact_blocks_sibling_run_with_shared_prefix(store, tmp_path):
    a = store.dir("run_a")
    a.mkdir(parents=True, exist_ok=True)
    b = store.dir("run_ab")           # 前缀相同但**不是**同一个 run
    b.mkdir(parents=True, exist_ok=True)
    (b / "secret.md").write_text("x", encoding="utf-8")
    assert store.resolve_artifact("run_a", "../run_ab/secret.md") is None


def test_resolve_artifact_blocks_symlink_escape(store, run_dir, tmp_path):
    rid, d = run_dir
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = d / "article" / "link.md"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持 symlink")
    assert store.resolve_artifact(rid, "article/link.md") is None


def test_resolve_artifact_denies_internal_bookkeeping_files(store, run_dir):
    rid, _ = run_dir
    assert {"run.json", "run.json.tmp", "error.log"} == store.DENY_ARTIFACTS
    for name in store.DENY_ARTIFACTS:
        assert store.resolve_artifact(rid, name) is None


@pytest.mark.parametrize("bad_run_id", ["../", "..", ".", "run/a", "", "x" * 65, "run id", "run.json"])
def test_resolve_artifact_rejects_malformed_run_id(store, run_dir, bad_run_id):
    """run_id 现在也过白名单（[A-Za-z0-9_-]，≤64）—— 纵深防御，不只靠路由层的 store.get 前置 404。"""
    rid, _ = run_dir
    assert store.resolve_artifact(bad_run_id, "article/xhs.md") is None
    assert store.resolve_artifact(rid, "article/xhs.md") is not None    # 合法 id 不受影响


def test_resolve_artifact_allows_other_json(store, run_dir):
    rid, d = run_dir
    (d / "digest.json").write_text("{}", encoding="utf-8")
    assert store.resolve_artifact(rid, "digest.json") is not None


def test_resolve_artifact_should_also_reject_traversal_in_run_id(store, tmp_path):
    """已修（2026-09-19，纵深防御）。原缺口：resolve_artifact 只清洗 rel，不清洗 run_id。

    HTTP 路由 /artifacts/{run_id}/{rel:path} 目前靠 store.get(run_id) 的前置 404 兜住
    （app/main.py:161），所以外部请求打不进来；但 load_all 只读目录里的 run.json、
    不校验「文件里的 id == 目录名」，只要数据目录里出现一份 id 为 "../" 的 run.json，
    这个 run_id 就能把 base 指到运行目录之外。期望：run_id 也做同样的拒绝。"""
    outside = store.root.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    assert store.resolve_artifact("../", "outside.md") is None


# --------------------------------------------------------------------------- #
# 上传落盘
# --------------------------------------------------------------------------- #

def test_store_upload_sanitizes_filename_and_records_hash(store):
    meta = store.store_upload("../../etc/evil.pdf", b"hello")
    assert meta["filename"] == "evil.pdf"
    assert meta["bytes"] == 5
    assert len(meta["sha256"]) == 64
    assert meta["uploadId"].startswith("up_")
    assert store.upload_path(meta["uploadId"]).name == "evil.pdf"
    assert store.upload_meta(meta["uploadId"]) == meta


def test_upload_lookup_of_unknown_id_is_empty(store):
    assert store.upload_path("up_nope") is None
    assert store.upload_meta("up_nope") == {}


def test_upload_meta_survives_corrupt_json(store, tmp_path):
    d = store.upload_root / "up_bad"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{ not json", encoding="utf-8")
    assert store.upload_meta("up_bad") == {}


def test_save_is_atomic_and_reloadable(store, make_run):
    run = make_run()
    store.add(run)
    assert store.get(run.id).id == run.id
    raw = json.loads((store.dir(run.id) / "run.json").read_text(encoding="utf-8"))
    assert raw["id"] == run.id
    assert not (store.dir(run.id) / "run.json.tmp").exists()


def test_load_all_downgrades_interrupted_runs(store, make_run):
    run = make_run()
    run.status = "running"
    run.stages[0].status = "running"
    store.add(run)
    store._runs.clear()
    store.load_all()
    reloaded = store.get(run.id)
    assert reloaded.status == "failed"
    assert reloaded.error["code"] == "INTERRUPTED"
    assert reloaded.stages[0].status == "failed"
