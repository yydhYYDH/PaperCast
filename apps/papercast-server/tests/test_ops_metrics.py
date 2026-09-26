"""app/ops.py：运营数据的 single-flight 与扫描行为（渠道接口与磁盘扫描全 mock，不联网）。"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from app import ops


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例都从「缓存空」开始，并复位 single-flight 的锁（它按 loop 缓存）。"""
    ops._METRICS_CACHE.update(at=0.0, data=None)
    ops._METRICS_LOCK = None
    ops._METRICS_LOOP = None
    yield
    ops._METRICS_CACHE.update(at=0.0, data=None)
    ops._METRICS_LOCK = None
    ops._METRICS_LOOP = None


def _stub_channels(monkeypatch, counter: Counter) -> None:
    async def _bili(_items):
        counter["bili"] += 1
        await asyncio.sleep(0)          # 制造可被撞见的 await 间隙
        return {"items": [], "errors": []}

    async def _zh(_items):
        counter["zh"] += 1
        await asyncio.sleep(0)
        return {"items": [], "errors": []}

    async def _xhs():
        counter["xhs"] += 1
        await asyncio.sleep(0)
        return {"available": False, "detail": "mock"}

    monkeypatch.setattr(ops, "_bilibili_items", _bili)
    monkeypatch.setattr(ops, "_zhihu_items", _zh)
    monkeypatch.setattr(ops, "_xhs_account", _xhs)


def test_concurrent_metrics_scans_disk_once(monkeypatch):
    """并发调用只算一次 —— 这是加锁的全部理由。

    背景（2026-09-26）：缓存是「算完才写」，而 `_scan_published()` 要 rglob 扫全量
    var/runs + var/artifacts（本机 1.7GB / 4000+ 文件），每次 xhs 还要 MCP 起一次浏览器
    （预算是 30 次/10 分钟）。批量并发跑时 5 条 run 会在同一秒一起越过空缓存，
    于是 5 次全盘扫描 + 5 次浏览器会话。
    """
    counter = Counter()
    _stub_channels(monkeypatch, counter)
    monkeypatch.setattr(ops, "_scan_published",
                        lambda: (counter.__setitem__("scan", counter["scan"] + 1),
                                 {"bilibili": [], "zhihu": [], "xiaohongshu": []})[1])

    async def main():
        return await asyncio.gather(*[ops.metrics() for _ in range(5)])

    results = asyncio.run(main())
    assert counter["scan"] == 1, f"磁盘被扫了 {counter['scan']} 次"
    assert counter["xhs"] == 1, f"渠道被问了 {counter['xhs']} 次"
    # 五个调用拿到的是同一份对象（后来者吃的是第一个人的结果）
    assert all(r is results[0] for r in results)


def test_sequential_call_inside_ttl_hits_cache(monkeypatch):
    """TTL 内的后续调用直接吃缓存，连锁都不碰。"""
    counter = Counter()
    _stub_channels(monkeypatch, counter)
    monkeypatch.setattr(ops, "_scan_published",
                        lambda: (counter.__setitem__("scan", counter["scan"] + 1),
                                 {"bilibili": [], "zhihu": [], "xiaohongshu": []})[1])

    async def main():
        await ops.metrics()
        await ops.metrics()
        await ops.metrics()

    asyncio.run(main())
    assert counter["scan"] == 1


def test_force_bypasses_cache(monkeypatch):
    """force=True 必须真的重算（运营看板点「刷新」要看到新数）。"""
    counter = Counter()
    _stub_channels(monkeypatch, counter)
    monkeypatch.setattr(ops, "_scan_published",
                        lambda: (counter.__setitem__("scan", counter["scan"] + 1),
                                 {"bilibili": [], "zhihu": [], "xiaohongshu": []})[1])

    async def main():
        await ops.metrics()
        await ops.metrics(force=True)

    asyncio.run(main())
    assert counter["scan"] == 2


def test_lock_is_rebuilt_across_event_loops(monkeypatch):
    """模块级 asyncio.Lock 会记住第一个 loop；跨 loop 复用会抛 RuntimeError。

    单测里每个用例都是新 loop，所以锁必须按 loop 重建 —— 这个回归测试就是钉住这点。
    """
    _stub_channels(monkeypatch, Counter())
    monkeypatch.setattr(ops, "_scan_published",
                        lambda: {"bilibili": [], "zhihu": [], "xiaohongshu": []})

    async def one():
        ops._METRICS_CACHE.update(at=0.0, data=None)
        return await ops.metrics()

    first = asyncio.run(one())
    second = asyncio.run(one())        # 新 loop；不该因为旧锁而炸
    assert first["channels"] and second["channels"]


def test_scan_runs_off_the_event_loop(monkeypatch):
    """全盘扫描是同步阻塞 I/O，必须在线程里跑，不能把事件循环堵住。"""
    import threading

    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def _scan():
        seen["thread"] = threading.get_ident()
        return {"bilibili": [], "zhihu": [], "xiaohongshu": []}

    _stub_channels(monkeypatch, Counter())
    monkeypatch.setattr(ops, "_scan_published", _scan)
    asyncio.run(ops.metrics())
    assert seen["thread"] != loop_thread, "扫描跑在事件循环线程上了"
