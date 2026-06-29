"""Hybrid query: graph traversal + semantic search."""

import re
from dataclasses import dataclass, field
from typing import Any

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.search.index import DocumentIndex


@dataclass
class ParsedQuestion:
    material: str | None = None
    mode: str | None = None
    property_name: str | None = None
    topic: str | None = None
    intent: str = "general"  # alloy_mode_effect | who_did_what | gaps | general


@dataclass
class QueryResult:
    answer: str
    experiments: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    related_entities: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    subgraph: dict[str, Any] | None = None


class HybridQueryEngine:
    def __init__(self, graph: NetworkXGraphStore, doc_index: DocumentIndex) -> None:
        self.graph = graph
        self.doc_index = doc_index

    def parse_question(self, question: str) -> ParsedQuestion:
        q = question.lower()
        parsed = ParsedQuestion()

        if any(w in q for w in ["пробел", "не исслед", "не делали", "gap"]):
            parsed.intent = "gaps"
        elif any(w in q for w in ["кто", "команда", "лаборатор", "установк"]):
            parsed.intent = "who_did_what"
        elif any(w in q for w in ["сплав", "концентрат", "материал", "ni-cu", "никел"]):
            parsed.intent = "alloy_mode_effect"

        flags = re.IGNORECASE

        mode_patterns = [
            r"флотац\w*(?:\s+ph\s+[\d.]+)?",
            r"электролиз\s+[\d.]+°?c",
            r"обжиг\s+[\d.]+°?c",
            r"термообработк\w*[\s\d/°cч]+",
            r"ph\s+[\d.]+",
        ]
        for pat in mode_patterns:
            m = re.search(pat, q, flags)
            if m:
                parsed.mode = m.group(0).strip()
                break

        prop_patterns = [
            r"извлечен\w*\s+ni",
            r"прочност\w+\s+на\s+разрыв",
            r"содержан\w+\s+ni",
            r"зольност\w+",
        ]
        for pat in prop_patterns:
            m = re.search(pat, q, flags)
            if m:
                parsed.property_name = m.group(0).strip()
                break

        material_patterns = [
            r"ni[-\s]?cu(?:\s+\w+){0,2}\s*(?:сплав|концентрат\w*)",
            r"ni[-\s]?cu\s+сплав",
            r"ni[-\s]?cu\s+концентрат\w*",
            r"сплав\s+[\w-]+",
            r"концентрат\s+[\w-]+",
        ]
        for pat in material_patterns:
            m = re.search(pat, q, flags)
            if m:
                parsed.material = m.group(0).strip()
                break

        if parsed.intent == "who_did_what":
            topic_patterns = [
                r"электролиз\w*",
                r"флотац\w*",
                r"обжиг\w*",
                r"термообработк\w*",
                r"никел\w*",
                r"сплав\w*",
            ]
            for pat in topic_patterns:
                m = re.search(pat, q, flags)
                if m:
                    parsed.topic = m.group(0).strip()
                    break
            if not parsed.topic:
                parsed.topic = question

        return parsed

    def execute(self, question: str) -> QueryResult:
        parsed = self.parse_question(question)

        if parsed.intent == "gaps":
            gaps = self.graph.find_gaps(
                materials=[parsed.material] if parsed.material else None,
                modes=[parsed.mode] if parsed.mode else None,
            )
            if gaps:
                lines = [f"• {g['material']} × {g['mode']} — не исследовано" for g in gaps[:10]]
                answer = "Обнаружены пробелы в данных:\n" + "\n".join(lines)
            else:
                answer = "Явных пробелов по известным комбинациям материал×режим не найдено."
            return QueryResult(answer=answer, gaps=gaps)

        if parsed.intent == "who_did_what":
            experiments = self.graph.query_who_did_what(topic=parsed.topic)
            doc_hits = self.doc_index.search(question, limit=3)
            sources = [
                {"id": h.id, "title": h.metadata.get("title"), "snippet": h.text[:300]}
                for h in doc_hits
            ]
            if not experiments:
                answer = (
                    "Не найдено экспериментов с указанием команды или установки по этой теме."
                )
                return QueryResult(answer=answer, sources=sources)

            lines = []
            related: list[dict] = []
            for item in experiments:
                exp = item["experiment"]
                teams = ", ".join(t["name"] for t in item.get("teams", [])) or "—"
                equip = ", ".join(e["name"] for e in item.get("equipment", [])) or "—"
                modes = ", ".join(m["name"] for m in item.get("modes", []))
                lines.append(
                    f"**{exp['name']}** ({exp['id']}): команда — {teams}; установка — {equip}; режим — {modes}"
                )
                related.extend(item.get("teams", []) + item.get("equipment", []))

            answer = f"Найдено записей: {len(experiments)}\n\n" + "\n\n".join(lines)
            subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=2)
            return QueryResult(
                answer=answer,
                experiments=experiments,
                sources=sources,
                related_entities=related[:20],
                subgraph=subgraph,
            )

        experiments = self.graph.query_experiments_by_context(
            material=parsed.material,
            mode=parsed.mode,
            property_name=parsed.property_name,
        )

        doc_hits = self.doc_index.search(question, limit=3)
        sources = [{"id": h.id, "title": h.metadata.get("title"), "snippet": h.text[:300]} for h in doc_hits]

        if not experiments:
            if doc_hits:
                answer = (
                    "В графе экспериментов точного совпадения нет, но в документах есть релевантные фрагменты. "
                    "Смотрите источники ниже."
                )
            else:
                answer = (
                    "По вашему запросу данных пока нет. "
                    "Уточните материал, режим или свойство — или дождитесь загрузки корпуса документов."
                )
            return QueryResult(answer=answer, sources=sources)

        lines = []
        related: list[dict] = []
        for item in experiments:
            exp = item["experiment"]
            mats = ", ".join(m["name"] for m in item.get("materials", []))
            modes = ", ".join(m["name"] for m in item.get("modes", []))
            measurements = item.get("measurements", [])
            meas_text = "; ".join(
                f"{m.get('value', '?')}" + (f" ({m.get('delta')})" if m.get("delta") else "")
                for m in measurements
            )
            teams = ", ".join(t["name"] for t in item.get("teams", []))
            equip = ", ".join(e["name"] for e in item.get("equipment", []))
            concl = "; ".join(c.get("description", c.get("name", "")) for c in item.get("conclusions", []))

            lines.append(
                f"**{exp['name']}** ({exp['id']}): материал — {mats}; режим — {modes}; "
                f"результат — {meas_text}. {concl}"
                + (f" Команда: {teams}." if teams else "")
                + (f" Установка: {equip}." if equip else "")
            )
            related.extend(item.get("materials", []) + item.get("modes", []) + item.get("teams", []))

        answer = "Найдено экспериментов: {}\n\n".format(len(experiments)) + "\n\n".join(lines)

        subgraph = None
        if experiments:
            subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=2)

        return QueryResult(
            answer=answer,
            experiments=experiments,
            sources=sources,
            related_entities=related[:20],
            subgraph=subgraph,
        )
