"""Hybrid query: graph traversal + semantic search."""

import re
from dataclasses import dataclass, field
from typing import Any

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.search.index import DocumentIndex, SearchHit
from scinikel.search.snippet import VISION_MARKER, extract_snippet, page_hint_from_text
from scinikel.search.text_cleanup import flotation_image_rank_bonus, summarize_vision_image
from scinikel.search.pdf_images import media_image_url


@dataclass
class ParsedQuestion:
    material: str | None = None
    mode: str | None = None
    property_name: str | None = None
    topic: str | None = None
    process: str | None = None  # электролиз, флотация, … без конкретного режима
    doc_id: str | None = None
    intent: str = "general"  # alloy_mode_effect | who_did_what | gaps | compare | document_media | general


@dataclass
class QueryResult:
    answer: str
    experiments: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    related_entities: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    subgraph: dict[str, Any] | None = None
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    clarification_options: list[dict[str, str]] = field(default_factory=list)
    scoped_doc_id: str | None = None


PROCESS_PATTERNS: list[tuple[str, str]] = [
    ("электролиз", r"электролиз"),
    ("флотация", r"флотац"),
    ("обжиг", r"обжиг"),
    ("термообработка", r"термообработк"),
    ("выщелачивание", r"выщелач"),
    ("автоклав", r"автоклав"),
    ("магнитная сепарация", r"магнитн"),
]

DOC_REF_PATTERNS: list[tuple[str, str]] = [
    (r"doc-giab-ni-cu-flotation-water", "doc-giab-ni-cu-flotation-water"),
    (r"giab-ni-cu-flotation-water", "doc-giab-ni-cu-flotation-water"),
    (r"\bгиаб\b", "doc-giab-ni-cu-flotation-water"),
]

MEDIA_MARKERS = (
    "график",
    "рисунк",
    "таблиц",
    "схем",
    "картин",
    "иллюстрац",
    "figure",
    "vision",
    "стр.",
    "страниц",
)


def scoped_document_id(message: str) -> str | None:
    """Запрос явно ограничен PDF-документом (графики/таблицы/жёсткость)."""
    q = message.lower()
    doc_id: str | None = None
    for pat, did in DOC_REF_PATTERNS:
        if re.search(pat, message, flags=re.IGNORECASE):
            doc_id = did
            break
    if not doc_id:
        return None
    if any(marker in q for marker in MEDIA_MARKERS):
        return doc_id
    if re.search(r"жё?сткост|кальци", q, flags=re.IGNORECASE):
        return doc_id
    return None


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

        for doc_pat, doc_id in DOC_REF_PATTERNS:
            if re.search(doc_pat, q, flags):
                parsed.doc_id = doc_id
                break

        if parsed.doc_id and (
            any(marker in q for marker in MEDIA_MARKERS)
            or re.search(r"кальци|жё?сткост", q, flags)
        ):
            parsed.intent = "document_media"

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

        if parsed.intent == "document_media" and parsed.doc_id:
            return self._execute_document_media(question, parsed)

        if parsed.intent == "who_did_what":
            experiments = self.graph.query_who_did_what(topic=parsed.topic)
            sources, images = self._retrieve_context(question, experiments)
            if not experiments:
                answer = (
                    "Не найдено экспериментов с указанием команды или установки по этой теме."
                )
                return QueryResult(answer=answer, sources=sources, images=images)

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
                images=images,
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

        sources, images = self._retrieve_context(question, experiments)

        if not experiments:
            if sources or images:
                answer = (
                    "В графе экспериментов точного совпадения нет, но в документах есть релевантные фрагменты. "
                    "Смотрите источники ниже."
                )
            else:
                answer = (
                    "По вашему запросу данных пока нет. "
                    "Уточните материал, режим или свойство — или дождитесь загрузки корпуса документов."
                )
            return QueryResult(answer=answer, sources=sources, images=images)

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
                images=images,
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
            images=images,
            related_entities=related[:20],
            subgraph=subgraph,
        )

    def _retrieve_context(
        self,
        question: str,
        experiments: list[dict[str, Any]],
        *,
        doc_limit: int = 5,
        image_limit: int = 3,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        doc_boost = self._doc_filters_from_experiments(experiments)
        doc_hits = self.doc_index.search(
            question, limit=doc_limit, filters=doc_boost, retrieve_k=30
        )
        doc_hits = self._merge_report_supplements(question, doc_hits, max_extra=2)
        sources = [self._format_doc_source(hit, question) for hit in doc_hits]
        images = self._search_image_sources(question, limit=image_limit)
        return sources, images

    def _merge_report_supplements(
        self,
        question: str,
        hits: list[SearchHit],
        *,
        max_extra: int = 2,
    ) -> list[SearchHit]:
        """Добавить PDF-отчёты (giab и др.), если чанки без EXP-* не попали в top."""
        if max_extra <= 0:
            return hits
        seen = {(h.metadata or {}).get("doc_id") or h.id for h in hits}
        try:
            extra = self.doc_index.search(
                question,
                limit=max_extra + len(seen),
                filters={"doc_type": "report"},
                retrieve_k=20,
            )
        except Exception:
            return hits
        merged = list(hits)
        for hit in extra:
            doc_id = (hit.metadata or {}).get("doc_id") or hit.id
            if doc_id in seen:
                continue
            if not str(doc_id).startswith("doc-"):
                continue
            merged.append(hit)
            seen.add(doc_id)
            if len(merged) >= len(hits) + max_extra:
                break
        return merged

    def _execute_document_media(self, question: str, parsed: ParsedQuestion) -> QueryResult:
        """Поиск по графикам/таблицам конкретного документа — без уточнения материала в графе."""
        doc_id = parsed.doc_id
        assert doc_id

        if not self.doc_index.has_doc_chunks(doc_id):
            self.doc_index.ensure_doc_indexed(doc_id)
        else:
            self.doc_index.ensure_doc_images_indexed(doc_id)

        queries = self._document_media_queries(question, doc_id)
        image_queries = self._document_media_image_queries(question, doc_id)
        hits = self._search_document_chunks(doc_id, queries, limit=6)
        sources = [self._format_doc_source(hit, question, snippet_len=480) for hit in hits]
        images = self._search_image_sources(
            question, limit=6, doc_id=doc_id, extra_queries=image_queries
        )

        lines = [f"**Материалы из документа** `{doc_id}`:", ""]
        if not sources and not images:
            tried = []
            if self.doc_index.doc_chunk_count(doc_id) > 0:
                tried.append("чанки в индексе есть, но по запросу ничего не нашлось")
            else:
                tried.append("нет чанков в BM25")
            lines.append(
                "Фрагменты не найдены. Загрузите PDF в «Базе знаний» "
                f"(giab-ni-cu-flotation-water.pdf) с Vision и CLIP, или положите файл в data/samples/. "
                f"({'; '.join(tried)})"
            )
        else:
            if sources:
                lines.append("**Текст и Vision-фрагменты:**")
                for idx, source in enumerate(sources[:6], start=1):
                    page = f", стр. {source['page_hint']}" if source.get("page_hint") else ""
                    kind = source.get("excerpt_type") or "фрагмент"
                    snippet = (source.get("snippet") or "")[:320].replace("\n", " ")
                    chunk = source.get("chunk_id") or ""
                    chunk_txt = f" [{chunk}]" if chunk else ""
                    lines.append(
                        f"{idx}. {source.get('title', doc_id)}{page}{chunk_txt} ({kind}): {snippet}…"
                    )
            if images:
                lines.append("")
                lines.append("**Рисунки (CLIP):**")
                for idx, image in enumerate(images[:4], start=1):
                    page = f", стр. {image['page']}" if image.get("page") else ""
                    title = image.get("title") or image.get("id") or "рисунок"
                    score = image.get("score")
                    score_txt = f" (score {score})" if score is not None else ""
                    lines.append(f"{idx}. {title}{page}{score_txt}")

        return QueryResult(
            answer="\n".join(lines),
            sources=sources,
            images=images,
            scoped_doc_id=doc_id,
        )

    @staticmethod
    def _document_media_queries(question: str, doc_id: str) -> list[str]:
        stripped = re.sub(re.escape(doc_id), "", question, flags=re.IGNORECASE)
        stripped = re.sub(r"гиаб[-\w]*", "", stripped, flags=re.IGNORECASE).strip(" :?.,\n")
        queries: list[str] = []
        if stripped:
            queries.append(stripped)
        q_lower = question.lower()
        if re.search(r"жё?сткост", q_lower):
            queries.append("ионы жесткости воды флотация пенный слой таблица")
            queries.append("концентрация кальция пульпа 27,52 извлечение никеля")
        if "кальци" in q_lower:
            queries.append("концентрация кальция пульпа извлечение никеля")
        if any(m in q_lower for m in ("график", "рисунк", "таблиц", "кинетик")):
            queries.append("таблица график извлечение флотация кинетика")
        return list(dict.fromkeys(queries)) or [question]

    @staticmethod
    def _document_media_image_queries(question: str, doc_id: str) -> list[str]:
        """CLIP-запросы: таблицы/графики флотации (англ. + рус. — OpenCLIP мультиязычный)."""
        q_lower = question.lower()
        queries = [
            "scientific chart graph table flotation extraction nickel copper",
            "таблица график флотация извлечение никель медь кальций",
            "flotation kinetics chart hardness ions calcium pulp",
        ]
        if re.search(r"жё?сткост", q_lower):
            queries.append("water hardness ions flotation foam stability chart")
        if "кальци" in q_lower:
            queries.append("calcium concentration pulp flotation table")
        if any(m in q_lower for m in ("график", "рисунк", "таблиц")):
            queries.insert(0, "table figure chart diagram scientific paper")
        stripped = re.sub(re.escape(doc_id), "", question, flags=re.IGNORECASE).strip(" :?.,\n")
        if stripped and len(stripped) > 12:
            queries.append(stripped[:120])
        return list(dict.fromkeys(queries))

    def _search_document_chunks(
        self, doc_id: str, queries: list[str], *, limit: int = 6
    ) -> list[SearchHit]:
        seen: set[str] = set()
        merged: list[SearchHit] = []
        doc_filters = {"doc_ids": [doc_id]}
        for query in queries:
            for hit in self.doc_index.search(
                query, limit=limit, filters=doc_filters, retrieve_k=25
            ):
                meta = hit.metadata or {}
                if meta.get("doc_id") != doc_id:
                    continue
                chunk_id = meta.get("chunk_id") or hit.id
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                merged.append(hit)
        ranked = self._rank_document_media_hits(merged, queries)
        filtered = [h for h in ranked if not HybridQueryEngine._is_title_chunk(h)]
        return (filtered or ranked)[:limit]

    @staticmethod
    def _is_title_chunk(hit: SearchHit) -> bool:
        text = hit.text or ""
        chunk_id = (hit.metadata or {}).get("chunk_id") or hit.id
        if chunk_id.endswith("#c0"):
            return True
        return "©" in text and "гиаб" in text.lower()

    @staticmethod
    def _rank_document_media_hits(
        hits: list[SearchHit], queries: list[str]
    ) -> list[SearchHit]:
        topic = " ".join(queries).lower()

        def rank_key(hit: SearchHit) -> tuple[float, float]:
            text = (hit.text or "").lower()
            bonus = 0.0
            if "жесткост" in text or "жёсткост" in text:
                bonus += 8.0
            if "табл" in text:
                bonus += 4.0
            if "27,52" in text or "27.52" in text:
                bonus += 10.0
            if "кальци" in text:
                bonus += 4.0
            if "пенн" in text and "пен" in topic:
                bonus += 3.0
            if "©" in text or "благодарност" in text or "miab" in text:
                bonus -= 12.0
            if "аннотац" in text or "ключевые слова" in text:
                bonus -= 6.0
            if (hit.metadata or {}).get("chunk_id", "").endswith("#c0"):
                bonus -= 15.0
            return (bonus, float(hit.score))

        return sorted(hits, key=rank_key, reverse=True)

    @staticmethod
    def _format_doc_source(
        hit: SearchHit, question: str, *, snippet_len: int = 360
    ) -> dict[str, Any]:
        meta = hit.metadata or {}
        chunk_id = meta.get("chunk_id")
        page = meta.get("page") or page_hint_from_text(hit.text or "")
        text = hit.text or ""
        if chunk_id:
            snippet = text[:snippet_len]
            excerpt_type = (
                "vision"
                if VISION_MARKER in text or "Vision" in text
                else "chunk"
            )
        else:
            excerpt = extract_snippet(text, question)
            snippet = excerpt["snippet"]
            excerpt_type = excerpt["excerpt_type"]
            page = page or excerpt.get("page_hint")
        return {
            "id": meta.get("doc_id") or hit.id,
            "chunk_id": chunk_id,
            "title": meta.get("title") or hit.id,
            "snippet": snippet,
            "excerpt_type": excerpt_type,
            "page_hint": page,
            "score": round(float(hit.score), 3) if hit.score else None,
            "doc_type": meta.get("doc_type") or "",
        }

    def _search_image_sources(
        self,
        question: str,
        *,
        limit: int = 3,
        doc_id: str | None = None,
        extra_queries: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        queries = list(dict.fromkeys([question, *(extra_queries or [])]))
        threshold = 0.08 if doc_id else 0.12
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        try:
            for query in queries:
                hits = self.doc_index.search_images(query, limit=limit, doc_id=doc_id)
                for hit in hits:
                    if hit.score < threshold or hit.id in seen:
                        continue
                    seen.add(hit.id)
                    rows.append(self._format_image_source(hit))
                if len(rows) >= limit:
                    break
            rows.sort(
                key=lambda r: (r.get("score") or 0) + flotation_image_rank_bonus(
                    r.get("snippet") or "", question
                ),
                reverse=True,
            )
            q_low = question.lower()
            if doc_id and any(k in q_low for k in ("график", "таблиц", "жёсткост", "жесткост", "флотир")):
                charts = [
                    r
                    for r in rows
                    if "микрофото" not in (r.get("media_label") or r.get("title") or "").lower()
                ]
                micro = [r for r in rows if r not in charts]
                rows = charts + micro
            return rows[:limit]
        except Exception:
            return []

    @staticmethod
    def _format_image_source(hit: SearchHit) -> dict[str, Any]:
        meta = hit.metadata or {}
        alt = meta.get("alt") or meta.get("title") or hit.id
        image_id = hit.id
        content = meta.get("librarian_annotation") or meta.get("content") or meta.get("abstract") or hit.text or alt
        if meta.get("librarian_annotation"):
            label = meta.get("figure_type") or alt
            summary = meta["librarian_annotation"]
            key_points = meta.get("key_points") or []
        elif meta.get("content") and len(meta.get("content", "")) > 60:
            from scinikel.agent.curator import CuratorAgent

            ann = CuratorAgent.librarian_annotate_vision(
                meta["content"], page=meta.get("page"), image_name=alt
            )
            label = ann["figure_type"]
            summary = ann["annotation"]
            key_points = ann["key_points"]
        elif meta.get("content"):
            label, summary = summarize_vision_image(content)
            key_points = []
        else:
            label, summary = alt, (content[:220] if content else alt)
            key_points = []
        return {
            "id": image_id,
            "title": label,
            "media_label": label,
            "snippet": summary,
            "librarian_annotation": meta.get("librarian_annotation") or summary,
            "key_points": key_points,
            "figure_type": meta.get("figure_type") or label,
            "excerpt_type": meta.get("excerpt_type") or ("vision" if meta.get("content") else "image"),
            "score": round(float(hit.score), 3),
            "page": meta.get("page"),
            "doc_id": meta.get("doc_id"),
            "doc_title": meta.get("doc_title") or meta.get("title"),
            "image_url": media_image_url(image_id),
            "mime_type": meta.get("mime_type"),
        }

    @staticmethod
    def _doc_filters_from_experiments(experiments: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Graph-aware doc search — boost/filter как metadata hybrid в 3dtoday."""
        if not experiments:
            return None
        experiment_ids = [item["experiment"]["id"] for item in experiments if item.get("experiment")]
        if not experiment_ids:
            return None
        return {"experiment_ids": experiment_ids[:10]}

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

        sources, images = self._retrieve_context(question, experiments)

        if len(experiments) < 2:
            answer = (
                "Для сравнения нужно минимум два эксперимента в графе по этой теме. "
                "Уточните материал и режимы, которые сопоставляем."
            )
            return QueryResult(answer=answer, experiments=experiments, sources=sources, images=images)

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
            images=images,
            related_entities=related[:20],
            subgraph=subgraph,
        )
