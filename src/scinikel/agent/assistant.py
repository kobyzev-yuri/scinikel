"""Dialog agent: LLM + graph/search tools, with rule-based fallback."""

from dataclasses import dataclass, field
from typing import Any

from scinikel.query.engine import HybridQueryEngine, QueryResult
from scinikel.services.llm import get_llm_client


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class AgentResponse:
    message: str
    query_result: QueryResult | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    llm_used: bool = False


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
        self.llm = get_llm_client()

    def chat(self, user_message: str) -> AgentResponse:
        self.history.append(ChatMessage(role="user", content=user_message))
        query_result = self.query_engine.execute(user_message)

        llm_used = False
        if self.llm.available:
            try:
                message = self._llm_answer(user_message, query_result)
                llm_used = True
            except Exception:
                message = self._fallback_answer(query_result)
        else:
            message = self._fallback_answer(query_result)

        citations = [
            *[
                {"type": "experiment", "id": e["experiment"]["id"], "title": e["experiment"]["name"]}
                for e in query_result.experiments
            ],
            *[{"type": "document", **s} for s in query_result.sources],
        ]

        self.history.append(ChatMessage(role="assistant", content=message))
        return AgentResponse(
            message=message,
            query_result=query_result,
            citations=citations,
            llm_used=llm_used,
        )

    def _fallback_answer(self, result: QueryResult) -> str:
        parts = [result.answer]
        if result.gaps:
            parts.append("\n**Пробелы:** " + ", ".join(f"{g['material']}×{g['mode']}" for g in result.gaps[:5]))
        if result.sources:
            parts.append("\n**Документы:** " + ", ".join(s.get("title") or s["id"] for s in result.sources))
        return "\n".join(parts)

    def _llm_answer(self, question: str, result: QueryResult) -> str:
        sources_text = "\n".join(
            f"- {s.get('title', s['id'])}: {s.get('snippet', '')[:200]}" for s in result.sources
        )
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
        return self.llm.chat_sync(messages)
