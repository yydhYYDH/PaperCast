"""app/llm.py：chat 的预算升级、流式传输与 JSON 抽取。

对应 2026-10-02 两篇论文 poster 阶段都失败的复盘：
- `模型输出不是合法 JSON`：reasoning 模型把 max_tokens 花在思维链上，正文 JSON 被截断；
- `RemoteProtocolError`：长回答走非流式，被网关按空闲连接掐断。

不联网：`_once` / `_stream` 用替身，`_stream` 的解析用假的 httpx.AsyncClient。
"""

from __future__ import annotations

import asyncio

import pytest

from app import llm
from app.config import Settings


@pytest.fixture
def client(monkeypatch):
    # 升级重试之间的 sleep 不参与被测逻辑，掐掉让用例秒回。
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", _no_sleep)
    return llm.LLMClient(Settings(llm_api_key="k", llm_base_url="http://x/v1", llm_model="m"))


# --------------------------------------------------------------------------- #
# chat：预算升级
# --------------------------------------------------------------------------- #

def test_truncated_content_escalates_budget_then_succeeds(client, monkeypatch):
    """finish_reason=="length" 的内容（哪怕是半截 JSON）必须翻倍预算重来，而不是直接返回。"""
    calls: list[dict] = []

    async def fake_once(url, payload, headers):
        calls.append(dict(payload))
        return ("{\"spec\": {\"title\": \"半截", "length") if len(calls) == 1 else ("{\"spec\": {}}", "stop")

    monkeypatch.setattr(client, "_once", fake_once)
    out = asyncio.run(client.chat("s", "u", max_tokens=8000, retries=2))

    assert out == "{\"spec\": {}}"
    assert [c["max_tokens"] for c in calls] == [8000, 16000]


def test_empty_reasoning_content_escalates_budget(client, monkeypatch):
    calls: list[dict] = []

    async def fake_once(url, payload, headers):
        calls.append(dict(payload))
        return ("", "length") if len(calls) == 1 else ("done", "stop")

    monkeypatch.setattr(client, "_once", fake_once)
    assert asyncio.run(client.chat("s", "u", max_tokens=4000)) == "done"
    assert calls[-1]["max_tokens"] == 8000


def test_empty_without_length_raises_empty(client, monkeypatch):
    async def fake_once(url, payload, headers):
        return ("", "stop")

    monkeypatch.setattr(client, "_once", fake_once)
    with pytest.raises(llm.LLMError) as ei:
        asyncio.run(client.chat("s", "u", retries=0))
    assert ei.value.code == "LLM_EMPTY"


def test_escalation_respects_hard_cap(client, monkeypatch):
    """设置页的硬上限：到顶了就不再翻倍（避免用户压了 cap 还被放大）。"""
    client.settings.llm_max_tokens_cap = 8000
    calls: list[dict] = []

    async def fake_once(url, payload, headers):
        calls.append(dict(payload))
        return ("half", "length")

    monkeypatch.setattr(client, "_once", fake_once)
    # budget 一开始就被 cap 压到 8000，ceiling 也是 8000，没有升级空间：
    # 不翻倍、不空转重试，直接把内容交回去（是否继续由上层判断）。
    assert asyncio.run(client.chat("s", "u", max_tokens=8000, retries=2)) == "half"
    assert [c["max_tokens"] for c in calls] == [8000]


def test_auth_error_is_not_retried(client, monkeypatch):
    calls = []

    async def fake_once(url, payload, headers):
        calls.append(1)
        raise llm.LLMError("LLM_AUTH", "401 bad key")

    monkeypatch.setattr(client, "_once", fake_once)
    with pytest.raises(llm.LLMError) as ei:
        asyncio.run(client.chat("s", "u", retries=2))
    assert ei.value.code == "LLM_AUTH"
    assert len(calls) == 1, "鉴权/额度错误重试没有意义，不该再烧两次"


# --------------------------------------------------------------------------- #
# _once：流式失败退回非流式
# --------------------------------------------------------------------------- #

def test_once_falls_back_to_blocking_when_stream_fails(client, monkeypatch):
    async def boom(url, payload, headers):
        raise ConnectionError("Server disconnected without sending a response")

    async def blocking(url, payload, headers):
        return ("from-blocking", "stop")

    monkeypatch.setattr(client, "_stream", boom)
    monkeypatch.setattr(client, "_blocking", blocking)
    assert asyncio.run(client._once("u", {}, {})) == ("from-blocking", "stop")


def test_once_does_not_swallow_http_auth(client, monkeypatch):
    async def auth_fail(url, payload, headers):
        raise llm.LLMError("LLM_AUTH", "401")

    async def blocking(url, payload, headers):  # pragma: no cover - 不该走到
        return ("x", "stop")

    monkeypatch.setattr(client, "_stream", auth_fail)
    monkeypatch.setattr(client, "_blocking", blocking)
    with pytest.raises(llm.LLMError) as ei:
        asyncio.run(client._once("u", {}, {}))
    assert ei.value.code == "LLM_AUTH"


# --------------------------------------------------------------------------- #
# _stream：SSE 解析
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, status, lines, body=b""):
        self.status_code = status
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, *a, **k):  # noqa: A003 - 对齐 httpx 接口
        return _FakeStreamCtx(self._resp)


def _patch_httpx(monkeypatch, resp):
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))


def test_stream_accumulates_content_and_reads_finish(client, monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"想"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"世界"},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    _patch_httpx(monkeypatch, _FakeResp(200, lines))
    assert asyncio.run(client._stream("u", {}, {})) == ("你好世界", "stop")


def test_stream_http_error_raises_auth(client, monkeypatch):
    _patch_httpx(monkeypatch, _FakeResp(401, [], body=b"bad key"))
    with pytest.raises(llm.LLMError) as ei:
        asyncio.run(client._stream("u", {}, {}))
    assert ei.value.code == "LLM_AUTH"


def test_stream_ignores_non_data_and_malformed_lines(client, monkeypatch):
    lines = [
        ": keep-alive",
        "event: message",
        "data: {not json",
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
    ]
    _patch_httpx(monkeypatch, _FakeResp(200, lines))
    assert asyncio.run(client._stream("u", {}, {})) == ("ok", "stop")


# --------------------------------------------------------------------------- #
# _extract_json
# --------------------------------------------------------------------------- #

def test_extract_json_tolerates_markdown_fence():
    assert llm._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_raises_bad_json_with_preview():
    with pytest.raises(llm.LLMError) as ei:
        llm._extract_json('{"spec": {"title": "半截')
    assert ei.value.code == "LLM_BAD_JSON"
