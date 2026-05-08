"""LLM Client: 统一大模型调用，使用 Custom Base URL。"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from common.config import get_settings
from common.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """兼容 Chat Completions 协议的 LLM 客户端。"""

    def __init__(self):
        settings = get_settings().llm
        self._providers: list[dict[str, str]] = []

        # 自定义兼容端点（最高优先级）；内部网关可只依赖 Base URL，不强制要求 Key。
        if settings.custom_base_url:
            self._providers.append(
                {
                    "name": "custom",
                    "api_key": settings.custom_api_key,
                    "base_url": settings.custom_base_url.rstrip("/"),
                    "model": settings.custom_model or "gpt-4o-mini",
                }
            )

        self._client = httpx.AsyncClient(timeout=180.0)
        self.last_call_count: int = 0
        self.last_tokens_used: int = 0

    def is_available(self) -> bool:
        return len(self._providers) > 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """调用 LLM，自动 fallback 到下一个 provider"""
        self.last_call_count = 0
        self.last_tokens_used = 0
        errors: list[str] = []

        for provider in self._providers:
            try:
                result = await self._call_provider(provider, messages, model, temperature, max_tokens)
                self.last_call_count = 1
                return result
            except Exception as e:
                error_detail = str(e) or e.__class__.__name__
                errors.append(f"{provider['name']}: {error_detail}")
                logger.warning(f"LLM provider {provider['name']} failed: {error_detail}")
                continue

        suffix = f" ({'; '.join(errors)})" if errors else ""
        raise RuntimeError(f"All LLM providers failed{suffix}")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """流式调用 OpenAI Chat Completions 兼容接口。"""
        self.last_call_count = 0
        self.last_tokens_used = 0
        errors: list[str] = []

        for provider in self._providers:
            emitted = False
            try:
                async for chunk in self._stream_provider(provider, messages, model, temperature, max_tokens):
                    emitted = True
                    self.last_call_count = 1
                    yield chunk
                return
            except Exception as e:
                error_detail = str(e) or e.__class__.__name__
                if emitted:
                    raise RuntimeError(f"LLM stream interrupted after output: {provider['name']}: {error_detail}") from e
                errors.append(f"{provider['name']}: {error_detail}")
                logger.warning(f"LLM provider {provider['name']} stream failed: {error_detail}")
                continue

        suffix = f" ({'; '.join(errors)})" if errors else ""
        raise RuntimeError(f"All LLM providers failed{suffix}")

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 响应"""
        enhanced = list(messages)
        if enhanced and enhanced[0]["role"] == "system":
            enhanced[0] = {
                **enhanced[0],
                "content": enhanced[0]["content"] + "\n\nYou MUST respond in valid JSON only.",
            }

        response = await self.chat(
            enhanced,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # 尝试提取 JSON（处理 markdown 代码块）
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return json.loads(text)

    async def _call_provider(
        self,
        provider: dict[str, str],
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        use_model = model or provider["model"]

        if provider["name"] == "claude":
            return await self._call_claude(provider, messages, use_model, temperature, max_tokens)

        url = f"{provider['base_url']}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if provider.get("api_key"):
            headers["Authorization"] = f"Bearer {provider['api_key']}"
        body: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._client.post(url, headers=headers, json=body)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            preview = resp.text[:1000]
            raise RuntimeError(f"HTTP {resp.status_code} {url}: {preview}") from e
        data = resp.json()
        self.last_tokens_used = data.get("usage", {}).get("total_tokens", 0)
        return data["choices"][0]["message"]["content"]

    async def _stream_provider(
        self,
        provider: dict[str, str],
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        use_model = model or provider["model"]
        if provider["name"] == "claude":
            raise RuntimeError("Claude streaming is not implemented for this client")

        url = f"{provider['base_url']}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if provider.get("api_key"):
            headers["Authorization"] = f"Bearer {provider['api_key']}"
        body: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with self._client.stream("POST", url, headers=headers, json=body) as resp:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                preview = (await resp.aread()).decode(errors="ignore")[:1000]
                raise RuntimeError(f"HTTP {resp.status_code} {url}: {preview}") from e

            async for line in resp.aiter_lines():
                if not line:
                    continue
                text = line.strip()
                if text.startswith("data:"):
                    text = text[5:].strip()
                if not text:
                    continue
                if text == "[DONE]":
                    break
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("Ignore malformed LLM stream line: %s", text[:200])
                    continue
                usage = data.get("usage") or {}
                if usage.get("total_tokens"):
                    self.last_tokens_used = usage["total_tokens"]
                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    async def _call_claude(
        self,
        provider: dict[str, str],
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        url = f"{provider['base_url']}/messages"
        headers = {
            "x-api-key": provider["api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_msg:
            body["system"] = system_msg

        resp = await self._client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        self.last_tokens_used = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get(
            "output_tokens", 0
        )
        return data["content"][0]["text"]

    async def close(self):
        await self._client.aclose()
