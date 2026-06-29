"""Извлечённые из PDF рисунки: кэш, Vision (3dtoday), CLIP-индекс в Qdrant."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from scinikel.search.sample_docs import REPO_ROOT

logger = logging.getLogger(__name__)

IMAGE_CACHE_ROOT = REPO_ROOT / "data" / "samples" / ".cache" / "images"
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp)$", re.IGNORECASE)


def strip_image_extension(image_id: str) -> str:
    """Убрать .jpeg/.png из id — URL API без расширения."""
    return _IMAGE_EXT.sub("", (image_id or "").strip())


def image_cache_dir(doc_id: str) -> Path:
    return IMAGE_CACHE_ROOT / doc_id


def persist_pdf_images(doc_id: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Скопировать рисунки из /tmp в постоянный кэш (scinikel; в 3dtoday — только /tmp)."""
    if not images:
        return []
    cache = image_cache_dir(doc_id)
    cache.mkdir(parents=True, exist_ok=True)
    stored: list[dict[str, Any]] = []
    per_page: dict[int, int] = {}
    for img in images:
        src = img.get("temp_path") or img.get("url")
        if not src or not Path(src).exists():
            continue
        page = int(img.get("page") or 1)
        per_page[page] = per_page.get(page, 0) + 1
        img_idx = per_page[page]
        ext = Path(src).suffix or ".png"
        image_id = f"{doc_id}-p{page}-i{img_idx}"
        dest = cache / f"{image_id}{ext}"
        if not dest.exists() or dest.stat().st_size == 0:
            shutil.copy2(src, dest)
        try:
            rel_path = dest.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_path = str(dest)
        stored.append(
            {
                **img,
                "image_id": image_id,
                "image_path": str(dest),
                "image_relpath": rel_path,
                "alt": img.get("alt") or f"Страница {page}, рис. {img_idx}",
            }
        )
    canonical_ids = {row["image_id"] for row in stored}
    prune_stale_cache(doc_id, canonical_ids)
    return stored


def prune_stale_cache(doc_id: str, canonical_ids: set[str]) -> int:
    """Удалить устаревшие файлы (p7-i3 при каноническом p7-i1)."""
    cache = image_cache_dir(doc_id)
    if not cache.is_dir():
        return 0
    removed = 0
    for path in cache.iterdir():
        if path.is_file() and path.stem not in canonical_ids:
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        logger.info("Pruned %s stale image files for %s", removed, doc_id)
    return removed


def canonical_image_file(doc_id: str, page: int) -> Path | None:
    """Канонический файл рисунка: всегда …-p{page}-i1."""
    cache = image_cache_dir(doc_id)
    if not cache.is_dir():
        return None
    for pattern in (f"{doc_id}-p{page}-i1.*", f"{doc_id}-p{page}-i*"):
        found = sorted(p for p in cache.glob(pattern) if p.is_file())
        if found:
            return found[0]
    return None


def normalize_image_id(image_id: str) -> str:
    """Старый id из Qdrant (p7-i3) → канонический (p7-i1), без расширения."""
    image_id = strip_image_extension(image_id)
    m = re.match(r"^(?P<doc>.+)-p(?P<page>\d+)-i\d+$", image_id)
    if not m:
        return image_id
    canonical = canonical_image_file(m.group("doc"), int(m.group("page")))
    return canonical.stem if canonical else image_id


def has_stale_image_ids(doc_id: str) -> bool:
    """В кэше или Qdrant остались id с глобальной нумерацией (i2, i3…)."""
    cache = image_cache_dir(doc_id)
    if cache.is_dir():
        for path in cache.iterdir():
            if path.is_file() and re.search(r"-p\d+-i[2-9]\d*$", path.stem):
                return True
    try:
        from scinikel.search.vector_db import get_vector_db

        vdb = get_vector_db()
        if vdb.image_available:
            for row in vdb.scroll_doc_images(doc_id):
                if re.search(r"-p\d+-i[2-9]\d*$", row.get("id") or ""):
                    return True
    except Exception:
        pass
    return False


def _analysis_by_page(image_analyses: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in image_analyses or []:
        page = row.get("page")
        if page is not None:
            out[int(page)] = row
    return out


def _vision_metadata_for_image(
    img: dict[str, Any],
    *,
    analyze_images: bool,
    precomputed: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Паттерн 3dtoday/main.add_article_from_parse:
    vision_analyzer → check_relevance → content в payload Qdrant.
    """
    if not analyze_images:
        return None

    page = img.get("page")
    row = (precomputed or {}).get(int(page)) if page is not None else None
    if row:
        analysis_text = row.get("analysis", "")
        if analysis_text:
            return {
                "content": analysis_text,
                "abstract": analysis_text[:500],
                "vision_provider": row.get("provider"),
                "excerpt_type": "vision",
            }

    try:
        from scinikel.agent.curator import CuratorAgent
        from scinikel.config import settings

        if not settings.vision_enabled:
            return None
        batch = CuratorAgent()._analyze_images_sync([img])
        if not batch or not batch.get("image_analyses"):
            return None
        analysis_text = batch["image_analyses"][0].get("analysis", "")
        if not analysis_text:
            return None
        return {
            "content": analysis_text,
            "abstract": analysis_text[:500],
            "vision_provider": batch.get("provider"),
            "excerpt_type": "vision",
        }
    except Exception as exc:
        logger.warning("Vision for image p%s failed: %s", page, exc)
        return None


def analyze_pdf_images(images: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Vision по всем рисункам PDF — для слияния в BM25 (как kb_librarian._analyze_images)."""
    if not images:
        return None
    try:
        from scinikel.agent.curator import CuratorAgent

        return CuratorAgent()._analyze_images_sync(images)
    except Exception as exc:
        logger.warning("PDF image batch vision failed: %s", exc)
        return None


def merge_vision_into_content(content: str, image_analysis: dict[str, Any] | None) -> str:
    from scinikel.agent.curator import CuratorAgent

    return CuratorAgent._merge_image_context(content, image_analysis)


def index_pdf_images(
    doc_index: Any,
    doc_id: str,
    images: list[dict[str, Any]],
    title: str,
    *,
    analyze_images: bool = True,
    image_analyses: list[dict[str, Any]] | None = None,
) -> int:
    """
    Vision-gated CLIP index — article_indexer.index_image() в 3dtoday.
    """
    from scinikel.search.vector_db import get_vector_db

    vdb = get_vector_db()
    if vdb.image_available:
        vdb.delete_doc_images(doc_id)

    persisted = persist_pdf_images(doc_id, images)
    precomputed = _analysis_by_page(image_analyses)
    indexed = 0
    for img in persisted:
        path = img.get("image_path")
        image_id = img.get("image_id")
        if not path or not image_id or not Path(path).exists():
            continue

        vision_meta = _vision_metadata_for_image(
            img, analyze_images=analyze_images, precomputed=precomputed
        )
        from scinikel.config import settings

        if analyze_images and settings.vision_enabled and vision_meta is None:
            # 3dtoday: нерелевантные / не проанализированные — пропуск
            logger.debug("Skip image %s (vision gate)", image_id)
            continue

        alt = img.get("alt", "")
        meta: dict[str, Any] = {
            "title": title,
            "alt": alt,
            "page": img.get("page"),
            "doc_id": doc_id,
            "doc_title": title,
            "image_path": path,
            "image_relpath": img.get("image_relpath"),
            "mime_type": img.get("mime_type"),
            "content_type": "image",
        }
        if vision_meta:
            from scinikel.agent.curator import CuratorAgent

            ann = CuratorAgent.librarian_annotate_vision(
                vision_meta["content"],
                page=img.get("page"),
                image_name=alt,
            )
            meta.update(vision_meta)
            meta["vision_raw"] = vision_meta["content"]
            meta["librarian_annotation"] = ann["annotation"]
            meta["figure_type"] = ann["figure_type"]
            meta["key_points"] = ann["key_points"]
            meta["content"] = ann["annotation"]
            meta["abstract"] = ann["annotation"][:500]
            meta["title"] = ann["figure_type"]
        elif not analyze_images:
            meta["content"] = alt
            meta["abstract"] = alt[:200]

        if doc_index.index_image(image_id, path, meta):
            indexed += 1

    if indexed:
        logger.info("Indexed %s images for %s (vision=%s)", indexed, doc_id, analyze_images)
    return indexed


def resolve_image_file(image_id: str) -> Path | None:
    """
    Найти канонический файл рисунка (…-p{N}-i1).
    """
    if not image_id:
        return None

    image_id = normalize_image_id(image_id)
    path = _find_in_cache(image_id)
    if path:
        return path

    path = _find_from_qdrant_path(image_id)
    if path and path.is_file():
        return path

    m = re.match(r"^(?P<doc>.+)-p(?P<page>\d+)-i\d+$", image_id)
    if m:
        return canonical_image_file(m.group("doc"), int(m.group("page")))
    return None


def media_image_url(image_id: str) -> str | None:
    """URL API только если файл реально найден на диске."""
    path = resolve_image_file(image_id)
    if not path:
        return None
    return f"/api/media/images/{path.stem}"


def _find_in_cache(image_id: str) -> Path | None:
    if not IMAGE_CACHE_ROOT.exists():
        return None
    stem = strip_image_extension(image_id)
    for path in IMAGE_CACHE_ROOT.rglob(f"{stem}.*"):
        if path.is_file():
            return path
    exact = list(IMAGE_CACHE_ROOT.rglob(stem))
    return exact[0] if exact and exact[0].is_file() else None


def _find_from_qdrant_path(image_id: str) -> Path | None:
    try:
        from scinikel.search.vector_db import get_vector_db

        vdb = get_vector_db()
        if not vdb.image_available:
            return None
        payload = vdb.get_image_payload(image_id)
        if not payload and image_id != strip_image_extension(image_id):
            payload = vdb.get_image_payload(strip_image_extension(image_id))
        if not payload:
            return None
        for key in ("image_path", "image_relpath"):
            raw = payload.get(key)
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = REPO_ROOT / raw
            if path.is_file():
                return path
    except Exception as exc:
        logger.debug("Qdrant image path lookup %s: %s", image_id, exc)
    return None


def _find_same_page_fallback(image_id: str) -> Path | None:
    """Если Qdrant хранит старый id (p8-i4), а в кэше только p8-i1."""
    m = re.match(r"^(?P<doc>.+)-p(?P<page>\d+)-i\d+$", image_id)
    if not m:
        return None
    doc_id = m.group("doc")
    page = m.group("page")
    cache = image_cache_dir(doc_id)
    if not cache.is_dir():
        return None
    candidates = sorted(cache.glob(f"{doc_id}-p{page}-i*"))
    return candidates[0] if candidates else None
