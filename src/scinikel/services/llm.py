"""Упрощённый LLM-клиент — паттерн из 3dtoday/llm_client + scinikel/assistant."""

from __future__ import annotations

import logging

import httpx

from scinikel.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.llm_provider

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        if self.provider == "ollama":
            return await self._ollama(prompt, system_prompt)
        if settings.openai_api_key:
            return await self._openai(prompt, system_prompt)
        try:
            return await self._ollama(prompt, system_prompt)
        except Exception as exc:
            raise RuntimeError(
                "LLM not configured: set OPENAI_API_KEY or LLM_PROVIDER=ollama"
            ) from exc

    def generate_sync(self, prompt: str, system_prompt: str | None = None) -> str:
        import asyncio

        return asyncio.run(self.generate(prompt, system_prompt))

    async def _openai(self, prompt: str, system_prompt: str | None) -> str:
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        base = settings.openai_base_url or "https://api.openai.com/v1"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": settings.llm_model, "messages": messages, "temperature": 0.1}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _ollama(self, prompt: str, system_prompt: str | None) -> str:
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        payload = {
            "model": settings.ollama_model,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")


_llm: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
