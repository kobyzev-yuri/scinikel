"""Tests for PDF image cache (3dtoday-aligned vision + CLIP helpers)."""

from pathlib import Path

import pytest

from scinikel.search.pdf_images import (
    index_pdf_images,
    media_image_url,
    persist_pdf_images,
    resolve_image_file,
)


def test_persist_pdf_images_copies_to_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("scinikel.search.pdf_images.IMAGE_CACHE_ROOT", tmp_path / "cache")
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    images = [{"temp_path": str(src), "page": 4, "alt": "Страница 4, рис. 1", "mime_type": "image/png"}]
    stored = persist_pdf_images("doc-test", images)
    assert len(stored) == 1
    assert stored[0]["image_id"] == "doc-test-p4-i1"
    assert Path(stored[0]["image_path"]).exists()
    assert resolve_image_file("doc-test-p4-i1") == Path(stored[0]["image_path"])


def test_resolve_with_jpeg_extension(tmp_path, monkeypatch):
    monkeypatch.setattr("scinikel.search.pdf_images.IMAGE_CACHE_ROOT", tmp_path / "cache")
    doc_id = "doc-giab-ni-cu-flotation-water"
    cache = tmp_path / "cache" / doc_id
    cache.mkdir(parents=True)
    f = cache / f"{doc_id}-p4-i1.jpeg"
    f.write_bytes(b"jpeg")
    assert resolve_image_file(f"{doc_id}-p4-i1.jpeg") == f
    assert media_image_url(f"{doc_id}-p4-i1.jpeg") == f"/api/media/images/{doc_id}-p4-i1"


def test_resolve_same_page_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("scinikel.search.pdf_images.IMAGE_CACHE_ROOT", tmp_path / "cache")
    doc_id = "doc-giab-ni-cu-flotation-water"
    cache = tmp_path / "cache" / doc_id
    cache.mkdir(parents=True)
    only = cache / f"{doc_id}-p8-i1.png"
    only.write_bytes(b"png")
    assert resolve_image_file(f"{doc_id}-p8-i4") == only
    assert media_image_url(f"{doc_id}-p8-i4") == f"/api/media/images/{doc_id}-p8-i1"


def test_index_pdf_images_without_clip_uses_alt(monkeypatch):
    class FakeIndex:
        def index_image(self, image_id, path, meta):
            assert meta.get("content")
            return False

    giab = Path(__file__).resolve().parents[1] / "data" / "samples" / "giab-ni-cu-flotation-water.pdf"
    if not giab.exists():
        pytest.skip("GIAB sample PDF not present")
    from scinikel.ingest.pdf_parser import parse_pdf

    monkeypatch.setattr("scinikel.config.settings.vision_enabled", False)
    parsed = parse_pdf(giab, max_pages=5)
    images = parsed.get("images") or []
    if not images:
        pytest.skip("No images extracted (PyMuPDF?)")
    n = index_pdf_images(
        FakeIndex(), "doc-giab-ni-cu-flotation-water", images, "giab", analyze_images=False
    )
    assert n == 0
