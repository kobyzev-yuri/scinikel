"""LLM-клиент — openai / ollama через config.env."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from scinikel.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower()

    @property
    def available(self) -> bool:
        return settings.llm_enabled

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages)

    def generate_sync(self, prompt: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat_sync(messages)

    def chat_sync(self, messages: list[dict[str, str]]) -> str:
        if self.provider == "ollama":
            return self._ollama_chat(messages)
        if settings.openai_api_key:
            return self._openai_chat(messages)
        try:
            return self._ollama_chat(messages)
        except Exception as exc:
            raise RuntimeError(
                "LLM not configured: set OPENAI_API_KEY in config.env or LLM_PROVIDER=ollama"
            ) from exc

    async def chat(self, messages: list[dict[str, str]]) -> str:
        import asyncio

        return await asyncio.to_thread(self.chat_sync, messages)

    def _openai_chat(self, messages: list[dict[str, str]]) -> str:
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        base = settings.openai_base_url or "https://api.openai.com/v1"
        payload: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": settings.openai_temperature,
        }
        with httpx.Client(timeout=settings.openai_timeout) as client:
            resp = client.post(f"{base}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def _ollama_chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": settings.openai_temperature},
        }
        with httpx.Client(timeout=settings.ollama_timeout) as client:
            resp = client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")


_llm: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
