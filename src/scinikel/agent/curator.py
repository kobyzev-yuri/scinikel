"""CuratorAgent — адаптация KBLibrarianAgent из 3dtoday под онтологию scinikel."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import materialize_extraction, slugify
from scinikel.services.llm import get_llm_client

logger = logging.getLogger(__name__)

EXTRACTION_SCHEMA = """
{
  "relevance_score": 0.0,
  "decision": "approve|reject|needs_review",
  "reason": "краткая причина",
  "document": {
    "id": "DOC-...",
    "title": "название",
    "abstract": "краткое содержание",
    "doc_type": "report|article|protocol",
    "authors": []
  },
  "experiments": [
    {
      "id": "EXP-YYYY-NNN",
      "title": "название эксперимента",
      "material": "Ni-Cu сплав / концентрат",
      "mode": "флотация pH 10.5 / электролиз 250°C",
      "property_name": "извлечение Ni",
      "property_value": "87.3%",
      "property_delta": "+3.1%",
      "equipment": "FML-8",
      "team": "Лаборатория обогащения",
      "conclusion": "вывод одним предложением",
      "document_ref": "DOC-...",
      "topics": ["флотация", "никель"]
    }
  ],
  "topics": ["флотация"],
  "key_points": ["важный тезис"]
}
"""

SYSTEM_PROMPT = (
    "Ты — куратор научной базы знаний металлургического НИОКР (Норникель). "
    "Извлекай только факты из текста. Отвечай только валидным JSON без markdown."
)

METALLURGY_KEYWORDS = [
    "ni", "cu", "никел", "мед", "сплав", "концентрат", "флотац", "электролиз",
    "обжиг", "извлечен", "извлечение", "зольност", "прочност", "эксперимент", "лаборатор",
]


class CuratorAgent:
    """
    Анализ документа → structured JSON → materialize в граф.
    Паттерн review_and_decide из 3dtoday/kb_librarian.py.
    """

    def __init__(self, graph: NetworkXGraphStore | None = None) -> None:
        self.graph = graph
        self.llm = get_llm_client()

    async def review_and_extract(
        self,
        title: str,
        content: str,
        *,
        source: str | None = None,
        doc_type: str = "report",
    ) -> dict[str, Any]:
        relevance = self._quick_relevance(content)
        if relevance < 0.15:
            return {
                "decision": "reject",
                "relevance_score": relevance,
                "reason": "Документ не относится к металлургии/материаловедению",
                "document": {"title": title, "doc_type": doc_type},
                "experiments": [],
            }

        extraction = await self._llm_extract(title, content, source=source, doc_type=doc_type)
        if not extraction:
            extraction = self._heuristic_extract(title, content, source=source, doc_type=doc_type)

        extraction.setdefault("relevance_score", relevance)
        if extraction["relevance_score"] < relevance:
            extraction["relevance_score"] = relevance
        if extraction.get("decision") != "reject" and not extraction.get("experiments"):
            extraction["decision"] = "needs_review"
            extraction["reason"] = extraction.get("reason") or "Эксперименты не извлечены автоматически"

        return extraction

    async def ingest_to_graph(self, extraction: dict[str, Any]) -> dict[str, Any]:
        if self.graph is None:
            raise RuntimeError("Graph store not attached")
        if extraction.get("decision") == "reject":
            return {"status": "rejected", "graph_stats": self.graph.stats()}

        stats = materialize_extraction(self.graph, extraction)
        return {"status": "ok", "materialized": stats, "graph_stats": self.graph.stats()}

    async def review_and_ingest(
        self,
        title: str,
        content: str,
        *,
        source: str | None = None,
        doc_type: str = "report",
    ) -> dict[str, Any]:
        extraction = await self.review_and_extract(title, content, source=source, doc_type=doc_type)
        result = {"extraction": extraction}
        if self.graph and extraction.get("decision") != "reject":
            result["ingest"] = await self.ingest_to_graph(extraction)
        return result

    async def _llm_extract(
        self,
        title: str,
        content: str,
        *,
        source: str | None,
        doc_type: str,
    ) -> dict[str, Any] | None:
        prompt = f"""Проанализируй научный/технический документ металлургии и извлеки структурированные данные.

ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source or 'unknown'}
ТИП: {doc_type}

ТЕКСТ:
{content[:6000]}

Верни ТОЛЬКО JSON по схеме:
{EXTRACTION_SCHEMA}

Правила:
- id эксперimentов: EXP-YYYY-NNN если явно указан, иначе сгенерируй
- document.id: DOC-... если не указан — из заголовка
- decision=reject если документ явно не про R&D/эксперименты
- не выдумывай цифры — только из текста
"""
        try:
            response = await self.llm.generate(prompt, SYSTEM_PROMPT)
            return self._extract_json(response)
        except Exception as exc:
            logger.warning("LLM extraction failed, fallback to heuristics: %s", exc)
            return None

    def _heuristic_extract(
        self,
        title: str,
        content: str,
        *,
        source: str | None,
        doc_type: str,
    ) -> dict[str, Any]:
        """Rule-based fallback без LLM — для офлайн и быстрых тестов."""
        doc_id = f"doc-{slugify(title)}"
        experiments: list[dict[str, Any]] = []

        exp_ids = re.findall(r"EXP-\d{4}-\d+", content, flags=re.IGNORECASE)
        materials = re.findall(
            r"Ni[-\s]?Cu(?:[\s\w]{0,20})?(?:сплав|концентрат\w*)",
            content,
            flags=re.IGNORECASE,
        )
        modes = re.findall(
            r"(?:флотац\w*(?:\s+pH\s+[\d.]+)?|электролиз\s+[\d.]+°?\s*C|обжиг\s+[\d.]+°?\s*C)",
            content,
            flags=re.IGNORECASE,
        )

        if exp_ids or (materials and modes):
            experiments.append(
                {
                    "id": exp_ids[0].upper() if exp_ids else f"EXP-{slugify(title)[:12]}",
                    "title": title,
                    "material": materials[0] if materials else "не указан",
                    "mode": modes[0] if modes else "не указан",
                    "property_name": "результат",
                    "property_value": "?",
                    "document_ref": doc_id,
                    "topics": [],
                }
            )

        return {
            "decision": "needs_review" if experiments else "reject",
            "relevance_score": self._quick_relevance(content),
            "reason": "heuristic extraction (LLM unavailable)",
            "document": {
                "id": doc_id,
                "title": title,
                "abstract": content[:400],
                "doc_type": doc_type,
            },
            "experiments": experiments,
            "topics": [],
            "key_points": [],
        }

    @staticmethod
    def _extract_json(response: str) -> dict[str, Any] | None:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        return None

    @staticmethod
    def _quick_relevance(content: str) -> float:
        text = content.lower()
        hits = sum(1 for kw in METALLURGY_KEYWORDS if kw in text)
        return min(hits / 4.0, 1.0)
