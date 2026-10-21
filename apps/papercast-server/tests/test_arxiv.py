from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.intake import arxiv


class FakeClient:
    def __init__(self, statuses: list[int]):
        self.statuses = iter(statuses)
        self.headers: list[dict[str, str]] = []

    async def get(self, url: str, **kwargs):
        self.headers.append(kwargs["headers"])
        status = next(self.statuses)
        request = httpx.Request("GET", url)
        return httpx.Response(status, request=request)


def test_get_retries_406_and_sends_atom_headers(monkeypatch):
    monkeypatch.setattr(arxiv, "API_INTERVAL", 0)
    monkeypatch.setattr(arxiv, "BASE_DELAY", 0)
    client = FakeClient([406, 200])

    response = asyncio.run(arxiv._get(client, arxiv.API, params={"id_list": "2609.26780"}))

    assert response.status_code == 200
    assert len(client.headers) == 2
    assert client.headers[0]["Accept"].startswith("application/atom+xml")
    assert client.headers[0]["User-Agent"] == arxiv.UA


def test_get_serializes_api_requests(monkeypatch):
    monkeypatch.setattr(arxiv, "API_INTERVAL", 0.03)
    monkeypatch.setattr(arxiv, "BASE_DELAY", 0)
    started: list[float] = []

    class Client:
        async def get(self, url: str, **kwargs):
            started.append(time.monotonic())
            await asyncio.sleep(0.01)
            return httpx.Response(200, request=httpx.Request("GET", url))

    async def run():
        await asyncio.gather(
            arxiv._get(Client(), arxiv.API),
            arxiv._get(Client(), arxiv.API),
        )

    asyncio.run(run())

    assert started[1] - started[0] >= 0.025


def test_get_does_not_retry_non_retryable_status(monkeypatch):
    monkeypatch.setattr(arxiv, "API_INTERVAL", 0)
    monkeypatch.setattr(arxiv, "BASE_DELAY", 0)
    client = FakeClient([404, 200])

    response = asyncio.run(arxiv._get(client, arxiv.API))

    assert response.status_code == 404
    assert len(client.headers) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2609.26780", ("2609.26780", "")),
        ("arXiv:2609.26780v2", ("2609.26780", "v2")),
        ("https://arxiv.org/pdf/2609.26780.pdf", ("2609.26780", "")),
    ],
)
def test_normalize(value: str, expected: tuple[str, str]):
    assert arxiv.normalize(value) == expected


class CtxClient:
    """支持 async context manager 的假 client，行为由 handler 决定。"""

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, **kwargs):
        return await self._handler(url, **kwargs)


def test_get_with_fallback_uses_proxy_after_direct_fails(monkeypatch):
    monkeypatch.setattr(arxiv, "API_INTERVAL", 0)
    monkeypatch.setattr(arxiv, "BASE_DELAY", 0)
    seen: list[bool] = []

    def fake_new_client(timeout, *, trust_env):
        seen.append(trust_env)

        async def boom(url, **kw):
            raise httpx.ConnectError("direct blocked")

        async def ok(url, **kw):
            return httpx.Response(200, request=httpx.Request("GET", url))

        return CtxClient(boom if trust_env is False else ok)

    monkeypatch.setattr(arxiv, "_new_client", fake_new_client)

    response = asyncio.run(arxiv._get_with_fallback(arxiv.API, timeout=1))

    assert response.status_code == 200
    assert seen == [False, True]


def test_get_with_fallback_direct_only_when_disabled(monkeypatch):
    monkeypatch.setattr(arxiv, "API_INTERVAL", 0)
    monkeypatch.setattr(arxiv, "BASE_DELAY", 0)
    monkeypatch.setattr(arxiv, "DIRECT_FIRST", False)
    seen: list[bool] = []

    def fake_new_client(timeout, *, trust_env):
        seen.append(trust_env)

        async def ok(url, **kw):
            return httpx.Response(200, request=httpx.Request("GET", url))

        return CtxClient(ok)

    monkeypatch.setattr(arxiv, "_new_client", fake_new_client)

    asyncio.run(arxiv._get_with_fallback(arxiv.API, timeout=1))

    assert seen == [True]


def test_backoff_respects_retry_after(monkeypatch):
    resp = httpx.Response(429, headers={"Retry-After": "7"}, request=httpx.Request("GET", arxiv.API))

    delay = arxiv._backoff_delay(0, resp)

    assert 7.0 <= delay <= 8.0


def test_backoff_exponential_without_retry_after(monkeypatch):
    monkeypatch.setattr(arxiv, "BASE_DELAY", 2.0)

    delay = arxiv._backoff_delay(1, None)

    assert 4.0 <= delay <= 5.0
