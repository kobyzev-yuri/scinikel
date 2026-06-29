"""Tests for document chunking."""

from scinikel.search.chunking import chunk_text


def test_chunk_splits_long_document():
    text = "Абзац один про флотацию.\n\n" + ("Слово " * 200) + "\n\nАбзац про электролиз 250°C."
    chunks = chunk_text("doc-test", text, metadata={"title": "Тест"}, chunk_size=200, chunk_overlap=40)
    assert len(chunks) >= 2
    assert all(c.doc_id == "doc-test" for c in chunks)
    assert all(c.chunk_id.startswith("doc-test#c") for c in chunks)


def test_chunk_vision_section_separate():
    text = (
        "Введение без цифр.\n\n"
        "--- Описание изображений (Vision) ---\n"
        "[fig1, стр. 6]\nГрафик извлечения Ni: ε₀=0,87."
    )
    chunks = chunk_text("doc-giab", text, metadata={"title": "GIAB"})
    assert any("ε₀" in c.text or "никеля" in c.text.lower() for c in chunks)
    vision_chunks = [c for c in chunks if c.page == 6 or "стр" in c.text.lower()]
    assert vision_chunks


def test_chunk_extracts_experiment_ids():
    text = "Результаты EXP-2024-031 при 250°C показали 99.2% Ni."
    chunks = chunk_text("DOC-089", text, metadata={"title": "Электролиз"})
    assert chunks[0].experiment_ids == ["EXP-2024-031"]


def test_page_prefix_from_pdf_marker():
    text = "[стр. 4]\nСодержание Ca²⁺ 27,52 мг/дм³ в пульпе."
    chunks = chunk_text("doc-pdf", text, metadata={"title": "PDF"})
    assert chunks[0].page == 4
