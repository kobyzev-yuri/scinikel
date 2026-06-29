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
    process: str | None = None  # электролиз, флотация, … без конкретного режима
    intent: str = "general"  # alloy_mode_effect | who_did_what | gaps | compare | general


@dataclass
class QueryResult:
    answer: str
    experiments: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    related_entities: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    subgraph: dict[str, Any] | None = None
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    clarification_options: list[dict[str, str]] = field(default_factory=list)


PROCESS_PATTERNS: list[tuple[str, str]] = [
    ("электролиз", r"электролиз"),
    ("флотация", r"флотац"),
    ("обжиг", r"обжиг"),
    ("термообработка", r"термообработк"),
    ("выщелачивание", r"выщелач"),
    ("автоклав", r"автоклав"),
    ("магнитная сепарация", r"магнитн"),
]


class HybridQueryEngine:
    def __init__(self, graph: NetworkXGraphStore, doc_index: DocumentIndex) -> None:
        self.graph = graph
        self.doc_index = doc_index

    def parse_question(self, question: str) -> ParsedQuestion:
        q = question.lower()
        parsed = ParsedQuestion()

        if any(w in q for w in ["пробел", "не исслед", "не делали", "gap"]):
            parsed.intent = "gaps"
        elif re.search(r"сравн|vs\.?|против|разниц|отличи", q):
            parsed.intent = "compare"
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

        if not parsed.mode:
            temp = re.search(r"при\s+([\d.]+)\s*°?\s*c", q, flags)
            if temp:
                temp_val = f"{temp.group(1)}°C"
                if parsed.process:
                    parsed.mode = f"{parsed.process} {temp_val}"
                else:
                    parsed.mode = temp_val

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
            r"ni[-\s]?cu(?:\s+\w+){0,2}\s*(?:сплав\w*|концентрат\w*)",
            r"ni[-\s]?cu\s+сплав\w*",
            r"ni[-\s]?cu\s+концентрат\w*",
            r"сплав\s+[\w-]+",
            r"концентрат\s+[\w-]+",
            r"анодн\w+\s+никел\w*",
        ]
        for pat in material_patterns:
            m = re.search(pat, q, flags)
            if m:
                parsed.material = m.group(0).strip()
                break

        for process_name, pat in PROCESS_PATTERNS:
            if re.search(pat, q, flags):
                parsed.process = process_name
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

    def execute(self, question: str, *, allow_clarification: bool = True) -> QueryResult:
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
            subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=1)
            return QueryResult(
                answer=answer,
                experiments=experiments,
                sources=sources,
                related_entities=related[:20],
                subgraph=subgraph,
            )

        if parsed.intent == "compare":
            return self._execute_compare(question, parsed)

        experiments = self.graph.query_experiments_by_context(
            material=parsed.material,
            mode=parsed.mode,
            property_name=parsed.property_name,
        )
        if parsed.process:
            experiments = self._filter_by_process(experiments, parsed.process)

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

        clarification = self._build_clarification(experiments, parsed) if allow_clarification else None
        if clarification:
            prompt, options = clarification
            subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=1)
            related: list[dict] = []
            for item in experiments[:5]:
                related.extend(item.get("materials", []) + item.get("modes", []))
            return QueryResult(
                answer=prompt,
                experiments=experiments,
                sources=sources,
                related_entities=related[:20],
                subgraph=subgraph,
                needs_clarification=True,
                clarification_prompt=prompt,
                clarification_options=options,
            )

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
            subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=1)

        return QueryResult(
            answer=answer,
            experiments=experiments,
            sources=sources,
            related_entities=related[:20],
            subgraph=subgraph,
        )

    @staticmethod
    def _filter_by_process(experiments: list[dict[str, Any]], process: str) -> list[dict[str, Any]]:
        needle = process.lower()
        filtered: list[dict[str, Any]] = []
        for item in experiments:
            modes = [m["name"] for m in item.get("modes", [])]
            if any(needle in mode.lower() for mode in modes):
                filtered.append(item)
        return filtered

    def _build_clarification(
        self, experiments: list[dict[str, Any]], parsed: ParsedQuestion
    ) -> tuple[str, list[dict[str, str]]] | None:
        if len(experiments) < 2:
            return None
        if parsed.material and parsed.mode:
            return None

        materials: list[str] = []
        seen_materials: set[str] = set()
        modes: list[str] = []
        seen_modes: set[str] = set()
        for item in experiments:
            for material in item.get("materials", []):
                name = material["name"]
                if name not in seen_materials:
                    seen_materials.add(name)
                    materials.append(name)
            for mode in item.get("modes", []):
                name = mode["name"]
                if name not in seen_modes:
                    seen_modes.add(name)
                    modes.append(name)

        if not parsed.material and len(materials) >= 2:
            options: list[dict[str, str]] = []
            for material in materials[:5]:
                if parsed.process:
                    suggestion = f"Что делали по {parsed.process} для {material}?"
                else:
                    suggestion = f"Что делали с {material}?"
                options.append({"label": material, "suggestion": suggestion, "kind": "material"})
            names = ", ".join(materials[:4]) + ("…" if len(materials) > 4 else "")
            prompt = (
                f"Запрос неоднозначен: найдено {len(experiments)} экспериментов по разным материалам "
                f"({names}).\nУточните, какой материал вас интересует."
            )
            return prompt, options

        if parsed.material and not parsed.mode and len(modes) >= 2:
            options = []
            for mode in modes[:5]:
                options.append(
                    {
                        "label": mode,
                        "suggestion": f"Что делали по {mode} для {parsed.material}?",
                        "kind": "mode",
                    }
                )
            prompt = (
                f"По материалу «{parsed.material}» найдено несколько режимов ({len(modes)}). "
                "Уточните режим или параметры процесса."
            )
            return prompt, options

        if parsed.process and not parsed.material and len(modes) >= 2 and len(materials) == 1:
            options = []
            for mode in modes[:5]:
                options.append(
                    {
                        "label": mode,
                        "suggestion": f"Что делали по {mode} для {materials[0]}?",
                        "kind": "mode",
                    }
                )
            prompt = (
                f"По процессу «{parsed.process}» для {materials[0]} есть {len(modes)} режима. "
                "Уточните, какой режим сравниваем."
            )
            return prompt, options

        return None

    def _execute_compare(self, question: str, parsed: ParsedQuestion) -> QueryResult:
        experiments = self.graph.query_experiments_by_context(
            material=parsed.material,
            mode=None,
            property_name=parsed.property_name,
        )
        if parsed.process:
            experiments = self._filter_by_process(experiments, parsed.process)

        mode_filters = re.findall(r"[\d.]+°?\s*c", question.lower())
        if mode_filters:
            filtered: list[dict[str, Any]] = []
            for item in experiments:
                mode_names = " ".join(m["name"].lower() for m in item.get("modes", []))
                if any(
                    token.replace(" ", "").replace("°", "") in mode_names.replace("°", "")
                    for token in mode_filters
                ):
                    filtered.append(item)
            if filtered:
                experiments = filtered

        if len(experiments) < 2:
            experiments = self.graph.query_experiments_by_context(
                material=parsed.material,
                mode=parsed.mode,
                property_name=parsed.property_name,
            )
            if parsed.process:
                experiments = self._filter_by_process(experiments, parsed.process)

        doc_hits = self.doc_index.search(question, limit=3)
        sources = [{"id": h.id, "title": h.metadata.get("title"), "snippet": h.text[:300]} for h in doc_hits]

        if len(experiments) < 2:
            answer = (
                "Для сравнения нужно минимум два эксперимента в графе по этой теме. "
                "Уточните материал и режимы, которые сопоставляем."
            )
            return QueryResult(answer=answer, experiments=experiments, sources=sources)

        lines = ["**Сравнение режимов:**", ""]
        related: list[dict] = []
        for item in experiments[:6]:
            exp = item["experiment"]
            mats = ", ".join(m["name"] for m in item.get("materials", []))
            modes = ", ".join(m["name"] for m in item.get("modes", []))
            measurements = item.get("measurements", [])
            meas_text = "; ".join(
                f"{m.get('value', '?')}" + (f" ({m.get('delta')})" if m.get("delta") else "")
                for m in measurements
            )
            concl = "; ".join(c.get("description", c.get("name", "")) for c in item.get("conclusions", []))
            lines.append(
                f"• **{modes}** ({exp['id']}): {meas_text}. {concl}"
                + (f" Материал: {mats}." if mats else "")
            )
            related.extend(item.get("materials", []) + item.get("modes", []))

        if len(experiments) == 2:
            lines.append("")
            lines.append(
                "_Итог: сравните значения свойства и дельты по строкам выше — "
                "в данных указан базовый режим и улучшенный вариант._"
            )

        subgraph = self.graph.subgraph(experiments[0]["experiment"]["id"], depth=1)
        return QueryResult(
            answer="\n".join(lines),
            experiments=experiments,
            sources=sources,
            related_entities=related[:20],
            subgraph=subgraph,
        )
