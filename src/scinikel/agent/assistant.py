"""Dialog agent: LLM + graph/search tools, with rule-based fallback."""

import re
from dataclasses import dataclass, field
from typing import Any

from scinikel.agent.structured_answer import (
    ensure_table_in_answer,
    format_document_media_answer,
    format_structured_answer,
)
from scinikel.query.engine import HybridQueryEngine, QueryResult, scoped_document_id
from scinikel.services.llm import get_llm_client
from scinikel.services.llm_runtime import should_use_llm


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
Отвечай сразу по делу — без рассуждений вслух и без скрытых блоков рассуждений.
Учитывай предыдущие реплики диалога: на уточняющие вопросы («а кто?», «подробнее», «сравни…»)
отвечай в контексте уже обсуждённой темы.
Если пользователь соглашается на предложение из твоего предыдущего ответа («да», «давай», «сравни», «свести в таблицу», «что именно улучшает»),
выполни его сразу по уже известному контексту диалога (материал, режим, сравнение) — не задавай повторных наводящих вопросов.
Если просят таблицу — оформи markdown-таблицу с колонками: Эксперимент | Материал | Режим | Результат | Комментарий.
Если данных недостаточно — скажи прямо и предложи уточнить материал, режим или свойство.
Если в контексте указано, что запрос неоднозначен и пользователь ещё не выбрал вариант,
перечисли варианты и попроси уточнить.
Не выдумывай эксперименты и цифры.
Если во «Источниках» есть фрагмент документа с doc_id, chunk_id или номером страницы — обязательно укажи их в ответе.
Дополняй ответ графа данными из PDF-отчётов (giab и др.), если они есть в источниках — не проси пользователя прислать документ."""

TABLE_USER_INSTRUCTION = (
    "\n\nОформи ответ как markdown-таблицу (колонки: Эксперимент | Материал | Режим | Результат | Комментарий) "
    "по экспериментам из контекста и истории диалога. "
    "Не проси уточнить материал — он уже известен. Только таблица и краткий итог (1–2 предложения)."
)

TOOL_CONTEXT_TEMPLATE = """
## Данные из графа знаний (по текущему запросу)
{graph_answer}

## Источники (документы и фрагменты)
{sources}

## Рисунки (CLIP)
{images}

## Связанные сущности
{related}
"""

MATERIAL_HINTS = (
    "ni",
    "никел",
    "сплав",
    "концентрат",
    "cu",
    "мед",
    "вольфрам",
    "шлам",
    "обжиг",
    "флотац",
    "электролиз",
    "выщелач",
    "автоклав",
    "корроз",
)

AFFIRMATIVE_MARKERS = (
    "да",
    "давай",
    "хочу",
    "ок",
    "окей",
    "хорошо",
    "пожалуйста",
    "согласен",
    "ага",
    "угу",
)

COMPARE_MARKERS = (
    "сравни",
    "сравнение",
    "сопостав",
    "vs",
    "против",
    "разниц",
    "отличи",
)

DETAIL_MARKERS = (
    "что именно",
    "почему",
    "зачем",
    "объясни",
    "улучша",
    "расскажи",
    "подробн",
    "как это",
    "в чём",
    "в чем",
)

FORMAT_MARKERS = (
    "таблиц",
    "свести",
    "сводк",
    "резюме",
    "итог",
    "кратко в",
)

DIALOG_MATERIAL_PATTERNS: list[tuple[str, str]] = [
    (r"анодн\w+\s+никел\w*", "анодный никель"),
    (r"ni[-\s]?cu\s+сплав\w*", "Ni-Cu сплав"),
    (r"ni[-\s]?cu\s+(?:сульфидн\w+\s+)?концентрат\w*", "Ni-Cu сульфидный концентрат"),
    (r"медн\w+\s+концентрат\w*", "медный концентрат"),
    (r"вольфрамов\w+\s+шлам\w*", "вольфрамовый шлам"),
]

DIALOG_PROCESS_PATTERNS: list[tuple[str, str]] = [
    (r"электролиз\w*", "электролиз"),
    (r"флотац\w*", "флотация"),
    (r"обжиг\w*", "обжиг"),
    (r"термообработк\w*", "термообработка"),
    (r"выщелач\w*", "выщелачивание"),
    (r"автоклав\w*", "автоклав"),
]


class ResearchAgent:
    def __init__(self, query_engine: HybridQueryEngine) -> None:
        self.query_engine = query_engine

    @property
    def llm(self):
        return get_llm_client()

    def chat(self, user_message: str, history: list[ChatMessage] | None = None) -> AgentResponse:
        prior = list(history or [])
        doc_scope = scoped_document_id(user_message)

        if doc_scope:
            query_text = user_message
            skip_clarification = True
            query_result = self.query_engine.execute(query_text, allow_clarification=False)
        else:
            query_text = self._resolve_query_text(user_message, prior)
            skip_clarification = self._should_skip_clarification(user_message, prior)
            query_result = self.query_engine.execute(query_text, allow_clarification=not skip_clarification)

        if not doc_scope and query_result.needs_clarification and skip_clarification:
            retry_text = self._expand_format_query(user_message, prior) or query_text
            retry = self.query_engine.execute(retry_text, allow_clarification=False)
            if not retry.needs_clarification:
                query_result = retry
            elif self._is_format_request(user_message, prior) and should_use_llm() and self.llm.available:
                query_result = QueryResult(
                    answer="Сводка по уже обсуждённым экспериментам из диалога.",
                    experiments=[],
                )

        llm_used = False
        wants_table = self._is_format_request(user_message, prior)
        if query_result.scoped_doc_id:
            wants_table = False

        if query_result.needs_clarification:
            message = self._clarification_answer(query_result)
        elif query_result.scoped_doc_id:
            message = format_document_media_answer(query_result)
        elif not should_use_llm():
            message = format_structured_answer(query_result, wants_table=wants_table)
        elif self.llm.available:
            try:
                message = self._llm_answer(user_message, query_result, prior, wants_table=wants_table)
                message = ensure_table_in_answer(message, query_result, wants_table=wants_table)
                llm_used = True
            except Exception:
                message = format_structured_answer(query_result, wants_table=wants_table)
        else:
            message = format_structured_answer(query_result, wants_table=wants_table)

        citations = self._build_citations(query_result)

        return AgentResponse(
            message=message,
            query_result=query_result,
            citations=citations,
            llm_used=llm_used,
        )

    @staticmethod
    def _build_citations(query_result: QueryResult) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        image_citations = [{"type": "image", **image} for image in query_result.images[:6]]
        doc_citations = [{"type": "document", **source} for source in query_result.sources[:5]]

        if query_result.scoped_doc_id:
            citations.extend(image_citations)
            citations.extend(doc_citations)
            return citations

        for item in query_result.experiments[:6]:
            exp = item.get("experiment") or {}
            mats = ", ".join(m["name"] for m in item.get("materials", [])[:2])
            modes = ", ".join(m["name"] for m in item.get("modes", [])[:2])
            measurements = item.get("measurements", [])
            meas = "; ".join(
                str(m.get("value", "")) for m in measurements[:2] if m.get("value")
            )
            snippet_parts = [p for p in (modes, mats, meas) if p]
            citations.append(
                {
                    "type": "experiment",
                    "id": exp.get("id"),
                    "title": exp.get("name") or exp.get("id"),
                    "snippet": " · ".join(snippet_parts) or None,
                    "modes": modes or None,
                    "materials": mats or None,
                }
            )
        citations.extend(doc_citations)
        citations.extend(image_citations)
        return citations

    def _resolve_query_text(self, message: str, history: list[ChatMessage]) -> str:
        if not history:
            return message

        expanded = self._expand_format_query(message, history)
        if expanded:
            return expanded

        expanded = self._expand_from_dialog(message, history)
        if expanded:
            return expanded

        if self._is_follow_up(message, history):
            return self._merge_with_dialog_context(message, history)
        return message

    def _merge_with_dialog_context(self, message: str, history: list[ChatMessage]) -> str:
        ctx = self._extract_dialog_context(history)
        anchor = self._last_user_message(history)
        parts: list[str] = []
        if anchor:
            parts.append(anchor)
        if ctx.get("material") and ctx["material"].lower() not in message.lower():
            parts.append(f"Контекст: материал {ctx['material']}")
        if ctx.get("process") and ctx["process"].lower() not in message.lower():
            parts.append(f"процесс {ctx['process']}")
        if ctx.get("mode") and ctx["mode"].lower() not in message.lower():
            parts.append(f"режим {ctx['mode']}")
        parts.append(f"Уточнение: {message}")
        return "\n".join(parts)

    @staticmethod
    def _extract_dialog_context(history: list[ChatMessage]) -> dict[str, str]:
        if not history:
            return {}
        blob = "\n".join(m.content for m in history[-10:])
        blob_lower = blob.lower()
        ctx: dict[str, str] = {}

        material_line = re.search(r"материал:\s*([^\n•]+)", blob_lower, re.IGNORECASE)
        if material_line:
            ctx["material"] = material_line.group(1).strip(" -—")
        else:
            for pattern, name in DIALOG_MATERIAL_PATTERNS:
                if re.search(pattern, blob_lower, re.IGNORECASE):
                    ctx["material"] = name
                    break

        mode_line = re.search(r"режим:\s*([^\n•]+)", blob_lower, re.IGNORECASE)
        if mode_line:
            ctx["mode"] = mode_line.group(1).strip(" -—")
        else:
            mode_match = re.search(r"электролиз\s+[\d.]+°?\s*c", blob_lower, re.IGNORECASE)
            if mode_match:
                ctx["mode"] = mode_match.group(0)
            else:
                for pattern, name in DIALOG_PROCESS_PATTERNS:
                    if re.search(pattern, blob_lower, re.IGNORECASE):
                        ctx["process"] = name
                        break

        if "электролиз" in blob_lower and "process" not in ctx:
            ctx["process"] = "электролиз"

        return ctx

    @staticmethod
    def _extract_dialog_materials(history: list[ChatMessage]) -> list[str]:
        if not history:
            return []
        blob_lower = "\n".join(m.content for m in history[-10:]).lower()
        found: list[str] = []
        for pattern, name in DIALOG_MATERIAL_PATTERNS:
            if re.search(pattern, blob_lower, re.IGNORECASE) and name not in found:
                found.append(name)
        if re.search(r"ni[-\s]?cu", blob_lower, re.IGNORECASE) and not any(
            "Ni-Cu" in m for m in found
        ):
            found.append("Ni-Cu сплав")
        return found

    def _expand_format_query(self, message: str, history: list[ChatMessage]) -> str | None:
        if not history or not self._is_format_request(message, history):
            return None

        q = message.strip().lower()
        blob_lower = "\n".join(m.content for m in history[-8:]).lower()
        materials = self._extract_dialog_materials(history)

        if "анодный никель" in materials and "Ni-Cu сплав" in materials:
            return (
                "Сравни электролиз Ni-Cu сплава при 220°C, Ni-Cu сплава при 250°C "
                "и анодный никель при 250°C по чистоте Ni в катоде"
            )

        if len(materials) >= 2:
            return f"Сравни эксперименты по материалам: {', '.join(materials)}. {message}"

        ctx = self._extract_dialog_context(history)
        if ctx.get("material"):
            process = ctx.get("process") or "процессе"
            return f"Сводка по {ctx['material']} ({process}). {message}"

        if "сравн" in blob_lower:
            return f"Сравни режимы из контекста диалога. {message}"

        return None

    def _is_format_request(self, message: str, history: list[ChatMessage]) -> bool:
        if scoped_document_id(message):
            return False
        if not history:
            return False
        q = message.strip().lower()
        if any(marker in q for marker in FORMAT_MARKERS):
            return True
        last_assistant = self._last_assistant_message(history)
        if last_assistant and any(marker in last_assistant.lower() for marker in FORMAT_MARKERS):
            return self._is_affirmative(message) or any(marker in q for marker in ("это", "свод", "свести"))
        return False

    def _should_skip_clarification(self, message: str, history: list[ChatMessage]) -> bool:
        if self._is_format_request(message, history):
            return True
        if self._is_affirmative_or_compare(message, history):
            return True
        dialog_ctx = self._extract_dialog_context(history)
        if dialog_ctx.get("material") and self._is_follow_up(message, history):
            return True
        if len(self._extract_dialog_materials(history)) >= 2 and self._is_follow_up(message, history):
            return True
        return False

    def _expand_from_dialog(self, message: str, history: list[ChatMessage]) -> str | None:
        if not history:
            return None

        q = message.strip().lower()
        blob_lower = "\n".join(m.content for m in history[-8:]).lower()
        last_user = self._last_user_message(history)
        last_assistant = self._last_assistant_message(history)
        ctx = self._extract_dialog_context(history)

        if any(marker in q for marker in DETAIL_MARKERS) or re.search(r"[\d.]+°?\s*c", q):
            if ctx.get("material"):
                process = ctx.get("process") or ctx.get("mode") or "процессе"
                return (
                    f"Что улучшает {message} для {ctx['material']} "
                    f"({process})? Контекст диалога сохранён."
                )

        wants_compare = any(marker in q for marker in COMPARE_MARKERS) or (
            self._is_affirmative(message) and last_assistant and "сравн" in last_assistant.lower()
        )

        if wants_compare:
            if "анодн" in blob_lower and "ni-cu" in blob_lower and "электролиз" in blob_lower:
                return (
                    "Сравни электролиз Ni-Cu сплава при 220°C, Ni-Cu сплава при 250°C "
                    "и анодный никель при 250°C по чистоте Ni в катоде"
                )
            if "220" in blob_lower and "250" in blob_lower and "электролиз" in blob_lower:
                return "Сравни электролиз Ni-Cu сплава при 220°C и 250°C по содержанию Ni в катоде"
            if "ph 9" in blob_lower and "ph 10" in blob_lower and "флотац" in blob_lower:
                return "Сравни флотацию Ni-Cu концентрата при pH 9.0 и pH 10.5 по извлечению Ni"
            if last_user:
                return f"Сравни режимы из контекста диалога. Исходный вопрос: {last_user}. Уточнение: {message}"

        if self._is_affirmative(message) and last_assistant:
            if "сравн" in last_assistant.lower():
                return self._expand_from_dialog("сравни", history)
            if any(marker in last_assistant.lower() for marker in FORMAT_MARKERS):
                return self._expand_format_query(message, history) or f"{last_user}\nДополнение: {message}"
            if last_user:
                return f"{last_user}\nДополнение: {message}"

        return None

    @staticmethod
    def _is_affirmative(message: str) -> bool:
        q = message.strip().lower()
        if not q:
            return False
        if q in AFFIRMATIVE_MARKERS:
            return True
        return any(q.startswith(f"{marker},") or q.startswith(f"{marker} ") or q == marker for marker in AFFIRMATIVE_MARKERS)

    def _is_affirmative_or_compare(self, message: str, history: list[ChatMessage]) -> bool:
        q = message.strip().lower()
        if any(marker in q for marker in COMPARE_MARKERS):
            return True
        if self._is_affirmative(message):
            return True
        if history and self._is_affirmative(message):
            last_assistant = self._last_assistant_message(history)
            if last_assistant and any(w in last_assistant.lower() for w in ("могу", "если нужно", "хотите")):
                return True
        return False

    @staticmethod
    def _is_follow_up(message: str, history: list[ChatMessage] | None = None) -> bool:
        q = message.strip().lower()
        if len(q) > 100:
            return False

        if any(marker in q for marker in DETAIL_MARKERS):
            return bool(history)

        if any(marker in q for marker in FORMAT_MARKERS):
            return bool(history)

        if history and re.search(r"[\d.]+°?\s*c", q) and len(q) < 70:
            return True

        if any(hint in q for hint in MATERIAL_HINTS) and len(q) > 40:
            return False

        if any(marker in q for marker in COMPARE_MARKERS):
            return True

        strong_prefixes = (
            "а ",
            "а как",
            "а кто",
            "а где",
            "а когда",
            "а почему",
            "а что",
            "и ",
            "подробнее",
            "уточни",
            "ещё",
            "еще",
            "расскажи больше",
            "сравни",
            "это ",
            "тот ",
            "та ",
            "те ",
            "второй",
            "первая",
            "предыдущ",
            "его ",
            "её ",
            "ее ",
            "их ",
            "там ",
        )
        if any(q.startswith(prefix) for prefix in strong_prefixes):
            return True

        if ResearchAgent._is_affirmative(message):
            return True

        if len(q) < 45 and not any(hint in q for hint in MATERIAL_HINTS):
            vague_starts = ("какой", "какая", "какие", "кто", "где", "когда", "сколько", "почему")
            if any(q.startswith(start) for start in vague_starts):
                return True

        return False

    @staticmethod
    def _last_user_message(history: list[ChatMessage]) -> str:
        for msg in reversed(history):
            if msg.role == "user":
                return msg.content
        return ""

    @staticmethod
    def _last_assistant_message(history: list[ChatMessage]) -> str:
        for msg in reversed(history):
            if msg.role == "assistant":
                return msg.content
        return ""

    def _clarification_answer(self, result: QueryResult) -> str:
        lines = [result.clarification_prompt or result.answer]
        if result.clarification_options:
            lines.append("")
            lines.append("**Выберите вариант:**")
            for idx, opt in enumerate(result.clarification_options, start=1):
                lines.append(f"{idx}. {opt['label']}")
        return "\n".join(lines)

    @staticmethod
    def _format_source_line(source: dict[str, Any]) -> str:
        title = source.get("title") or source.get("id") or "документ"
        doc_id = source.get("id")
        parts = [f"- {title}"]
        if doc_id and doc_id != title:
            parts.append(f"doc_id={doc_id}")
        if source.get("chunk_id"):
            parts.append(f"chunk={source['chunk_id']}")
        if source.get("page_hint"):
            parts.append(f"стр. {source['page_hint']}")
        if source.get("excerpt_type"):
            parts.append(f"({source['excerpt_type']})")
        snippet = (source.get("snippet") or "")[:240]
        return " · ".join(parts) + f": {snippet}"

    @staticmethod
    def _format_image_line(image: dict[str, Any]) -> str:
        title = image.get("title") or image.get("id") or "рисунок"
        parts = [f"- {title}"]
        if image.get("doc_id"):
            parts.append(f"doc_id={image['doc_id']}")
        if image.get("page"):
            parts.append(f"стр. {image['page']}")
        if image.get("score") is not None:
            parts.append(f"score={image['score']}")
        snippet = (image.get("snippet") or "")[:160]
        return " · ".join(parts) + (f": {snippet}" if snippet else "")

    def _fallback_answer(self, result: QueryResult) -> str:
        return format_structured_answer(result)

    def _llm_answer(
        self,
        question: str,
        result: QueryResult,
        prior_history: list[ChatMessage],
        *,
        wants_table: bool = False,
    ) -> str:
        sources_text = "\n".join(
            self._format_source_line(s) for s in result.sources
        ) or "нет"
        images_text = "\n".join(
            self._format_image_line(img) for img in result.images
        ) or "нет"
        related_text = ", ".join(r.get("name", "") for r in result.related_entities[:10])
        context = TOOL_CONTEXT_TEMPLATE.format(
            graph_answer=result.answer,
            sources=sources_text,
            images=images_text,
            related=related_text or "нет",
        )

        user_content = f"{question}\n\n{context}"
        if wants_table:
            user_content += TABLE_USER_INSTRUCTION

        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in prior_history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_content})
        return self.llm.chat_sync(messages)
