"""CuratorAgent — адаптация KBLibrarianAgent из 3dtoday под онтологию scinikel."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import doc_id_from_title, materialize_extraction, slugify
from scinikel.services.llm import get_llm_client
from scinikel.services.llm_runtime import should_use_llm

logger = logging.getLogger(__name__)

MAX_VISION_IMAGES = 10

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
    Паттерн review_and_decide + _analyze_images из 3dtoday/kb_librarian.py.
    """

    def __init__(self, graph: NetworkXGraphStore | None = None) -> None:
        self.graph = graph

    @property
    def llm(self):
        return get_llm_client()

    async def review_and_extract(
        self,
        title: str,
        content: str,
        *,
        source: str | None = None,
        doc_type: str = "report",
        images: list[dict[str, Any]] | None = None,
        analyze_images: bool = True,
    ) -> dict[str, Any]:
        image_analysis = None
        enriched = content
        if images and analyze_images:
            image_analysis = await self._analyze_images(images)
            enriched = self._merge_image_context(content, image_analysis)

        relevance = self._quick_relevance(enriched)
        if relevance < 0.15 and not (image_analysis and image_analysis.get("image_analyses")):
            return {
                "decision": "reject",
                "relevance_score": relevance,
                "reason": "Документ не относится к металлургии/материаловедению",
                "document": {"title": title, "doc_type": doc_type},
                "experiments": [],
                "image_analysis": image_analysis,
            }

        extraction = None
        extraction_method = "heuristic"
        if should_use_llm():
            extraction = await self._llm_extract(
                title, enriched, source=source, doc_type=doc_type
            )
            if extraction:
                extraction_method = "llm"
        if not extraction:
            extraction = self._heuristic_extract(
                title, enriched, source=source, doc_type=doc_type
            )
            extraction_method = "heuristic"

        extraction.setdefault("relevance_score", relevance)
        extraction["extraction_method"] = extraction_method
        if extraction["relevance_score"] < relevance:
            extraction["relevance_score"] = relevance
        if extraction.get("decision") != "reject" and not extraction.get("experiments"):
            extraction["decision"] = "needs_review"
            extraction["reason"] = extraction.get("reason") or "Эксперименты не извлечены автоматически"
        if image_analysis:
            extraction["image_analysis"] = image_analysis

        return self._normalize_extraction(extraction, title)

    @staticmethod
    def _normalize_extraction(extraction: dict[str, Any], title: str) -> dict[str, Any]:
        """Единый doc_id из заголовка (не DOC-TMP из LLM)."""
        doc_id = doc_id_from_title(title)
        doc = extraction.setdefault("document", {})
        doc["id"] = doc_id
        doc.setdefault("title", title)
        for exp in extraction.get("experiments") or []:
            exp["document_ref"] = doc_id
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
        images: list[dict[str, Any]] | None = None,
        analyze_images: bool = True,
    ) -> dict[str, Any]:
        extraction = await self.review_and_extract(
            title,
            content,
            source=source,
            doc_type=doc_type,
            images=images,
            analyze_images=analyze_images,
        )
        result = {"extraction": extraction}
        if self.graph and extraction.get("decision") != "reject":
            result["ingest"] = await self.ingest_to_graph(extraction)
        return result

    async def _analyze_images(self, images: list[dict[str, Any]]) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._analyze_images_sync, images)

    def _analyze_images_sync(self, images: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not images:
            return None
        try:
            from scinikel.config import settings
            from scinikel.services.vision_analyzer import VisionAnalyzer

            if not settings.vision_enabled:
                return self._analyze_images_fallback(images)

            analyzer = VisionAnalyzer()
            availability = analyzer.check_availability()
            if not availability.get("available"):
                logger.info("Vision unavailable: %s", availability.get("message"))
                return self._analyze_images_fallback(images)

            relevant: list[dict[str, Any]] = []
            for idx, img in enumerate(images[:MAX_VISION_IMAGES]):
                image_name = img.get("alt") or img.get("title") or f"image_{idx + 1}"
                result = None
                if img.get("data"):
                    result = analyzer.analyze_image_from_base64(img["data"], image_name)
                else:
                    path = img.get("temp_path") or img.get("url")
                    if path and Path(path).exists():
                        result = analyzer.analyze_image_from_path(Path(path))

                if not result or not result.get("success"):
                    continue
                analysis_text = result.get("analysis", "")
                relevance = analyzer.check_relevance_to_metallurgy(analysis_text, image_name)
                if relevance.get("is_relevant"):
                    row = {
                        "image_name": image_name,
                        "page": img.get("page"),
                        "analysis": analysis_text,
                        "relevance_score": relevance.get("relevance_score", 0.5),
                        "provider": result.get("provider"),
                    }
                    row.update(
                        self.librarian_annotate_vision(
                            analysis_text,
                            page=img.get("page"),
                            image_name=image_name,
                        )
                    )
                    relevant.append(row)

            if relevant:
                return {
                    "provider": availability.get("provider"),
                    "relevant_images_count": len(relevant),
                    "total_images_analyzed": min(len(images), MAX_VISION_IMAGES),
                    "image_analyses": relevant,
                }
            return self._analyze_images_fallback(images)
        except Exception as exc:
            logger.warning("Image analysis failed: %s", exc)
            return self._analyze_images_fallback(images)

    @staticmethod
    def _analyze_images_fallback(images: list[dict[str, Any]]) -> dict[str, Any] | None:
        rows: list[dict[str, Any]] = []
        for idx, img in enumerate(images[:MAX_VISION_IMAGES]):
            label = img.get("alt") or img.get("title") or ""
            if label:
                row = {
                    "image_name": label,
                    "page": img.get("page"),
                    "analysis": label,
                    "provider": "fallback",
                }
                row.update(
                    CuratorAgent.librarian_annotate_vision(
                        label, page=img.get("page"), image_name=label
                    )
                )
                rows.append(row)
        if not rows:
            return None
        return {
            "provider": "fallback",
            "relevant_images_count": len(rows),
            "total_images_analyzed": len(rows),
            "image_analyses": rows,
        }

    @staticmethod
    def librarian_annotate_vision(
        vision_text: str,
        *,
        page: int | None = None,
        image_name: str = "",
    ) -> dict[str, Any]:
        """
        Аннотация библиотекаря к рисунку — сжатое изложение Vision (паттерн kb_librarian._create_summary).
        """
        from scinikel.search.text_cleanup import summarize_vision_image

        figure_type, summary = summarize_vision_image(vision_text)
        key_points = CuratorAgent._key_points_from_vision(vision_text)
        return {
            "figure_type": figure_type,
            "annotation": summary,
            "librarian_annotation": summary,
            "key_points": key_points,
        }

    @staticmethod
    def _key_points_from_vision(text: str) -> list[str]:
        low = (text or "").lower()
        points: list[str] = []
        if "жесткост" in low or "жёсткост" in low or "кальци" in low:
            points.append("Связь ионов жёсткости воды (Ca²⁺) с флотацией")
        if "гистограм" in low or ("класс" in low and "флотир" in low):
            points.append("Распределение материала по классам флотируемости")
        if "27,52" in low or "27.52" in low:
            points.append("Оптимальная концентрация Ca²⁺ около 27,52 мг/дм³")
        if "44,45" in low or "44.45" in low:
            points.append("Снижение показателей при 44,45 мг/дм³ Ca²⁺")
        if "никел" in low and ("извлечен" in low or "график" in low):
            points.append("Динамика извлечения никеля")
        if "мед" in low and ("извлечен" in low or "cu" in low):
            points.append("Динамика извлечения меди")
        if "кинетик" in low or "констант" in low and "флотац" in low:
            points.append("Кинетика / константы скорости флотации")
        if "микрофото" in low or "микроскоп" in low:
            points.append("Минералогический состав (фон к основным графикам)")
        return list(dict.fromkeys(points))[:5]

    @staticmethod
    def _merge_image_context(content: str, image_analysis: dict[str, Any] | None) -> str:
        if not image_analysis or not image_analysis.get("image_analyses"):
            return content
        blocks = [content, "\n\n--- Аннотации куратора к рисункам ---"]
        for row in image_analysis["image_analyses"]:
            page = row.get("page")
            page_hint = f", стр. {page}" if page else ""
            note = row.get("annotation") or row.get("librarian_annotation") or row.get("analysis", "")
            blocks.append(f"\n[{row.get('image_name', 'image')}{page_hint}]\n{note}")
            for kp in row.get("key_points") or []:
                blocks.append(f"• {kp}")
        return "\n".join(blocks)

    @staticmethod
    def _content_for_llm_extract(content: str, *, max_chars: int = 14000) -> str:
        """Приоритет Vision-описаний и конца статьи (результаты), не только начала PDF."""
        marker = "--- Аннотации куратора к рисункам ---"
        legacy = "--- Описание изображений (Vision) ---"
        if marker in content:
            split_on = marker
        elif legacy in content:
            split_on = legacy
        else:
            split_on = None
        if split_on:
            main, vision = content.split(split_on, 1)
            budget = max_chars // 2
            return (main[:budget] + split_on + vision[:budget])[:max_chars]
        if len(content) <= max_chars:
            return content
        head = max_chars // 3
        tail = max_chars - head
        return content[:head] + "\n\n[...]\n\n" + content[-tail:]

    async def _llm_extract(
        self,
        title: str,
        content: str,
        *,
        source: str | None,
        doc_type: str,
    ) -> dict[str, Any] | None:
        from scinikel.services.llm_runtime import PROVIDER_OLLAMA, get_effective_config

        cfg = get_effective_config()
        llm_timeout: float | None = None
        if cfg.provider == PROVIDER_OLLAMA:
            llm_timeout = max(cfg.ollama_timeout, 300.0)

        body = self._content_for_llm_extract(content)
        prompt = f"""Проанализируй научный/технический документ металлургии и извлеки структурированные данные.

ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source or 'unknown'}
ТИП: {doc_type}

ТЕКСТ (включая описания таблиц/графиков из Vision):
{body}

Верни ТОЛЬКО JSON по схеме:
{EXTRACTION_SCHEMA}

Правила:
- id эксперimentов: EXP-YYYY-NNN если явно указан, иначе сгенерируй уникальный EXP-2024-NNN
- document.id: doc-{{slug}} из заголовка файла, lowercase (напр. doc-giab-ni-cu-flotation-water)
- decision=needs_review для научных статей с лабораторными данными
- цифры извлечения Ni/Cu, pH, Ca2+ — из текста и блока Vision
- не выдумывай цифры — только из текста
"""
        try:
            response = await self.llm.generate(prompt, SYSTEM_PROMPT, timeout=llm_timeout)
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
        doc_id = doc_id_from_title(title)
        experiments: list[dict[str, Any]] = []

        exp_ids = re.findall(r"EXP-\d{4}-\d+", content, flags=re.IGNORECASE)
        materials = re.findall(
            r"(?:Ni[-\s]?Cu|медно[-\s]?никел\w*|никелев\w*\s+руд\w*|Ni-Cu)",
            content,
            flags=re.IGNORECASE,
        )
        modes = re.findall(
            r"(?:флотац\w*(?:\s+pH\s+[\d.]+)?|электролиз\s+[\d.]+°?\s*C|обжиг\s+[\d.]+°?\s*C|"
            r"ион\w+\s+(?:кальци|жёсткост|Ca))",
            content,
            flags=re.IGNORECASE,
        )
        recoveries = re.findall(
            r"(?:извлечен\w*|recovery)\s+(?:мед\w*|никел\w*|Ni|Cu)[^\d]{0,40}(\d+[.,]\d*)\s*%",
            content,
            flags=re.IGNORECASE,
        )

        if exp_ids or (materials and modes):
            experiments.append(
                {
                    "id": exp_ids[0].upper() if exp_ids else f"EXP-{slugify(title)[:12]}",
                    "title": title,
                    "material": materials[0] if materials else "медно-никелевые руды",
                    "mode": modes[0] if modes else "флотация",
                    "property_name": "извлечение",
                    "property_value": f"{recoveries[0]}%" if recoveries else "см. таблицы/графики",
                    "document_ref": doc_id,
                    "topics": ["флотация"] if "флотац" in content.lower() else [],
                }
            )
        elif self._quick_relevance(content) >= 0.5 and ("флотац" in content.lower() or "никел" in content.lower()):
            experiments.append(
                {
                    "id": f"EXP-{slugify(title)[:12]}",
                    "title": title[:120],
                    "material": materials[0] if materials else "медно-никелевые руды",
                    "mode": modes[0] if modes else "флотация (лабораторные испытания)",
                    "property_name": "извлечение Ni/Cu",
                    "property_value": f"{recoveries[0]}%" if recoveries else "см. таблицы/графики в PDF",
                    "document_ref": doc_id,
                    "topics": ["флотация", "никель"],
                }
            )

        has_signal = bool(experiments)
        return {
            "decision": "needs_review" if has_signal else "reject",
            "relevance_score": self._quick_relevance(content),
            "reason": "heuristic extraction (LLM unavailable)" if has_signal else "heuristic: no experiments",
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
