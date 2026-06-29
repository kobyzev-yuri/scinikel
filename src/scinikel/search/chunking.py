"""Разбиение документов на чанки для BM25 и dense-поиска."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scinikel.search.snippet import VISION_MARKER

DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 120

PAGE_PREFIX_RE = re.compile(r"^\[стр\.\s*(\d+)\]\s*", re.MULTILINE | re.IGNORECASE)
EXP_ID_RE = re.compile(r"EXP-\d{4}-\d+", re.IGNORECASE)


@dataclass
class TextChunk:
    chunk_id: str
    doc_id: str
    text: str
    chunk_index: int
    page: int | None = None
    title: str = ""
    doc_type: str = ""
    experiment_ids: list[str] = field(default_factory=list)


def _experiment_ids_in_text(text: str) -> list[str]:
    return list(dict.fromkeys(m.upper() for m in EXP_ID_RE.findall(text)))


def _page_from_text(text: str) -> int | None:
    match = PAGE_PREFIX_RE.search(text)
    if match:
        return int(match.group(1))
    page_m = re.search(r"стр\.?\s*(\d+)", text, flags=re.IGNORECASE)
    return int(page_m.group(1)) if page_m else None


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Вернуть (section_kind, body): main | vision."""
    if VISION_MARKER in text:
        main, vision = text.split(VISION_MARKER, 1)
        sections: list[tuple[str, str]] = []
        if main.strip():
            sections.append(("main", main.strip()))
        if vision.strip():
            sections.append(("vision", vision.strip()))
        return sections
    marker = "--- Описание изображений (Vision) ---"
    if marker in text:
        main, vision = text.split(marker, 1)
        sections = []
        if main.strip():
            sections.append(("main", main.strip()))
        if vision.strip():
            sections.append(("vision", vision.strip()))
        return sections
    return [("main", text.strip())]


def _paragraphs(body: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    if parts:
        return parts
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return lines or [body.strip()]


def _pack_paragraphs(
    paragraphs: list[str],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        chunks.append("\n\n".join(current))
        if chunk_overlap > 0 and chunks[-1]:
            tail = chunks[-1][-chunk_overlap:]
            current = [tail] if tail.strip() else []
            current_len = len(tail)
        else:
            current = []
            current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if para_len > chunk_size:
            flush()
            start = 0
            while start < para_len:
                end = min(start + chunk_size, para_len)
                chunks.append(para[start:end])
                if end >= para_len:
                    break
                start = max(end - chunk_overlap, start + 1)
            current = []
            current_len = 0
            continue

        extra = para_len + (2 if current else 0)
        if current and current_len + extra > chunk_size:
            flush()
        current.append(para)
        current_len += extra

    flush()
    return [c.strip() for c in chunks if c.strip()]


def chunk_text(
    doc_id: str,
    text: str,
    *,
    metadata: dict | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Нарезать документ на чанки с page/experiment metadata."""
    meta = metadata or {}
    title = str(meta.get("title") or doc_id)
    doc_type = str(meta.get("doc_type") or "")
    extra_exps = meta.get("experiment_ids") or []
    if isinstance(extra_exps, str):
        extra_exps = [extra_exps]

    if not text or not text.strip():
        return []

    chunks: list[TextChunk] = []
    chunk_counter = 0

    for section_kind, body in _split_sections(text):
        if section_kind == "vision":
            vision_parts = re.split(r"\n(?=\[)", body)
            paragraphs = [p.strip() for p in vision_parts if p.strip()]
        else:
            paragraphs = _paragraphs(body)

        for piece in _pack_paragraphs(
            paragraphs,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            page = _page_from_text(piece)
            exp_ids = list(dict.fromkeys([*extra_exps, *_experiment_ids_in_text(piece)]))
            chunk_id = f"{doc_id}#c{chunk_counter}"
            chunk_counter += 1
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    text=piece,
                    chunk_index=chunk_counter - 1,
                    page=page,
                    title=title,
                    doc_type=doc_type,
                    experiment_ids=exp_ids,
                )
            )

    return chunks
