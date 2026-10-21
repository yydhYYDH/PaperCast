"""LLM 客户端：OpenAI 兼容 /chat/completions，带重试与 reasoning 模型兜底。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Optional

import httpx

from .config import Settings


class LLMError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _extract_json(text: str) -> Any:
    """从模型输出里抠出 JSON（容忍 markdown 围栏和前后废话）。"""
    if not text:
        raise LLMError("LLM_EMPTY", "模型返回空内容")
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i >= 0 and j > i:
            try:
                return json.loads(t[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("LLM_BAD_JSON", f"模型输出不是合法 JSON：{t[:200]}")


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session = f"papercast-{uuid.uuid4().hex[:16]}"

    @property
    def available(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_base_url)

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "User-Agent": "papercast-server/1.0",
        }
        # opencode go 通道要求会话头，否则 400 MissingSessionID
        if "opencode.ai" in self.settings.llm_base_url:
            h["x-opencode-session"] = self._session
        return h

    def _raise_http(self, status: int, body: str) -> None:
        code = "LLM_AUTH" if status in (401, 403) else (
            "LLM_QUOTA" if status == 402 else "LLM_HTTP"
        )
        raise LLMError(code, f"{status} {body[:300]}")

    async def _blocking(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[str, Optional[str]]:
        """非流式请求：返回 (content, finish_reason)。"""
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_sec) as cx:
            resp = await cx.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            self._raise_http(resp.status_code, resp.text)
        choice = (resp.json().get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return (msg.get("content") or "").strip(), choice.get("finish_reason")

    async def _stream(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[str, Optional[str]]:
        """流式请求：返回 (content, finish_reason)。

        reasoning 模型（deepseek-v4.1-flash）回答前会先写 ~8k token 思维链，整段非流式请求
        要静默等 40-60 秒；网关按空闲连接把它掐断，客户端只看到
        `RemoteProtocolError: Server disconnected without sending a response`（2026-10-02 实测）。
        流式边收边保活，绕开这个空闲超时。
        """
        body = {**payload, "stream": True}
        parts: list[str] = []
        finish: Optional[str] = None
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_sec) as cx:
            async with cx.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    raw = (await resp.aread()).decode("utf-8", "replace")
                    self._raise_http(resp.status_code, raw)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        parts.append(delta["content"])
        return "".join(parts).strip(), finish

    async def _once(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[str, Optional[str]]:
        """发一次请求，优先流式；流式在连接层失败时退回非流式（兼容不认 stream 的网关）。"""
        if getattr(self.settings, "llm_stream", True):
            try:
                return await self._stream(url, payload, headers)
            except LLMError:
                raise
            except Exception:
                pass
        return await self._blocking(url, payload, headers)

    async def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
        retries: int = 2,
    ) -> str:
        if not self.available:
            raise LLMError("LLM_NOT_CONFIGURED", "没有可用的 LLM 凭据（LLM_API_KEY / GO_API_KEY）")
        budget = max_tokens or self.settings.llm_max_tokens
        # 硬上限：设置页可调。默认 0 = 不干预，因此不改变既有行为。
        cap = getattr(self.settings, "llm_max_tokens_cap", 0)
        if cap and budget > cap:
            budget = cap
        ceiling = cap if cap else 64000
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": budget,
            "temperature": temperature,
        }
        url = f"{self.settings.llm_base_url}/chat/completions"
        last: Optional[LLMError] = None

        for attempt in range(retries + 1):
            try:
                content, finish = await self._once(url, payload, self._headers())
                # reasoning 模型把预算花在思维链上：内容空、或被 finish_reason=="length" 截断时，
                # 翻倍预算重来。**截断的 JSON 正是「模型输出不是合法 JSON」的根因**（2026-10-02 实测）。
                if (not content or finish == "length") and budget < ceiling and attempt < retries:
                    budget = min(budget * 2, ceiling)
                    payload["max_tokens"] = budget
                    last = LLMError(
                        "LLM_TRUNCATED",
                        "思维链占满 token，已加倍预算重试" if not content else "输出被 max_tokens 截断，已加倍预算重试",
                    )
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if not content:
                    raise LLMError("LLM_EMPTY", f"模型返回空内容 finish_reason={finish}")
                return content
            except LLMError as e:
                last = e
                if e.code in ("LLM_AUTH", "LLM_QUOTA", "LLM_NOT_CONFIGURED"):
                    raise
            except Exception as e:  # 网络类错误
                last = LLMError("LLM_NETWORK", f"{type(e).__name__}: {e}")
            await asyncio.sleep(2.0 * (attempt + 1))

        raise last or LLMError("LLM_FAILED", "LLM 调用失败")

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: Optional[int] = None,
        retries: int = 2,
    ) -> Any:
        text = await self.chat(system, user, max_tokens=max_tokens, temperature=0.2, retries=retries)
        return _extract_json(text)
