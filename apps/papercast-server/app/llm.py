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
                async with httpx.AsyncClient(timeout=self.settings.llm_timeout_sec) as cx:
                    resp = await cx.post(url, json=payload, headers=self._headers())
                if resp.status_code >= 400:
                    detail = resp.text[:300]
                    code = "LLM_AUTH" if resp.status_code in (401, 403) else (
                        "LLM_QUOTA" if resp.status_code == 402 else "LLM_HTTP"
                    )
                    raise LLMError(code, f"{resp.status_code} {detail}")
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                content = (msg.get("content") or "").strip()
                if not content:
                    # reasoning 模型 token 花在思维链上：加倍预算重试一次
                    finish = choice.get("finish_reason")
                    if finish == "length" and budget < 64000 and attempt < retries:
                        budget *= 2
                        payload["max_tokens"] = budget
                        last = LLMError("LLM_TRUNCATED", "思维链占满 token，已加倍预算重试")
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
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
