"""Dialog agent: LLM + graph/search tools, with rule-based fallback."""

from dataclasses import dataclass, field
from typing import Any

import httpx

from scinikel.config import settings
from scinikel.query.engine import HybridQueryEngine, QueryResult


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class AgentResponse:
    message: str
    query_result: QueryResult | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)


SYSTEM_PROMPT = """Ты — «Научный клубок», эксперт-ассистент исследователя Норникеля.
Отвечай на русском, языком практика. Каждый тезис опирай на факты из контекста.
Если данных недостаточно — скажи прямо и предложи уточнить материал, режим или свойство.
Не выдумывай эксперименты и цифры."""

TOOL_CONTEXT_TEMPLATE = """
## Данные из графа знаний
{graph_answer}

## Источники
{sources}

## Связанные сущности
{related}
"""


class ResearchAgent:
    def __init__(self, query_engine: HybridQueryEngine) -> None:
        self.query_engine = query_engine
        self.history: list[ChatMessage] = []

    def chat(self, user_message: str) -> AgentResponse:
        self.history.append(ChatMessage(role="user", content=user_message))
        query_result = self.query_engine.execute(user_message)

        if settings.openai_api_key:
            message = self._llm_answer(user_message, query_result)
        else:
            message = self._fallback_answer(query_result)

        citations = [
            *[{"type": "experiment", "id": e["experiment"]["id"], "title": e["experiment"]["name"]} for e in query_result.experiments],
            *[{"type": "document", **s} for s in query_result.sources],
        ]

        self.history.append(ChatMessage(role="assistant", content=message))
        return AgentResponse(message=message, query_result=query_result, citations=citations)

    def _fallback_answer(self, result: QueryResult) -> str:
        parts = [result.answer]
        if result.gaps:
            parts.append("\n**Пробелы:** " + ", ".join(f"{g['material']}×{g['mode']}" for g in result.gaps[:5]))
        if result.sources:
            parts.append("\n**Документы:** " + ", ".join(s.get("title") or s["id"] for s in result.sources))
        return "\n".join(parts)

    def _llm_answer(self, question: str, result: QueryResult) -> str:
        sources_text = "\n".join(f"- {s.get('title', s['id'])}: {s.get('snippet', '')[:200]}" for s in result.sources)
        related_text = ", ".join(r.get("name", "") for r in result.related_entities[:10])
        context = TOOL_CONTEXT_TEMPLATE.format(
            graph_answer=result.answer,
            sources=sources_text or "нет",
            related=related_text or "нет",
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": m.role, "content": m.content} for m in self.history[-6:]],
            {"role": "user", "content": f"{question}\n\n{context}"},
        ]

        try:
            return self._call_openai(messages)
        except Exception:
            return self._fallback_answer(result)

    def _call_openai(self, messages: list[dict[str, str]]) -> str:
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        base = settings.openai_base_url or "https://api.openai.com/v1"
        payload = {"model": settings.llm_model, "messages": messages, "temperature": 0.2}
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{base}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
