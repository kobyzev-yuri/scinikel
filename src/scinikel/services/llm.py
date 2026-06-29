"""LLM-клиент — ProxyAPI (openai) / ollama через config.env + runtime override."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from scinikel.services.llm_runtime import (
    PROVIDER_OLLAMA,
    EffectiveLLMConfig,
    get_effective_config,
)

logger = logging.getLogger(__name__)


class LLMClient:
    def _cfg(self) -> EffectiveLLMConfig:
        return get_effective_config()

    @property
    def provider(self) -> str:
        return self._cfg().provider

    @property
    def available(self) -> bool:
        return self._cfg().enabled

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, timeout=timeout)

    def generate_sync(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat_sync(messages, timeout=timeout)

    def chat_sync(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> str:
        cfg = self._cfg()
        if cfg.provider == PROVIDER_OLLAMA:
            return self._ollama_chat(messages, cfg, timeout=timeout)
        if cfg.openai_api_key:
            return self._openai_chat(messages, cfg, timeout=timeout)
        raise RuntimeError(
            "LLM не настроен: задайте OPENAI_API_KEY в config.env или выберите Ollama во вкладке LLM"
        )

    async def chat(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> str:
        import asyncio

        return await asyncio.to_thread(self.chat_sync, messages, timeout=timeout)

    def _openai_chat(
        self,
        messages: list[dict[str, str]],
        cfg: EffectiveLLMConfig,
        *,
        timeout: float | None = None,
    ) -> str:
        headers = {"Authorization": f"Bearer {cfg.openai_api_key}"}
        base = cfg.openai_base_url or "https://api.proxyapi.ru/openai/v1"
        payload: dict[str, Any] = {
            "model": cfg.openai_model,
            "messages": messages,
            "temperature": cfg.openai_temperature,
        }
        with httpx.Client(timeout=timeout or cfg.openai_timeout) as client:
            resp = client.post(f"{base.rstrip('/')}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def _ollama_chat(
        self,
        messages: list[dict[str, str]],
        cfg: EffectiveLLMConfig,
        *,
        timeout: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": cfg.ollama_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": cfg.openai_temperature,
                "num_predict": 1024,
            },
        }
        with httpx.Client(timeout=timeout or cfg.ollama_timeout) as client:
            resp = client.post(f"{cfg.ollama_base_url.rstrip('/')}/api/chat", json=payload)
            resp.raise_for_status()
            body = resp.json()
        msg = body.get("message") or {}
        content = (msg.get("content") or "").strip()
        if content:
            return content
        thinking = (msg.get("thinking") or "").strip()
        if thinking:
            logger.warning("Ollama returned thinking without content; think=false may be unsupported")
        return thinking


_llm: LLMClient | None = None


def reset_llm_client() -> None:
    global _llm
    _llm = None


def get_llm_client() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
