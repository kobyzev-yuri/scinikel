"""Tests for POST /api/search/image (этап 6c)."""

import io

from fastapi.testclient import TestClient

from scinikel.api.app import app

client = TestClient(app)


def test_search_image_rejects_non_image():
    res = client.post(
        "/api/search/image",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert res.status_code == 400


def test_search_image_accepts_png():
    # Minimal 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    res = client.post(
        "/api/search/image",
        files={"file": ("query.png", io.BytesIO(png), "image/png")},
    )
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert data["backend"] in ("openclip+qdrant", "unavailable")
